import datetime
from typing import Dict, List, Optional

from models.db import DBModel, utcnow
from pydantic import BaseModel
from sqlmodel import Field


class BalanceEntry(DBModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="networthitem.id")
    balance: float  # always positive, for both assets and debts
    effective_date: datetime.datetime = Field(default_factory=utcnow)
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)


class BalanceEntries(BaseModel):
    entries: List[BalanceEntry]

    @classmethod
    def load_by_item_id(cls, item_id: int):
        entries = BalanceEntry.load_by_filter(
            BalanceEntry.item_id == item_id, limit=None
        )
        return cls(entries=entries)

    @classmethod
    def load_by_item_ids(cls, item_ids: List[int]):
        if not item_ids:
            return cls(entries=[])
        entries = BalanceEntry.load_by_filter(
            column=BalanceEntry.item_id, values=item_ids, limit=None
        )
        return cls(entries=entries)

    @staticmethod
    def latest_per_item(
        entries: List[BalanceEntry],
    ) -> Dict[int, BalanceEntry]:
        latest: Dict[int, BalanceEntry] = {}
        for entry in entries:
            current = latest.get(entry.item_id)
            if not current or (entry.effective_date, entry.id) > (
                current.effective_date,
                current.id,
            ):
                latest[entry.item_id] = entry
        return latest
