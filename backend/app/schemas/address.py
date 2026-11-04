from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AddressCreateRequest(BaseModel):
    """Payload for registering a customer delivery address."""

    recipient_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the package recipient",
    )
    phone: str = Field(
        ...,
        min_length=10,
        max_length=15,
        pattern=r"^\+?[0-9]{10,15}$",
        description="Contact phone number for delivery",
    )
    address_line1: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Primary street address / house / apartment number",
    )
    address_line2: Optional[str] = Field(
        None,
        max_length=255,
        description="Secondary address info (suite, landmark, etc.)",
    )
    city: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="City or town",
    )
    state: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="State or province",
    )
    pincode: str = Field(
        ...,
        min_length=4,
        max_length=10,
        pattern=r"^[0-9]{4,10}$",
        description="Postal / ZIP code",
    )
    is_default: bool = Field(
        False,
        description="Whether this is the customer's default delivery address",
    )


class AddressUpdateRequest(BaseModel):
    """Payload for updating an existing delivery address."""

    recipient_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Name of the package recipient",
    )
    phone: Optional[str] = Field(
        None,
        min_length=10,
        max_length=15,
        pattern=r"^\+?[0-9]{10,15}$",
        description="Contact phone number for delivery",
    )
    address_line1: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Primary street address / house / apartment number",
    )
    address_line2: Optional[str] = Field(
        None,
        max_length=255,
        description="Secondary address info",
    )
    city: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="City or town",
    )
    state: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="State or province",
    )
    pincode: Optional[str] = Field(
        None,
        min_length=4,
        max_length=10,
        pattern=r"^[0-9]{4,10}$",
        description="Postal / ZIP code",
    )
    is_default: Optional[bool] = Field(
        None,
        description="Whether this is the customer's default delivery address",
    )


class AddressResponse(BaseModel):
    """Customer delivery address response schema."""

    id: int
    user_id: int
    recipient_name: str
    phone: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    pincode: str
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

