from typing import Annotated, Optional

from pydantic import BaseModel, StringConstraints

# Free text: the institution name. It's the SimpleFin connection key together
# with user_id (see Importer.import_household_from_simplefin), so it should
# name the real bank. CSV upload only works when it matches an importer key in
# Importer.get_transaction_classes(); any other name is SimpleFin-only.
Bank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AccountsRequest(BaseModel):
    user_id: int


class AccountCreateRequest(BaseModel):
    description: str
    type: str
    bank: Bank
    user_id: int


class AccountUpdateRequest(BaseModel):
    description: Optional[str] = None
    type: Optional[str] = None
    bank: Optional[Bank] = None
    user_id: Optional[int] = None
