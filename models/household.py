import datetime
from typing import List, Optional

from models.db import DBModel, EncryptedString, utcnow
from models.user import User
from pydantic import BaseModel
from sqlalchemy import Column
from sqlmodel import Field, UniqueConstraint


class Household(DBModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "name",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    anthropic_api_key: Optional[str] = Field(default=None, sa_column=Column(EncryptedString))
    simplefin_access_url: Optional[str] = Field(default=None, sa_column=Column(EncryptedString))
    stripe_customer_id: Optional[str] = Field(default=None)
    stripe_subscription_id: Optional[str] = Field(default=None)
    # Mirrors the Stripe subscription's own `status` field verbatim
    # (active, trialing, past_due, canceled, incomplete, ...), kept in sync
    # by the billing webhook. None = never subscribed.
    subscription_status: Optional[str] = Field(default=None)
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)

    @classmethod
    def load_by_name(cls, name):
        return cls.load_by_filter(cls.name == name, limit=1)[0]

    @classmethod
    def load_by_account_id(cls, account_id: int):
        from models.account import Account

        account = Account.load(account_id)
        if not account:
            return None
        household_users = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == account.user_id
        )
        if not household_users:
            return None
        return cls.load(household_users[0].house_hold_id)

    def add_user(self, user: User):
        household_user = HouseholdUser(
            house_hold_id=self.id,
            user_id=user.id,
        ).create()
        return household_user

    def get_anthropic_key(self):
        return self.anthropic_api_key

    def get_simplefin_url(self):
        return self.simplefin_access_url


class Households(BaseModel):
    households: List[Household]

    @classmethod
    def load_all(cls):
        households = Household.load_by_filter()
        return cls(households=households)


class HouseholdUser(DBModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "house_hold_id",
            "user_id",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    house_hold_id: int = Field(foreign_key="household.id")
    user_id: int = Field(foreign_key="user.id")
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)


class HouseholdUsers(BaseModel):
    household_users: List[HouseholdUser]

    @classmethod
    def load_by_household_id(cls, household_id: int):
        users = HouseholdUser.load_by_filter(
            HouseholdUser.house_hold_id == household_id
        )
        return cls(household_users=users)

    @classmethod
    def load_all(cls):
        household_users = HouseholdUser.load_by_filter()
        return cls(household_users=household_users)
