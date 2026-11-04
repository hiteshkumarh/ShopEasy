from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CartItemAddRequest(BaseModel):
    """Payload to add an item to the persistent shopping cart."""

    product_id: int = Field(
        ...,
        gt=0,
        description="Database ID of the product to add",
    )
    quantity: int = Field(
        1,
        gt=0,
        description="Number of units to add (must be positive)",
    )


class CartItemUpdateRequest(BaseModel):
    """Payload to update the quantity of an existing cart item."""

    quantity: int = Field(
        ...,
        gt=0,
        description="Updated quantity of units (must be positive)",
    )


class CartItemResponse(BaseModel):
    """Presentation model for an item in the shopping cart."""

    id: int
    product_id: int
    product_name: str
    product_code: Optional[str] = None
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    stock: int
    is_active: bool
    is_power_bank: bool
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel):
    """Presentation model for the customer's full shopping cart."""

    items: List[CartItemResponse]
    total_items: int
    subtotal: Decimal

    model_config = ConfigDict(from_attributes=True)

