from pydantic import BaseModel, EmailStr


class EmailLoginRequest(BaseModel):
    email: EmailStr
