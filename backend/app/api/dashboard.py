from decimal import Decimal
import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.enums import (
    CycleStatus,
    OrderStatus,
    QueueStatus,
    WalletType,
)
from app.models.order import Order
from app.models.queue import BeneficiaryQueue, CommissionCycle
from app.models.user import User
from app.schemas.dashboard import (
    EarningsSummaryResponse,
    ReferralSummaryResponse,
    ReferredUserItem,
    SequentialProgress,
    WithdrawalEligibility,
)
from app.services.wallet_service import get_or_create_wallet

logger = logging.getLogger("shopeasy.api.dashboard")

router = APIRouter(prefix="/dashboard", tags=["Customer Dashboard"])


def mask_phone_number(phone: str) -> str:
    """Mask phone number preserving leading 2 and trailing 4 digits."""
    clean = phone.strip()
    if len(clean) >= 6:
        return f"{clean[:2]}****{clean[-4:]}"
    return "****"


@router.get("/earnings", response_model=EarningsSummaryResponse)
def get_earnings_dashboard(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve composite metrics for customer earnings dashboard.

    Includes:
      - Direct Referral & Sequential Commission wallet balances.
      - Total available earnings and lifetime withdrawn totals.
      - 16-circle visual component progress and active/waiting/completed beneficiary states.
      - Withdrawal eligibility flags for both earning categories.
    """
    # 1. Fetch isolated wallet balances
    dr_wallet = get_or_create_wallet(
        db, user_id=current_user.id, wallet_type=WalletType.DIRECT_REFERRAL
    )
    sc_wallet = get_or_create_wallet(
        db, user_id=current_user.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
    )

    total_earnings = dr_wallet.balance + sc_wallet.balance
    total_withdrawn = dr_wallet.total_withdrawn + sc_wallet.total_withdrawn

    # 2. Fetch beneficiary queue and cycle state
    queue_entry = (
        db.query(BeneficiaryQueue)
        .filter(BeneficiaryQueue.user_id == current_user.id)
        .first()
    )
    cycle = (
        db.query(CommissionCycle)
        .filter(CommissionCycle.beneficiary_id == current_user.id)
        .first()
    )

    if not queue_entry:
        status_label = "not_enrolled"
        queue_pos = None
        completed_count = 0
        cycle_earned = Decimal("0.00")
        circle_states = [False] * 16
    elif queue_entry.status == QueueStatus.ACTIVE:
        status_label = "active"
        queue_pos = queue_entry.queue_position
        completed_count = cycle.completed_commissions if cycle else 0
        cycle_earned = cycle.total_earned if cycle else Decimal("0.00")
        circle_states = [True] * completed_count + [False] * (16 - completed_count)
    elif queue_entry.status == QueueStatus.WAITING:
        status_label = "waiting"
        queue_pos = queue_entry.queue_position
        completed_count = 0
        cycle_earned = Decimal("0.00")
        circle_states = [False] * 16
    else:  # QueueStatus.COMPLETED
        status_label = "completed"
        queue_pos = queue_entry.queue_position
        completed_count = 16
        cycle_earned = Decimal("4000.00")
        circle_states = [True] * 16

    progress = SequentialProgress(
        status=status_label,
        queue_position=queue_pos,
        completed_commissions=completed_count,
        total_earned=cycle_earned,
        target_commissions=16,
        target_amount=Decimal("4000.00"),
        circle_states=circle_states,
    )

    # 3. Compute withdrawal eligibility
    dr_eligible = dr_wallet.balance >= Decimal("750.00")
    sc_eligible = (
        cycle is not None
        and cycle.completed_commissions == 16
        and sc_wallet.balance == Decimal("4000.00")
    )

    eligibility = WithdrawalEligibility(
        direct_referral_eligible=dr_eligible,
        direct_referral_min_required=Decimal("750.00"),
        sequential_commission_eligible=sc_eligible,
        sequential_commission_required=Decimal("4000.00"),
    )

    return EarningsSummaryResponse(
        direct_referral_balance=dr_wallet.balance,
        sequential_commission_balance=sc_wallet.balance,
        total_earnings=total_earnings,
        direct_referral_withdrawn=dr_wallet.total_withdrawn,
        sequential_commission_withdrawn=sc_wallet.total_withdrawn,
        total_withdrawn=total_withdrawn,
        sequential_progress=progress,
        withdrawal_eligibility=eligibility,
    )


@router.get("/referrals", response_model=ReferralSummaryResponse)
def get_referral_summary(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve customer referral code statistics and referred customer history."""
    referees = (
        db.query(User)
        .filter(User.referred_by_id == current_user.id)
        .order_by(User.created_at.desc())
        .all()
    )

    referred_items: List[ReferredUserItem] = []
    successful_count = 0

    for referee in referees:
        first_order = (
            db.query(Order)
            .filter(
                Order.user_id == referee.id,
                Order.order_status == OrderStatus.CONFIRMED,
            )
            .order_by(Order.created_at.asc())
            .first()
        )
        has_purchased = first_order is not None
        if has_purchased:
            successful_count += 1
            reward = Decimal("750.00")
            first_purchase_at = first_order.created_at
        else:
            reward = Decimal("0.00")
            first_purchase_at = None

        referred_items.append(
            ReferredUserItem(
                id=referee.id,
                full_name=referee.full_name,
                phone_masked=mask_phone_number(referee.phone),
                has_purchased=has_purchased,
                first_purchase_at=first_purchase_at,
                reward_earned=reward,
            )
        )

    total_earnings = Decimal(successful_count) * Decimal("750.00")

    return ReferralSummaryResponse(
        referral_code=current_user.referral_code,
        total_referrals=len(referees),
        successful_referrals=successful_count,
        total_referral_earnings=total_earnings,
        referred_users=referred_items,
    )
