"""Schemas for Plan A and Plan B Administrative Inspection APIs (WP-11)."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import AccountStatus, Programme, WalletType


# ==============================================================================
# Plan A Inspection Schemas
# ==============================================================================

class AdminPlanACommissionResponse(BaseModel):
    """Plan A direct commission record for administrative inspection."""

    id: int
    billing_id: int
    order_id: int
    purchaser_id: int
    referrer_id: Optional[int] = None
    applied_referral_code: Optional[str] = None
    gross_amount: Decimal
    operational_cost_amount: Decimal
    tds_amount: Decimal
    net_amount: Decimal
    status: str
    processed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPlanAQueueResponse(BaseModel):
    """Plan A cashback queue summary."""

    id: int
    root_user_id: int
    root_user_name: Optional[str] = None
    active_cycle_id: Optional[int] = None
    last_allocated_position: int
    total_entries: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPlanAQueueEntryResponse(BaseModel):
    """Plan A cashback queue entry."""

    id: int
    queue_id: int
    user_id: int
    user_name: Optional[str] = None
    billing_id: int
    queue_position: int
    status: str
    enrolled_at: datetime
    activated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPlanACycleResponse(BaseModel):
    """Plan A cashback cycle."""

    id: int
    queue_id: int
    queue_entry_id: int
    recipient_user_id: int
    recipient_user_name: Optional[str] = None
    recipient_billing_id: int
    cycle_number: int
    completed_contributions: int
    total_earned: Decimal
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPlanAContributionResponse(BaseModel):
    """Plan A cashback contribution record."""

    id: int
    queue_id: int
    cycle_id: int
    contributing_billing_id: int
    contributing_user_id: int
    recipient_user_id: int
    amount: Decimal
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPlanAReserveEntryResponse(BaseModel):
    """Plan A company-owned unallocated cashback reserve entry (BR-A4 / BR-A5)."""

    id: int
    queue_id: int
    billing_id: int
    billing_number: Optional[str] = None
    customer_id: int
    amount: Decimal
    status: str  # Always "UNALLOCATED — COMPANY OWNED"
    reserved_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPlanAReserveSummaryResponse(BaseModel):
    """Aggregated financial summary of the company-owned unallocated reserve."""

    status_label: str = "UNALLOCATED — COMPANY OWNED"
    total_unallocated_amount: Decimal
    total_entries: int
    queue_breakdown: List[Dict[str, Any]]


class AdminPlanACustomerCashbackSummaryResponse(BaseModel):
    """Individual customer cashback progress and audit metrics."""

    customer_id: int
    customer_name: str
    customer_phone: str
    programme: Programme
    active_queue_id: Optional[int] = None
    active_queue_position: Optional[int] = None
    active_queue_status: Optional[str] = None
    active_cycle_id: Optional[int] = None
    completed_contributions: int
    total_earned: Decimal
    target_cashback_amount: Decimal = Decimal("4000.00")
    bulbs_on: int
    bulbs_off: int
    total_completed_cycles: int
    total_lifetime_cashback: Decimal
    wallet_balance: Decimal
    is_wallet_frozen: bool


# ==============================================================================
# Plan B Inspection Schemas
# ==============================================================================

class AdminPlanBDistributorResponse(BaseModel):
    """Plan B distributor profile for admin management."""

    id: int
    full_name: str
    phone: str
    referral_code: Optional[str] = None
    account_status: AccountStatus
    is_active: bool
    referred_by_id: Optional[int] = None
    direct_referees_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPlanBReferralRelationResponse(BaseModel):
    """Plan B direct referral relationship."""

    id: int
    referee_id: int
    referee_name: Optional[str] = None
    referee_phone: Optional[str] = None
    referrer_id: int
    referral_code_used: Optional[str] = None
    binding_channel: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminPlanBCommissionResponse(BaseModel):
    """Plan B commission item (Direct or Generation)."""

    id: int
    commission_type: str
    distributor_id: int
    referee_id: Optional[int] = None
    order_id: Optional[int] = None
    billing_id: Optional[int] = None
    billing_number: Optional[str] = None
    generation_level: int = 1
    gross_amount: Decimal
    operational_cost_amount: Decimal
    tds_amount: Decimal
    net_amount: Decimal
    status: str
    processed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPlanBOverviewSummaryResponse(BaseModel):
    """Aggregated counts for Plan B administrative overview."""

    total_distributors: int
    total_direct_commissions: int
    total_generation_commissions: int
    total_billing_ids: int

    model_config = ConfigDict(from_attributes=True)


class AdminPlanBDistributorWalletResponse(BaseModel):
    """Plan B distributor wallet overview."""

    distributor_id: int
    wallet_id: int
    wallet_type: WalletType
    balance: Decimal
    total_earned: Decimal
    total_withdrawn: Decimal
    is_frozen: bool
    recent_transactions: List[Dict[str, Any]]
    recent_withdrawals: List[Dict[str, Any]]


class AdminPlanBBillingIdResponse(BaseModel):
    """Plan B Billing ID inspection item."""

    id: int
    billing_number: str
    sequence_number: int
    order_id: int
    user_id: int
    programme: Programme
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

