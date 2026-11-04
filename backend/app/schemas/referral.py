"""Pydantic schemas for referral validation."""

from pydantic import BaseModel, Field


class ReferralValidateRequest(BaseModel):
    """Payload to validate a referral code."""

    referral_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The referral code to validate.",
        examples=["REFABC123"],
    )


class ReferralValidateResponse(BaseModel):
    """Validation response containing referrer details."""

    is_valid: bool = Field(default=True, description="Whether the referral code is valid.")
    referral_code: str = Field(..., description="The validated uppercase referral code.")
    referrer_name: str = Field(..., description="Full name of the referrer.")
    message: str = Field(default="Valid referral code.", description="Human-readable validation message.")
