from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductResponse(BaseModel):
    """Public and admin product presentation schema."""

    id: int
    name: str
    description: Optional[str] = None
    price: Decimal
    stock: int
    image_url: Optional[str] = None
    is_active: bool
    is_power_bank: bool
    product_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    """Paginated list of product records."""

    items: List[ProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

    model_config = ConfigDict(from_attributes=True)


class ProductCreateRequest(BaseModel):
    """Payload for creating a new product catalog item."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Product title / name",
    )
    description: Optional[str] = Field(
        None,
        description="Detailed product description",
    )
    price: Decimal = Field(
        ...,
        gt=0,
        max_digits=10,
        decimal_places=2,
        description="Product unit price in INR (must be positive)",
    )
    stock: int = Field(
        0,
        ge=0,
        description="Available inventory quantity (must not be negative)",
    )
    image_url: Optional[str] = Field(
        None,
        max_length=500,
        description="URL or relative path to product image asset",
    )
    product_code: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique programmatic product SKU / code",
    )
    is_active: bool = Field(
        True,
        description="Whether product is active and visible to public catalog",
    )
    is_power_bank: Optional[bool] = Field(
        None,
        description="Whether product qualifies as Power Bank for commission calculations",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Product name cannot be empty or whitespace only.")
        return clean

    @field_validator("product_code")
    @classmethod
    def validate_product_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                return None
            return clean
        return None


class ProductUpdateRequest(BaseModel):
    """Payload for updating an existing product catalog item."""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Product title / name",
    )
    description: Optional[str] = Field(
        None,
        description="Detailed product description",
    )
    price: Optional[Decimal] = Field(
        None,
        gt=0,
        max_digits=10,
        decimal_places=2,
        description="Product unit price in INR (must be positive)",
    )
    stock: Optional[int] = Field(
        None,
        ge=0,
        description="Available inventory quantity (must not be negative)",
    )
    image_url: Optional[str] = Field(
        None,
        max_length=500,
        description="URL or relative path to product image asset",
    )
    product_code: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique programmatic product SKU / code",
    )
    is_active: Optional[bool] = Field(
        None,
        description="Whether product is active and visible to public catalog",
    )
    is_power_bank: Optional[bool] = Field(
        None,
        description="Whether product qualifies as Power Bank for commission calculations",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Product name cannot be empty or whitespace only.")
            return clean
        return None

    @field_validator("product_code")
    @classmethod
    def validate_product_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                return None
            return clean
        return None

