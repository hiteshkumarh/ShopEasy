"""Schemas for Plan A Cashback Progress API (WP-10)."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PlanACashbackCycleSummary(BaseModel):
    """Summary of a single cashback cycle for the customer."""
    model_config = ConfigDict(from_attributes=True)

    cycle_id: int
    cycle_number: int
    completed_contributions: int = Field(ge=0, le=16)
    total_earned: Decimal = Field(default=Decimal("0.00"), ge=0, le=Decimal("4000.00"))
    status: str  # "ACTIVE", "COMPLETED"
    is_completed: bool
    started_at: datetime
    completed_at: Optional[datetime] = None


class PlanACashbackContributionItem(BaseModel):
    """Customer-facing individual ₹250 cashback contribution record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    cycle_id: Optional[int] = None
    cycle_number: Optional[int] = None
    contributing_billing_id: int
    contributing_billing_number: str
    contributing_user_masked_phone: Optional[str] = None
    recipient_billing_number: Optional[str] = None
    recipient_reference: str
    amount: Decimal = Field(default=Decimal("250.00"))
    status: str
    idempotency_key: str
    created_at: datetime


class PlanACashbackProgressResponse(BaseModel):
    """Authenticated customer cashback progress response with 48-bulb visual tracking."""
    model_config = ConfigDict(from_attributes=True)

    has_active_cycle: bool
    current_billing_id: Optional[str] = Field(
        None, description="Billing number of the customer's active cashback cycle (e.g. AGD-000201)"
    )
    current_cycle_number: Optional[int] = Field(
        None, description="Sequential cycle number within the queue"
    )
    completed_contributions: int = Field(
        0, ge=0, le=16, description="Completed contributions out of 16"
    )
    total_contributions_required: int = Field(
        16, description="Total contributions required to complete a cycle"
    )
    cashback_amount_earned: Decimal = Field(
        Decimal("0.00"), ge=0, le=Decimal("4000.00"), description="Cashback amount accumulated towards ₹4,000"
    )
    target_cashback_amount: Decimal = Field(
        Decimal("4000.00"), description="Full target cashback amount"
    )
    cycle_status: str = Field(
        "NO_CYCLE", description="Status of the cycle: ACTIVE, COMPLETED, WAITING, or NO_CYCLE"
    )
    is_completed: bool = Field(
        False, description="Whether the current cycle has reached 16 contributions (₹4,000)"
    )

    # 48-bulb visual progress representation
    bulbs_on: int = Field(
        0, ge=0, le=48, description="Number of switched ON bulbs (completed_contributions * 3)"
    )
    bulbs_off: int = Field(
        48, ge=0, le=48, description="Number of remaining OFF bulbs (48 - bulbs_on)"
    )
    total_bulbs: int = Field(48, description="Fixed total bulbs")
    bulb_states: List[bool] = Field(
        default_factory=lambda: [False] * 48,
        description="Array of 48 boolean states representing individual bulb ON (True) / OFF (False) status",
    )

    # Withdrawal eligibility
    is_withdrawable: bool = Field(
        False,
        description="Whether full ₹4,000 cashback withdrawal can be requested (completed cycle + ₹4,000 balance)",
    )
    withdrawal_status: Optional[str] = Field(
        None,
        description="Status of any active or recent withdrawal request (e.g. REQUESTED, COMPLETED)",
    )
    current_wallet_balance: Decimal = Field(
        Decimal("0.00"), description="Current balance in Sequential Commission / Cashback wallet"
    )

    # Active Cycle Earnings & Pending Visibility
    active_cycle_earnings: Decimal = Field(
        Decimal("0.00"), description="Total earnings accumulated in active cycle pending completion"
    )
    active_contributions: List[PlanACashbackContributionItem] = Field(
        default_factory=list, description="Contributions for the active cashback cycle"
    )



