import datetime
from typing import Optional

from pydantic import BaseModel


class TransactionsRequest(BaseModel):
    user_id: int
    household_id: int
    account_id: Optional[int] = None
    from_date: Optional[datetime.datetime] = None
    to_date: Optional[datetime.datetime] = None
    type: Optional[str] = None


class TransactionsSummaryRequest(BaseModel):
    user_id: int
    household_id: int


class TransactionSaveRequest(BaseModel):
    id: int
    category: str
    sub_category: str
    need: bool
    # Optional so a frontend that predates the flag doesn't clear it.
    income: Optional[bool] = None


class TransactionUploadRequest(BaseModel):
    accountId: int
    importFile: bytes


class ForceImportRequest(BaseModel):
    description: str
    date: datetime.datetime
    amount: float
    account_id: int
