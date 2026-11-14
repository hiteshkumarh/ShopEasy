"""Pydantic schemas for referral validation."""

from typing import Optional
from pydantic import BaseModel, Field

from app.models.enums import Programme


class ReferralValidateRequest(BaseModel):
    """Payload to validate a referral code."""

    referral_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The referral code to validate.",
        examples=["REFABC123"],
    )
    programme: Optional[Programme] = Field(
        None,
        description="Optional programme context for validation.",
    )


class ReferralValidateResponse(BaseModel):
    """Validation response containing referrer details."""

    is_valid: bool = Field(default=True, description="Whether the referral code is valid.")
    referral_code: str = Field(..., description="The validated uppercase referral code.")
    referrer_name: str = Field(..., description="Full name of the referrer.")
    referrer_programme: Optional[Programme] = Field(None, description="Programme of the referrer.")
    message: str = Field(default="Valid referral code.", description="Human-readable validation message.")
