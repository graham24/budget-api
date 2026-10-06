from typing import Optional

from pydantic import BaseModel, EmailStr


class HouseholdRequest(BaseModel):
    user_id: int


class HouseholdUpdateRequest(BaseModel):
    name: str


class HouseholdMemberAddRequest(BaseModel):
    email: EmailStr


class HouseholdSecretsRequest(BaseModel):
    anthropic_api_key: Optional[str] = None
    simplefin_access_url: Optional[str] = None


class HouseholdSimplefinClaimRequest(BaseModel):
    setup_token: str
