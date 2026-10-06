import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class NetWorthItemsRequest(BaseModel):
    household_id: int


class NetWorthItemCreateRequest(BaseModel):
    household_id: int
    account_id: Optional[int] = None
    name: str
    kind: Literal["asset", "debt"]
    type: str
    interest_rate: Optional[float] = None
    minimum_payment: Optional[float] = None
    initial_balance: Optional[float] = None
    balance_date: Optional[datetime.datetime] = None


class NetWorthItemUpdateRequest(BaseModel):
    name: Optional[str] = None
    account_id: Optional[int] = None
    type: Optional[str] = None
    interest_rate: Optional[float] = None
    minimum_payment: Optional[float] = None


class BalanceEntryCreateRequest(BaseModel):
    balance: float
    effective_date: Optional[datetime.datetime] = None


class NetWorthSummaryRequest(BaseModel):
    household_id: int
    months: int = 12
