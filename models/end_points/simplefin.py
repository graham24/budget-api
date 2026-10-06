from typing import Optional

from pydantic import BaseModel

from models.end_points.account import Bank


class SimplefinAccountsRequest(BaseModel):
    household_id: int


class SimplefinNewAccount(BaseModel):
    description: str
    type: str
    bank: Bank
    user_id: int


class SimplefinAccountLinkRequest(BaseModel):
    household_id: int
    bank_account_id: Optional[int] = None
    new_account: Optional[SimplefinNewAccount] = None

class SimplefinAccountRefreshRequest(BaseModel):
    household_id: int

class SimplefinImportRequest(BaseModel):
    household_id: int
