from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class CheckUserRequest(BaseModel):
    name: str
    dob: Optional[str] = None
    max_edits: int = Field(2, ge=0, le=2)
    limit: int = Field(10, ge=1, le=100)


class BatchSweepRequest(BaseModel):
    limit: int = Field(0, description="0 = all sanctioned entries")


class SanctionedEntry(BaseModel):
    full_name: str = Field(..., alias="fullName")
    aliases: list[str] = []
    date_of_birth: Optional[datetime] = Field(None, alias="dateOfBirth")
    country: Optional[str] = None
    source: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = Field(True, alias="isActive")

    class Config:
        populate_by_name = True


class UserProfile(BaseModel):
    user_id: str = Field(..., alias="userId")
    full_name: str = Field(..., alias="fullName")
    date_of_birth: Optional[datetime] = Field(None, alias="dateOfBirth")
    phone: Optional[str] = None
    email: Optional[str] = None
    status: str = "active"

    class Config:
        populate_by_name = True
