import datetime
from typing import Dict, List, Optional

from models.balance_entry import BalanceEntries, BalanceEntry
from models.db import DBModel, utcnow
from pydantic import BaseModel
from sqlmodel import Field, UniqueConstraint


class NetWorthItem(DBModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "name",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    account_id: Optional[int] = Field(default=None, foreign_key="account.id")
    name: str
    kind: str  # "asset" or "debt"
    type: str  # e.g. "Real Estate", "Vehicle" / "Mortgage", "Credit Card"
    interest_rate: Optional[float] = None
    minimum_payment: Optional[float] = None
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)


class NetWorthItems(BaseModel):
    items: List[NetWorthItem]

    @classmethod
    def load_by_household_id(cls, household_id: int):
        items = NetWorthItem.load_by_filter(
            NetWorthItem.household_id == household_id, limit=None
        )
        return cls(items=items)

    @classmethod
    def modified_since(cls, household_id: int, since: datetime.datetime) -> bool:
        """True if any item or balance entry changed after the given time."""
        items = cls.load_by_household_id(household_id).items
        if any(i.modified and i.modified > since for i in items):
            return True
        entries = BalanceEntries.load_by_item_ids(
            [i.id for i in items]
        ).entries
        return any(e.modified and e.modified > since for e in entries)

    @classmethod
    def net_worth_series(cls, household_id: int, months: int = 12):
        """Monthly assets/debts/net-worth series ending with the current
        month. Each item's balance is carried forward from its latest entry
        on or before each month-end; items with no entry yet contribute 0."""
        items = cls.load_by_household_id(household_id).items
        entries_by_item = cls._entries_by_item(items)

        now = utcnow()
        series = []
        for offset in range(months - 1, -1, -1):
            year = now.year + (now.month - 1 - offset) // 12
            month = (now.month - 1 - offset) % 12 + 1
            if offset == 0:
                as_of = now
            else:
                # End of the month: first day of the next month minus a tick
                next_year = year + month // 12
                next_month = month % 12 + 1
                as_of = datetime.datetime(
                    next_year, next_month, 1
                ) - datetime.timedelta(microseconds=1)
            assets, debts = cls._totals_as_of(items, entries_by_item, as_of)
            series.append(
                {
                    "month": f"{year}-{month:02d}",
                    "assets": assets,
                    "debts": debts,
                    "net_worth": assets - debts,
                }
            )
        return series

    @classmethod
    def totals(cls, household_id: int):
        """Current (total_assets, total_debts) from each item's latest entry."""
        items = cls.load_by_household_id(household_id).items
        entries_by_item = cls._entries_by_item(items)
        return cls._totals_as_of(items, entries_by_item, utcnow())

    @staticmethod
    def _entries_by_item(
        items: List[NetWorthItem],
    ) -> Dict[int, List[BalanceEntry]]:
        """All entries for the given items, sorted ascending per item."""
        if not items:
            return {}
        entries = BalanceEntries.load_by_item_ids(
            [item.id for item in items]
        ).entries
        by_item: Dict[int, List[BalanceEntry]] = {}
        for entry in sorted(
            entries, key=lambda e: (e.effective_date, e.id)
        ):
            by_item.setdefault(entry.item_id, []).append(entry)
        return by_item

    @staticmethod
    def _totals_as_of(items, entries_by_item, as_of):
        assets = 0.0
        debts = 0.0
        for item in items:
            balance = 0.0
            for entry in entries_by_item.get(item.id, []):
                if entry.effective_date > as_of:
                    break
                balance = entry.balance
            if item.kind == "asset":
                assets += balance
            else:
                debts += balance
        return assets, debts
