"""Pydantic models for UC3 — Fraud Detection."""

from pydantic import BaseModel, Field
from typing import Optional, Any


class SimulateRequest(BaseModel):
    scenario: str = Field(
        ...,
        description="One of: signal_1, signal_2, signal_3, signal_4, clean",
    )
    user_id: Optional[str] = Field(None, alias="userId")

    class Config:
        populate_by_name = True


class SignalRuleUpdate(BaseModel):
    """Flexible update for any signal rule threshold field."""
    updates: dict[str, Any] = Field(
        ...,
        description="Key-value pairs mapping field names to new values",
    )
