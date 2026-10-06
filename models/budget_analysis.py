import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy import Column, Text
from sqlmodel import Field

from models.db import DBModel, utcnow


class BudgetAnalysis(DBModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    analysis: str = Field(sa_column=Column(Text))
    from_date: datetime.datetime
    to_date: datetime.datetime
    transaction_count: int
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)

    @classmethod
    def find_matching(
        cls,
        household_id: int,
        from_date: datetime.datetime,
        to_date: datetime.datetime,
        transaction_count: int,
    ):
        """Return an existing analysis that covers the same date range and transaction count, or None."""
        results = cls.load_by_filter(
            cls.household_id == household_id,
            cls.from_date == from_date,
            cls.to_date == to_date,
            cls.transaction_count == transaction_count,
            limit=1,
        )
        return results[0] if results else None


class BudgetAnalyses(BaseModel):
    analyses: List[BudgetAnalysis]

    @classmethod
    def load_latest_by_household(cls, household_id: int):
        analyses = BudgetAnalysis.load_by_filter(
            BudgetAnalysis.household_id == household_id,
            limit=1,
        )
        return cls(analyses=analyses)
