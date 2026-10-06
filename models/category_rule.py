import datetime
from typing import List, Optional

from models.db import DBModel, utcnow
from pydantic import BaseModel
from sqlmodel import Field, UniqueConstraint


class CategoryRule(DBModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "match_text",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    match_text: str
    category: str
    sub_category: str
    need: bool = False
    # Whether matching transactions are income (e.g. a PAYROLL rule) or
    # spending — a positive match on a non-income rule is a refund.
    income: bool = False
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)

    def matches(self, description: str) -> bool:
        return self.match_text.lower() in description.lower()


class CategoryRules(BaseModel):
    rules: List[CategoryRule]

    @classmethod
    def load_by_household_id(cls, household_id: int):
        rules = CategoryRule.load_by_filter(
            CategoryRule.household_id == household_id, limit=None
        )
        return cls(rules=rules)

    def find_matching(self, description: str) -> Optional[CategoryRule]:
        """Return the first rule whose match_text appears in the description (newest rule wins)."""
        for rule in self.rules:
            if rule.matches(description):
                return rule
        return None
