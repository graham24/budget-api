import datetime
from typing import List, Optional

from models.db import DBModel, utcnow
from pydantic import BaseModel, EmailStr
from sqlmodel import Field, UniqueConstraint


class User(DBModel, table=True):
    __table_args__ = (UniqueConstraint("email"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    first_name: str
    last_name: str
    email: EmailStr
    google_sub: Optional[str] = Field(default=None)
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)

    @classmethod
    def load_by_email(cls, email):
        users = cls.load_by_filter(cls.email == email, limit=1)
        if users:
            return users[0]
        return None

    @classmethod
    def load_by_google_sub(cls, google_sub):
        users = cls.load_by_filter(cls.google_sub == google_sub, limit=1)
        if users:
            return users[0]
        return None


class Users(BaseModel):
    users: List[User]

    @classmethod
    def load_all(cls):
        users = User.load_by_filter()
        return cls(users=users)
