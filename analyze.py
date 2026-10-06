import datetime
import os
from dateutil.relativedelta import relativedelta
from difflib import SequenceMatcher

import anthropic

from models.account import Account, Accounts
from models.balance_entry import BalanceEntries
from models.budget_target import BudgetTargets
from models.household import Household
from models.net_worth_item import NetWorthItems
from models.transaction import Transaction


def parse_income(value, amount: float) -> bool:
    """The model's income field ("1"/"0"). Falls back to the sign when it's
    missing or garbled, and never lets a debit count as income."""
    if amount < 0:
        return False
    value = (value or "").strip()
    if value in ("0", "1"):
        return value == "1"
    return amount >= 0


class TransactionAnalyzer:
    def __init__(self, transaction: Transaction):
        household = Household.load_by_account_id(transaction.account_id)
        self.client = anthropic.Anthropic(api_key=household.get_anthropic_key())
        self.transaction = transaction
        self.account = Account.load(self.transaction.account_id)

    def analyze_transaction(self, account_transactions=None):
        """
        Analyzes a bank transaction row using Claude to determine category, sub-category and need.

        Returns:
            dict: A dictionary with 'category', 'sub_category', 'need' (str) and
            'income' (bool) keys.
        """
        similar_transactions = SimilarTransactions(
            transaction=self.transaction
        ).find_similar(account_transactions=account_transactions)

        if similar_transactions:
            similar_transaction_string = "\n".join(
                f"Description: {t.description}, Amount: {t.amount}, "
                f"Account: {self.account.description}: {self.account.type}, "
                f"Date: {t.date}, Category: {t.category}, Sub-category: {t.sub_category}, "
                f"Type: {t.type}"
                for t in similar_transactions
            )
            similar_section = f"""The following are past transactions with similar descriptions that have already been categorized by the user.
Use these as your primary reference — match their category and sub-category unless the new transaction is clearly different:
{similar_transaction_string}"""
        else:
            similar_section = "No similar past transactions were found. Use the transaction details and your knowledge to categorize it."

        prompt = f"""You are a financial assistant. Categorize the following bank transaction into a category, sub-category, and need.

Transaction Details:
- Description: {self.transaction.description}
- Amount: {self.transaction.amount} (negative = expense/debit, positive = income/credit)
- Date: {self.transaction.date}
- Account: {self.account.description} ({self.account.type})

{similar_section}

Rules:
- If the description contains "transfer" or it is a credit card payment, set category to "Transfer" and choose an appropriate sub-category (e.g. "Credit Card Payment", "Account Transfer").
- Need means it is an essential expense: mortgage, rent, car payment, groceries, gas, utilities, healthcare, insurance, etc. Return 1 for True, 0 for False.
- Set need to 0 for transfers, credit card payments, and income deposits.
- Income means real earnings: salary/payroll, interest, dividends, gifts, side income. Return 1 for income, 0 otherwise.
- Refunds, returns, merchant credits, chargebacks, and reimbursements are NOT income (income = 0) — they are money coming back against spending. Categorize them exactly like the purchase they reverse (e.g. an Amazon return is "Shopping, Online", not "Refund"), and give them the need value that purchase would have.
- Negative amounts are never income (income = 0).
- Do not use "Expense" as a category.
- The category and sub-category must never be the same.
- If the description contains "Venmo" or "PayPal", set category to "Dining" and sub-category to "Dining Out" unless similar past transactions clearly indicate otherwise.

Response format:
Return only the category, sub-category, need, and income separated by commas (e.g. "Groceries, Supermarket, 1, 0"). No extra text."""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            parts = response.content[0].text.split(",", 3)
            return {
                "category": parts[0].strip(),
                "sub_category": parts[1].strip(),
                "need": parts[2].strip(),
                "income": parse_income(
                    parts[3] if len(parts) > 3 else None, self.transaction.amount
                ),
            }
        except Exception as e:
            print(f"Error analyzing transaction: {e}")
            return {
                "category": "Unknown",
                "sub_category": "Unknown",
                "need": "0",
                "income": parse_income(None, self.transaction.amount),
            }

    def reanalyze_transaction(self):
        response = self.analyze_transaction()
        self.transaction.category = response["category"].strip()
        self.transaction.sub_category = response["sub_category"].strip()
        self.transaction.need = (
            True if response["need"].strip() == "1" else False
        )
        self.transaction.income = response["income"]
        self.transaction.save()
        return self.transaction


