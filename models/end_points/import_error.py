from pydantic import BaseModel


class ImportErrorsRequest(BaseModel):
    household_id: int
