from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import UserRole

# Regular expressions for validation
PHONE_REGEX = r"^\d{10}$"
OTP_REGEX = r"^\d{6}$"


# ---------------------------------------------------------------------------
# Customer Authentication Schemas
# ---------------------------------------------------------------------------

class CustomerRegisterRequest(BaseModel):
    """Payload for customer account registration."""
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Full legal name of the customer",
    )
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit mobile number",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Full name cannot be empty or whitespace only.")
        return clean


class CustomerRegisterResponse(BaseModel):
    """Response returned upon successful customer registration."""
    id: int
    full_name: str
    phone: str
    role: UserRole = UserRole.CUSTOMER
    referral_code: str
    is_active: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerOTPRequest(BaseModel):
    """Payload to request a single-use login OTP for customer."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit customer mobile number",
    )

    model_config = ConfigDict(extra="forbid")


class CustomerOTPVerifyRequest(BaseModel):
    """Payload to verify customer login OTP."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit customer mobile number",
    )
    otp_code: str = Field(
        ...,
        pattern=OTP_REGEX,
        description="6-digit one-time password",
    )

    model_config = ConfigDict(extra="forbid")


class CustomerPasswordLoginRequest(BaseModel):
    """Payload for customer login using phone and password."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit customer mobile number",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Customer account password",
    )

    model_config = ConfigDict(extra="forbid")


class CustomerPasswordResetRequest(BaseModel):
    """Payload to request an OTP for customer password reset."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit customer mobile number",
    )

    model_config = ConfigDict(extra="forbid")


class CustomerPasswordResetConfirmRequest(BaseModel):
    """Payload to confirm password reset using verified OTP."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit customer mobile number",
    )
    otp_code: str = Field(
        ...,
        pattern=OTP_REGEX,
        description="6-digit verification code",
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (minimum 8 characters)",
    )

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Administrator Authentication Schemas
# ---------------------------------------------------------------------------

class AdminOTPRequest(BaseModel):
    """Payload to request an OTP for administrator login."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit authorized administrator mobile number",
    )

    model_config = ConfigDict(extra="forbid")


class AdminOTPVerifyRequest(BaseModel):
    """Payload to verify administrator login OTP."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit authorized administrator mobile number",
    )
    otp_code: str = Field(
        ...,
        pattern=OTP_REGEX,
        description="6-digit administrator OTP",
    )

    model_config = ConfigDict(extra="forbid")


class AdminPasswordLoginRequest(BaseModel):
    """Payload for administrator password login triggering mandatory MFA."""
    phone: str = Field(
        ...,
        pattern=PHONE_REGEX,
        description="10-digit authorized administrator mobile number",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Administrator account password",
    )

    model_config = ConfigDict(extra="forbid")


class AdminMFAVerifyRequest(BaseModel):
    """Payload to complete administrator MFA verification."""
    mfa_token: str = Field(
        ...,
        min_length=10,
        description="Ephemeral MFA challenge token received during password login",
    )
    otp_code: str = Field(
        ...,
        pattern=OTP_REGEX,
        description="6-digit second-factor MFA OTP",
    )

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Authentication Responses
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    """JWT bearer token response returned upon successful authentication."""
    access_token: str
    token_type: str = "bearer"
    role: UserRole

    model_config = ConfigDict(from_attributes=True)


class MFARequiredResponse(BaseModel):
    """Intermediate response returned when administrator password login requires MFA."""
    mfa_token: str
    token_type: str = "mfa"
    expires_in: int = 300
    mfa_required: bool = True

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Identity Schemas
# ---------------------------------------------------------------------------

class AuthUserResponse(BaseModel):
    """Current authenticated user profile."""
    id: int
    full_name: str
    phone: str
    role: UserRole
    referral_code: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

