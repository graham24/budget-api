import datetime
from typing import List, Optional

from models.account import Account
from models.db import DBModel, utcnow
from sqlmodel import Field, UniqueConstraint


class SimpleFinAccount(DBModel, table=True):
    __table_args__ = (UniqueConstraint("simplefin_account_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    simplefin_account_id: str
    bank_account_id: Optional[int] = Field(foreign_key="account.id", default=None)
    last_fetched: Optional[datetime.datetime]
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)

class SimpleFinAccounts(DBModel):
    accounts: List[SimpleFinAccount]

    @classmethod
    def load_by_simplefin_account_ids(cls, simplefin_account_ids: List[str]):
        accounts = SimpleFinAccount.load_by_filter(
            column=SimpleFinAccount.simplefin_account_id,
            values=simplefin_account_ids,
            limit=None,
        )
        return cls(accounts=accounts)