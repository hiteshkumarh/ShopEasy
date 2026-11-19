"""Pydantic schemas for Admin Financial Settings API (WP-11 Step 4 / AD-06).

Defines request/response contracts for querying and updating versioned,
effective-dated financial settings without exposing internal secrets or sensitive fields.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Programme


class FinancialSettingResponse(BaseModel):
    """Pydantic representation of a single FinancialSetting."""

    id: int
    programme: Programme
    setting_key: str
    setting_value: Decimal
    currency: str
    description: Optional[str] = None
    version: int
    effective_from: datetime
    effective_to: Optional[datetime] = None
    is_active: bool
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FinancialSettingListResponse(BaseModel):
    """Paginated list of financial settings."""

    total: int
    items: List[FinancialSettingResponse]

    model_config = ConfigDict(from_attributes=True)


class FinancialSettingUpdateRequest(BaseModel):
    """Payload for creating or updating a financial setting prospectively."""

    programme: Programme
    setting_key: str = Field(..., min_length=1, max_length=64)
    setting_value: Decimal = Field(..., ge=Decimal("0.000000"))
    currency: str = Field("INR", min_length=3, max_length=3)
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    description: Optional[str] = Field(None, max_length=255)
    change_reason: str = Field(..., min_length=1, max_length=255)

    @field_validator("setting_key")
    @classmethod
    def validate_setting_key_not_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("setting_key cannot be empty or whitespace.")
        return s

    @field_validator("change_reason")
    @classmethod
    def validate_change_reason_not_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("change_reason cannot be empty or whitespace.")
        return s

