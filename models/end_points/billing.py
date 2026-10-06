from pydantic import BaseModel


class BillingCheckoutSessionRequest(BaseModel):
    household_id: int


class BillingPortalSessionRequest(BaseModel):
    household_id: int