def normalize_description(desc: str) -> str:
    """Strip any token containing a digit — removes reference numbers and transaction IDs."""
    return " ".join(token for token in desc.split() if not any(c.isdigit() for c in token))


class SimilarTransactions:
    def __init__(self, transaction: Transaction):
        """
        Initializes the SimilarTransactionFinder with a list of transactions.
        """
        self.transaction = transaction

    def find_similar(
        self, threshold=0.8, account_transactions=None, months: int = 12
    ) -> list[Transaction]:
        """
        Finds transactions similar to the given transaction based on description similarity.

        Args:
            threshold (float): The similarity threshold (0 to 1).
            account_transactions: Pre-fetched list of transactions to search, or None to query DB.
            months (int): How far back to look when querying the DB (default 12).

        Returns:
            list: A list of similar Transaction objects.
        """

        def similarity(desc1, desc2):
            return SequenceMatcher(None, normalize_description(desc1), normalize_description(desc2)).ratio()

        if account_transactions is None:
            account_transactions = Transaction.load_by_filter(
                Transaction.account_id == self.transaction.account_id,
                Transaction.id != self.transaction.id,
                Transaction.date
                >= (datetime.datetime.now() - relativedelta(months=months)),
                limit=None,
            )

        return [
            t for t in account_transactions
            if similarity(self.transaction.description, t.description) >= threshold
        ]


class BatchTransactionAnalyzer:
    def __init__(self, account: Account):
        household = Household.load_by_account_id(account.id)
        self.claude_api_key = household.get_anthropic_key() if household.anthropic_api_key else os.environ["CLAUDE_DEFAULT_API_KEY"]
        self.client = anthropic.Anthropic(api_key=self.claude_api_key)
        self.account = account

    def _build_reference_pool(self, reference_transactions: list[Transaction]) -> str:
        """
        Build a deduplicated reference string from categorized historical transactions.
        Strips duplicates by normalized description so the prompt stays concise.
        """
        categorized = [t for t in reference_transactions if t.category not in ("Unknown", "Transfer")]
        seen = set()
        unique_refs = []
        for t in categorized:
            key = normalize_description(t.description)
            if key and key not in seen:
                seen.add(key)
                unique_refs.append(t)

        if not unique_refs:
            return "No past categorized transactions available."

        lines = "\n".join(
            f"- {t.description}: {t.category} / {t.sub_category}"
            + (" (refund)" if not t.is_income and t.amount > 0 else "")
            for t in unique_refs[:100]  # cap at 100 to keep prompt manageable
        )
        return f"Past categorized transactions for reference (match these where descriptions are similar):\n{lines}"

    def analyze_batch(
        self,
        transactions: list[Transaction],
        reference_transactions: list[Transaction] = None,
    ) -> list[dict]:
        """
        Categorize up to 50 transactions in a single API call.

        Returns:
            list of dicts with 'category', 'sub_category', 'need' (str) and
            'income' (bool) for each transaction, in the same order as the
            input list.
        """
        if not transactions:
            return []

        reference_section = self._build_reference_pool(reference_transactions or [])

        tx_lines = "\n".join(
            f"{i + 1}. Description: {t.description} | Amount: {t.amount} | Date: {t.date.strftime('%Y-%m-%d')}"
            for i, t in enumerate(transactions)
        )

        prompt = f"""You are a financial assistant. Categorize the following bank transactions.

Account: {self.account.description} ({self.account.type})

{reference_section}

Rules:
- If the description contains "transfer" or it is a credit card payment, set category to "Transfer" and choose an appropriate sub-category (e.g. "Credit Card Payment", "Account Transfer").
- Need means it is an essential expense: mortgage, rent, car payment, groceries, gas, utilities, healthcare, insurance, etc. Return 1 for True, 0 for False.
- Set need to 0 for transfers, credit card payments, and income deposits.
- Income means real earnings: salary/payroll, interest, dividends, gifts, side income. Return 1 for income, 0 otherwise.
- Refunds, returns, merchant credits, chargebacks, and reimbursements are NOT income (income = 0) — they are money coming back against spending. Categorize them exactly like the purchase they reverse (e.g. an Amazon return is "Shopping, Online", not "Refund"), and give them the need value that purchase would have.
- Negative amounts are never income (income = 0).
- Do not use "Expense" as a category.
- The category and sub-category must never be the same.
- Negative amount = money out (debit), positive = money in (credit).
- If the description contains "Venmo" or "PayPal", set category to "Dining" and sub-category to "Dining Out" unless a similar past transaction clearly indicates otherwise.

Transactions to categorize:
{tx_lines}

Response format:
Return exactly {len(transactions)} lines, one per transaction, numbered to match:
1. Category, Sub-category, need, income
2. Category, Sub-category, need, income
...

No extra text."""

        fallback = {"category": "Unknown", "sub_category": "Unknown", "need": "0"}

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=len(transactions) * 35,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )

            lines = [l.strip() for l in response.content[0].text.strip().split("\n") if l.strip()]
            results = []
            for line in lines:
                # Strip leading "N." prefix
                if line and line[0].isdigit():
                    line = line.split(".", 1)[-1].strip()
                parts = line.split(",", 3)
                # A 3-field line (model skipped income) is still usable;
                # income falls back to the sign below.
                if len(parts) >= 3:
                    results.append({
                        "category": parts[0].strip(),
                        "sub_category": parts[1].strip(),
                        "need": parts[2].strip(),
                        "income": parts[3] if len(parts) > 3 else None,
                    })
                else:
                    print(f"Unexpected batch response line: {line!r}")
                    results.append(fallback)

            # Pad if model returned fewer lines than expected
            while len(results) < len(transactions):
                results.append(fallback)

            results = results[:len(transactions)]

        except Exception as e:
            print(f"Error analyzing batch: {e}")
            results = [fallback for _ in transactions]

        return [
            {**result, "income": parse_income(result.get("income"), t.amount)}
            for result, t in zip(results, transactions)
        ]


