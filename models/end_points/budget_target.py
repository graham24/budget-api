from pydantic import BaseModel


class BudgetTargetsRequest(BaseModel):
    household_id: int


class BudgetTargetSaveRequest(BaseModel):
    household_id: int
    category: str
    monthly_limit: float
