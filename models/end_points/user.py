from typing import Optional

from pydantic import BaseModel, EmailStr


class UsersRequest(BaseModel):
    house_hold_id: int


class UserUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
