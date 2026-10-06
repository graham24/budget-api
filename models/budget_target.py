import datetime
from typing import List, Optional

from models.db import DBModel, utcnow
from pydantic import BaseModel
from sqlmodel import Field, UniqueConstraint


class BudgetTarget(DBModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "category",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    category: str
    monthly_limit: float
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)


class BudgetTargets(BaseModel):
    targets: List[BudgetTarget]

    @classmethod
    def load_by_household_id(cls, household_id: int):
        targets = BudgetTarget.load_by_filter(
            BudgetTarget.household_id == household_id, limit=None
        )
        return cls(targets=targets)

    @classmethod
    def modified_since(cls, household_id: int, since: datetime.datetime) -> bool:
        """True if any target was created or changed after the given time."""
        targets = cls.load_by_household_id(household_id).targets
        return any(t.modified and t.modified > since for t in targets)

    @classmethod
    def load_by_category(cls, household_id: int, category: str):
        targets = BudgetTarget.load_by_filter(
            BudgetTarget.household_id == household_id,
            BudgetTarget.category == category,
            limit=1,
        )
        return targets[0] if targets else None
