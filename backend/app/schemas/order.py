from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AllocationScenario, OrderStatus, PaymentStatus
from app.schemas.address import AddressResponse


class CheckoutRequest(BaseModel):
    """Payload for submitting checkout and placing an order."""

    address_id: int = Field(
        ...,
        gt=0,
        description="ID of the delivery address selected by the customer",
    )
    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Client-generated unique token to prevent duplicate order placements",
    )
    referral_code: Optional[str] = Field(
        None,
        max_length=20,
        description="Optional referral code (valid only on customer's first successful order)",
    )


class OrderItemResponse(BaseModel):
    """Snapshot line item in a confirmed order."""

    id: int
    product_id: int
    product_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderAllocationResponse(BaseModel):
    """Immutable financial allocation snapshot recorded for an order."""

    id: int
    order_id: int
    scenario: AllocationScenario
    power_bank_quantity: int
    order_total_amount: Decimal
    product_import_cost: Decimal
    output_gst: Decimal
    packing_courier: Decimal
    gift_achievement: Decimal
    office_staff: Decimal
    direct_referral_reward: Decimal
    sequential_commission: Decimal
    total_allocated: Decimal
    remaining_amount: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    """Full order presentation schema including items and allocation."""

    id: int
    order_number: str
    idempotency_key: str
    user_id: int
    address_id: int
    total_amount: Decimal
    order_status: OrderStatus
    payment_status: PaymentStatus
    payment_reference: Optional[str] = None
    applied_referral_code: Optional[str] = None
    is_first_successful_order: bool
    created_at: datetime
    updated_at: datetime
    order_items: List[OrderItemResponse] = []
    order_allocation: Optional[OrderAllocationResponse] = None
    address: Optional[AddressResponse] = None

    model_config = ConfigDict(from_attributes=True)


class OrderListResponse(BaseModel):
    """List of orders for a customer."""

    items: List[OrderResponse]
    total: int

    model_config = ConfigDict(from_attributes=True)

