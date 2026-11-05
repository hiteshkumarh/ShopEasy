from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class SequentialProgress(BaseModel):
    """16-circle visual component state and cycle progress."""

    status: str = Field(
        ...,
        description="Status state: 'active', 'waiting', 'completed', or 'not_enrolled'",
    )
    queue_position: Optional[int] = Field(
        default=None,
        description="Customer's position in the global FIFO beneficiary queue",
    )
    completed_commissions: int = Field(
        default=0,
        ge=0,
        le=16,
        description="Count of ₹250 commissions received (0 through 16)",
    )
    total_earned: Decimal = Field(
        default=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
        description="Total amount earned in current/completed cycle",
    )
    target_commissions: int = Field(default=16, description="Total commissions per cycle (16)")
    target_amount: Decimal = Field(
        default=Decimal("4000.00"),
        max_digits=10,
        decimal_places=2,
        description="Total cycle completion target (₹4,000.00)",
    )
    circle_states: List[bool] = Field(
        ...,
        description="16 boolean states representing filled (True) or unfilled (False) circle slots",
    )


class WithdrawalEligibility(BaseModel):
    """Withdrawal eligibility gates for both wallets."""

    direct_referral_eligible: bool = Field(
        ..., description="True if Direct Referral balance >= ₹750.00"
    )
    direct_referral_min_required: Decimal = Field(
        default=Decimal("750.00"),
        max_digits=10,
        decimal_places=2,
        description="Minimum threshold for direct referral liquidation (₹750.00)",
    )
    sequential_commission_eligible: bool = Field(
        ...,
        description="True if Sequential cycle is 16/16 completed and available balance == ₹4,000.00",
    )
    sequential_commission_required: Decimal = Field(
        default=Decimal("4000.00"),
        max_digits=10,
        decimal_places=2,
        description="Required completed cycle amount for withdrawal (₹4,000.00)",
    )


class EarningsSummaryResponse(BaseModel):
    """Composite earnings dashboard data for the customer storefront."""

    direct_referral_balance: Decimal = Field(..., max_digits=10, decimal_places=2)
    sequential_commission_balance: Decimal = Field(..., max_digits=10, decimal_places=2)
    total_earnings: Decimal = Field(
        ...,
        max_digits=10,
        decimal_places=2,
        description="Combined current available balance across both wallets",
    )
    direct_referral_withdrawn: Decimal = Field(..., max_digits=10, decimal_places=2)
    sequential_commission_withdrawn: Decimal = Field(..., max_digits=10, decimal_places=2)
    total_withdrawn: Decimal = Field(..., max_digits=10, decimal_places=2)
    sequential_progress: SequentialProgress
    withdrawal_eligibility: WithdrawalEligibility


class ReferredUserItem(BaseModel):
    """Summary of a customer referred by the current user."""

    id: int
    full_name: str
    phone_masked: str
    has_purchased: bool
    first_purchase_at: Optional[datetime] = None
    reward_earned: Decimal = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)


class ReferralSummaryResponse(BaseModel):
    """Customer referral code stats and referee history."""

    referral_code: Optional[str]
    total_referrals: int
    successful_referrals: int
    total_referral_earnings: Decimal = Field(..., max_digits=10, decimal_places=2)
    referred_users: List[ReferredUserItem]
