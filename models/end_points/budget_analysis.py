import datetime
from typing import Optional

from pydantic import BaseModel


class BudgetAnalysisRequest(BaseModel):
    user_id: Optional[int] = None  # GET (latest) only needs household_id
    household_id: int
    from_date: Optional[datetime.datetime] = None
    to_date: Optional[datetime.datetime] = None
    force: bool = False  # skip the cache and regenerate
