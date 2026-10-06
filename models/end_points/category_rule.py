from pydantic import BaseModel


class CategoryRulesRequest(BaseModel):
    household_id: int


class CategoryRuleCreateRequest(BaseModel):
    household_id: int
    match_text: str
    category: str
    sub_category: str
    need: bool = False
    income: bool = False
