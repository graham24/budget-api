"""Completely delete a household and everything scoped to it (for wiping test accounts).

Deletes, in FK-safe order: transactions, linked SimpleFin account rows,
balance entries, net worth items, import error logs, budget analyses,
budget targets, category rules, accounts, household-user links, the
household itself, and finally any user left with no remaining household
membership (so a user shared across households, however unlikely, is kept).

Usage:
    python scripts/delete_household.py <household_id>            # dry run, shows what would be deleted
    python scripts/delete_household.py <household_id> --yes       # actually delete

Run from the repo root with the venv active (needs the same .env as the app).
"""

import sys

sys.path.insert(0, ".")

from models.account import Account
from models.balance_entry import BalanceEntry
from models.budget_analysis import BudgetAnalysis
from models.budget_target import BudgetTarget
from models.category_rule import CategoryRule
from models.household import Household, HouseholdUser
from models.import_error import ImportErrorLog
from models.net_worth_item import NetWorthItem
from models.simplefin import SimpleFinAccount
from models.transaction import Transaction
from models.user import User


def delete_household(household_id: int, dry_run: bool = True):
    household = Household.load(household_id)
    if not household:
        print(f"No household with id {household_id}")
        return

    household_users = HouseholdUser.load_by_filter(
        HouseholdUser.house_hold_id == household_id, limit=None
    )
    user_ids = [hu.user_id for hu in household_users]

    accounts = (
        Account.load_by_filter(column=Account.user_id, values=user_ids, limit=None)
        if user_ids
        else []
    )
    account_ids = [a.id for a in accounts]

    transactions = (
        Transaction.load_by_filter(
            column=Transaction.account_id, values=account_ids, limit=None
        )
        if account_ids
        else []
    )
    simplefin_accounts = (
        SimpleFinAccount.load_by_filter(
            column=SimpleFinAccount.bank_account_id, values=account_ids, limit=None
        )
        if account_ids
        else []
    )
    net_worth_items = NetWorthItem.load_by_filter(
        NetWorthItem.household_id == household_id, limit=None
    )
    net_worth_item_ids = [i.id for i in net_worth_items]
    balance_entries = (
        BalanceEntry.load_by_filter(
            column=BalanceEntry.item_id, values=net_worth_item_ids, limit=None
        )
        if net_worth_item_ids
        else []
    )
    import_errors = ImportErrorLog.load_by_filter(
        ImportErrorLog.household_id == household_id, limit=None
    )
    budget_analyses = BudgetAnalysis.load_by_filter(
        BudgetAnalysis.household_id == household_id, limit=None
    )
    budget_targets = BudgetTarget.load_by_filter(
        BudgetTarget.household_id == household_id, limit=None
    )
    category_rules = CategoryRule.load_by_filter(
        CategoryRule.household_id == household_id, limit=None
    )

    print(f"Household {household_id} ({household.name!r}):")
    print(f"  {len(household_users)} household-user link(s), user_ids={user_ids}")
    print(f"  {len(accounts)} account(s)")
    print(f"  {len(transactions)} transaction(s)")
    print(f"  {len(simplefin_accounts)} linked SimpleFin account row(s)")
    print(f"  {len(net_worth_items)} net worth item(s)")
    print(f"  {len(balance_entries)} balance entr(y/ies)")
    print(f"  {len(import_errors)} import error(s)")
    print(f"  {len(budget_analyses)} budget analys(is/es)")
    print(f"  {len(budget_targets)} budget target(s)")
    print(f"  {len(category_rules)} category rule(s)")

    if dry_run:
        print("\nDry run — nothing deleted. Re-run with --yes to actually delete.")
        return

    for t in transactions:
        t.delete()
    for s in simplefin_accounts:
        s.delete()
    for e in balance_entries:
        e.delete()
    for i in net_worth_items:
        i.delete()
    for e in import_errors:
        e.delete()
    for a in budget_analyses:
        a.delete()
    for t in budget_targets:
        t.delete()
    for r in category_rules:
        r.delete()
    for a in accounts:
        a.delete()
    for hu in household_users:
        hu.delete()

    household.delete()

    # Only remove users left with no remaining household membership at all
    # (in case a user is somehow shared across households).
    for user_id in user_ids:
        remaining = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == user_id, limit=1
        )
        if not remaining:
            user = User.load(user_id)
            if user:
                user.delete()
                print(f"  deleted user {user_id} ({user.email})")

    print(f"\nDeleted household {household_id} and all associated data.")


if __name__ == "__main__":
    if len(sys.argv) == 2:

        household_id = int(sys.argv[1])
        confirm = "--yes" in sys.argv[2:]
    else:
        household_id = input("Household ID: ")
        confirm_input = input("Dry Run: ")
        confirm = confirm_input == 'no'

    if confirm:
        answer = input(
            f"This will PERMANENTLY delete household {household_id} and all its data. Type 'delete' to confirm: "
        )
        if answer.strip().lower() != "delete":
            print("Aborted.")
            sys.exit(1)

    delete_household(household_id, dry_run=not confirm)