class BudgetAnalyzer:
    def __init__(self, household_id: int):
        household = Household.load(household_id)
        self.client = anthropic.Anthropic(api_key=household.get_anthropic_key())
        self.household_id = household_id

    def get_date_range(self) -> tuple:
        """Return (from_date, to_date) covering the last 3 complete months plus
        the current month to date. to_date is exclusive (start of tomorrow), so
        the cache key rolls over daily and a cached analysis never describes a
        stale point in the month."""
        today = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from_date = today.replace(day=1) - relativedelta(months=3)
        to_date = today + datetime.timedelta(days=1)
        return from_date, to_date

    def count_transactions(
        self,
        from_date: datetime.datetime,
        to_date: datetime.datetime,
    ) -> int:
        """Count non-Transfer transactions for the household in the given date range."""
        accounts = Accounts.load_by_household_id(self.household_id).accounts
        transactions = Transaction.load_by_filter(
            Transaction.date >= from_date,
            Transaction.date < to_date,
            Transaction.category != "Transfer",
            column=Transaction.account_id,
            values=[a.id for a in accounts],
            limit=None,
        )
        return len(transactions)

    def net_worth_text(self) -> tuple:
        """Balance-sheet section for the prompt; empty when nothing is tracked.

        Returns:
            tuple: (text, has_debts) — has_debts is True when any debt item
            carries a positive balance.
        """
        items = NetWorthItems.load_by_household_id(self.household_id).items
        if not items:
            return "", False
        entries = BalanceEntries.load_by_item_ids(
            [i.id for i in items]
        ).entries
        latest = BalanceEntries.latest_per_item(entries)

        def balance(item):
            entry = latest.get(item.id)
            return entry.balance if entry else 0.0

        lines = ["", "The household also tracks assets and debts (current balances):"]
        assets = [i for i in items if i.kind == "asset"]
        debts = [i for i in items if i.kind == "debt"]
        if assets:
            lines.append("  Assets:")
            for item in sorted(assets, key=balance, reverse=True):
                lines.append(f"    {item.name} ({item.type}): ${balance(item):,.2f}")
        if debts:
            lines.append("  Debts:")
            for item in sorted(debts, key=balance, reverse=True):
                extras = []
                if item.interest_rate:
                    extras.append(f"{item.interest_rate}% APR")
                if item.minimum_payment:
                    extras.append(f"${item.minimum_payment:,.2f}/month minimum")
                suffix = f" — {', '.join(extras)}" if extras else ""
                lines.append(
                    f"    {item.name} ({item.type}): ${balance(item):,.2f}{suffix}"
                )

        total_assets = sum(balance(i) for i in assets)
        total_debts = sum(balance(i) for i in debts)
        lines.append(
            f"  Totals: assets ${total_assets:,.2f}, debts ${total_debts:,.2f}, "
            f"net worth ${total_assets - total_debts:,.2f}"
        )
        series = NetWorthItems.net_worth_series(self.household_id, months=4)
        lines.append(
            "  Net worth by month: "
            + " -> ".join(f"{p['month']}: ${p['net_worth']:,.2f}" for p in series)
        )
        has_debts = any(balance(i) > 0 for i in debts)
        return "\n".join(lines) + "\n", has_debts

    def generate_analysis(
        self,
        from_date: datetime.datetime,
        to_date: datetime.datetime,
    ) -> tuple:
        """
        Generates a budget analysis for the given date range using Claude.

        Returns:
            tuple: (analysis_text, transaction_count)
        """
        accounts = Accounts.load_by_household_id(self.household_id).accounts
        account_ids = [a.id for a in accounts]

        today = datetime.datetime.now()
        targets = BudgetTargets.load_by_household_id(self.household_id).targets

        monthly_summaries = []
        total_count = 0
        in_progress_month = None
        current = from_date
        while current < to_date:
            next_month = current + relativedelta(months=1)
            transactions = Transaction.load_by_filter(
                Transaction.date >= current,
                Transaction.date < min(next_month, to_date),
                Transaction.category != "Transfer",
                column=Transaction.account_id,
                values=account_ids,
                limit=None,
            )

            total_count += len(transactions)
            # Refunds (income=False, positive) net down expenses rather than
            # counting as income.
            income = sum(t.amount for t in transactions if t.income)
            expenses = -sum(t.amount for t in transactions if not t.income)

            categories = {}
            for t in transactions:
                cat = categories.setdefault(t.category, {"total": 0.0, "subs": {}})
                cat["total"] += t.amount
                cat["subs"][t.sub_category] = (
                    cat["subs"].get(t.sub_category, 0.0) + t.amount
                )

            top_expenses = sorted(
                (t for t in transactions if not t.income and t.amount < 0),
                key=lambda t: t.amount,
            )[:10]

            month = {
                "month": current.strftime("%B %Y"),
                "income": round(income, 2),
                "expenses": round(expenses, 2),
                "net": round(income - expenses, 2),
                "categories": categories,
                "top_expenses": top_expenses,
                "progress": None,
            }
            if current <= today < next_month:
                # Precompute pacing so the model doesn't have to do the math
                days_elapsed = today.day
                days_in_month = (next_month - current).days
                month["progress"] = {
                    "days_elapsed": days_elapsed,
                    "days_in_month": days_in_month,
                    "fraction": days_elapsed / days_in_month,
                }
                in_progress_month = month
            monthly_summaries.append(month)
            current = next_month

        summary_text = ""
        for month in monthly_summaries:
            progress = month["progress"]
            if progress:
                summary_text += (
                    f"\n{month['month']} (IN PROGRESS — month to date, day "
                    f"{progress['days_elapsed']} of {progress['days_in_month']}, "
                    f"{progress['fraction']:.0%} of the month elapsed):\n"
                )
            else:
                summary_text += f"\n{month['month']}:\n"
            summary_text += f"  Total Income:   ${month['income']:,.2f}\n"
            summary_text += f"  Total Expenses: ${month['expenses']:,.2f}\n"
            summary_text += f"  Net:            ${month['net']:,.2f}\n"
            if progress and progress["fraction"] < 1:
                projected = month["expenses"] / progress["fraction"]
                summary_text += (
                    f"  Expenses projected to month end at a straight-line "
                    f"pace: ${projected:,.2f}\n"
                )
            if progress and targets:
                summary_text += "  Month-to-date progress against targets:\n"
                for t in targets:
                    spent = -month["categories"].get(t.category, {}).get("total", 0.0)
                    pct = spent / t.monthly_limit if t.monthly_limit else 0
                    summary_text += (
                        f"    {t.category}: ${spent:,.2f} of "
                        f"${t.monthly_limit:,.2f} ({pct:.0%} used)\n"
                    )
            summary_text += "  Spending by Category:\n"
            for cat, data in sorted(
                month["categories"].items(), key=lambda x: x[1]["total"]
            ):
                summary_text += f"    {cat}: ${data['total']:,.2f}\n"
                # sub-category lines are redundant when there's only one
                if len(data["subs"]) > 1:
                    for sub, amount in sorted(data["subs"].items(), key=lambda x: x[1]):
                        summary_text += f"      - {sub}: ${amount:,.2f}\n"
            summary_text += "  Largest individual expenses:\n"
            for t in month["top_expenses"]:
                summary_text += (
                    f"    {t.date.strftime('%Y-%m-%d')}  {t.description}: "
                    f"${t.amount:,.2f} ({t.category} / {t.sub_category})\n"
                )

        if targets:
            target_lines = "\n".join(
                f"  {t.category}: ${t.monthly_limit:,.2f}/month"
                for t in targets
            )
            targets_text = f"""

The household has set these monthly budget targets:
{target_lines}
"""
        else:
            targets_text = """

The household has not set any monthly budget targets yet.
"""

        net_worth_text, has_debts = self.net_worth_text()
        balance_sheet_point = (
            "\n7. Balance sheet: comment on the net worth trend and how it connects to cash flow — is monthly net income actually showing up as net worth growth? Celebrate growth explicitly when it's there, and if net worth is flat or down, point to the specific lever that would turn it around."
            if net_worth_text
            else ""
        )
        debt_payoff_point = (
            "\n8. Debt payoff strategy: recommend the best strategy for paying off the debts listed above. Compare avalanche (highest interest rate first) vs snowball (smallest balance first) and pick one for this household, naming the specific debt to attack first and why. Based on the average monthly net income above, state how much extra per month they could realistically put toward debt beyond the minimum payments, and give a rough payoff timeline at that pace — make the payoff date feel concrete and reachable. If any debt's interest rate is low enough that paying it off early isn't worth prioritizing over saving, say so."
            if has_debts
            else ""
        )

        if in_progress_month:
            period_text = "the last few complete months plus the current month to date"
            current_month_point = f"""
Today is {today.strftime("%A, %B %-d, %Y")}. {in_progress_month['month']} is still in progress ({in_progress_month['progress']['fraction']:.0%} of the month elapsed), so treat it differently from the complete months:
- Don't compare its raw totals to full months or count it in monthly averages; judge it by pace instead (month-to-date spending vs. how much of the month has passed, and vs. the complete months).
- The straight-line projection is rough: large fixed bills (rent, mortgage, insurance, subscriptions) usually land early in the month, and income may not have arrived yet, so an early-month projection can overstate spending and understate income. Use the complete months to judge which bills are still to come before calling anything off-pace.
- Include a short "This month so far" section right after the wins: where they're on pace, where they're running hot (especially against targets), and concretely how much room is left for the rest of the month in the categories that matter. Scale this to how far along the month is — early on, keep it to pacing signals; near the end, treat it as nearly final.
"""
        else:
            period_text = "the months below"
            current_month_point = ""

        prompt = f"""You are a supportive personal finance coach reviewing a household's budget for {period_text}. This household is actively working to improve their financial position — they chose to track their money and ask for this review. Your job is to keep them motivated and moving forward, not to make them feel bad about their spending.

Budget Data:
{summary_text}{targets_text}{net_worth_text}{current_month_point}
Please provide a thorough budget analysis covering:
1. Wins first: open by naming 2-3 specific things this household is doing well — positive net months, a category that came in under target, spending that dropped month over month, debt that shrank, savings or net worth that grew. Use real numbers from the data. If the picture is rough overall, find the genuine bright spots (even "you're tracking every dollar now" counts) rather than inventing praise.
2. Overall spending trends and whether the household is living within its means — frame this as where they stand today and what's within reach, not as a verdict
3. Notable patterns or changes across the complete months, calling out improvements as well as slippage
4. Categories with the biggest opportunity to free up money{" — compare actual spending against the household's budget targets and note where they're on track as well as where they went over" if targets else ""}. Use the sub-category breakdowns and the largest individual expenses to say whether a high category is a one-off purchase or a recurring pattern, naming the specific expense when it's a one-off. A one-off big purchase is not a failure — say so when that's what the data shows
5. Specific, actionable recommendations to improve the budget. Lead with the one or two changes that would move the needle most, quantify the payoff ("this frees up roughly $X/month"), and keep each step small enough to actually start this month
6. Recommended budget targets: propose a specific monthly dollar amount for each major expense category that does not already have a target, based on the actual spending above{", and flag any existing targets that look too loose or too tight" if targets else ""}. Present each as "Category: $X/month — short reasoning". Set targets that are realistic stretches from current spending, not punishing cuts. Use the exact category names from the spending data so the household can copy them into their budget tool.{balance_sheet_point}{debt_payoff_point}

Close with a short, genuinely encouraging note on the momentum they'd build if they act on one or two of these recommendations.

Tone: warm, encouraging, and on their side — like a coach who believes they'll get there. Be honest: never hide a real problem, soften a number, or imply things are fine when they aren't. But state problems as solvable challenges with a next step attached, and never scold, shame, moralize, or use judgmental language about their choices.
Be concise: the whole analysis must fit in roughly 800 words. Use short bullet points, not tables. Cover only the categories that matter most."""

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return response.content[0].text, total_count
