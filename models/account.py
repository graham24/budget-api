import datetime
from typing import List, Optional

from models.db import DBModel, utcnow
from models.household import HouseholdUsers
from pydantic import BaseModel
from sqlmodel import Field


class Account(DBModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    description: str
    type: str
    bank: str
    user_id: int = Field(foreign_key="user.id")
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)


class Accounts(BaseModel):
    accounts: List[Account]

    @classmethod
    def load_by_user_id(cls, user_id: int):
        accounts = Account.load_by_filter(
            Account.user_id == user_id, limit=None
        )
        return cls(accounts=accounts)

    @classmethod
    def load_by_household_id(cls, household_id: int):
        household_users = HouseholdUsers.load_by_household_id(household_id)
        accounts = Account.load_by_filter(
            column=Account.user_id,
            values=[hu.user_id for hu in household_users.household_users],
            limit=None,
        )
        return cls(accounts=accounts)
