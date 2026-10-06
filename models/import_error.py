import datetime
from typing import List, Optional

from models.db import DBModel, utcnow
from pydantic import BaseModel
from sqlmodel import Field


class ImportErrorLog(DBModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    message: str
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)


class ImportErrorLogs(BaseModel):
    errors: List[ImportErrorLog]

    @classmethod
    def load_by_household_id(cls, household_id: int, limit: int = 50):
        errors = ImportErrorLog.load_by_filter(
            ImportErrorLog.household_id == household_id, limit=limit
        )
        return cls(errors=errors)
