"""Plan A Cashback API endpoints (WP-10).

Endpoints:
- GET /cashback/progress: Authenticated customer cashback progress and 48-bulb visual tracking.
- GET /cashback/history: Authenticated customer completed cycles list.
"""

from decimal import Decimal
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.billing import BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
)
from app.models.enums import Programme, WalletType, WithdrawalStatus
from app.models.user import User
from app.models.wallet import Wallet, Withdrawal
from app.schemas.cashback import (
    PlanACashbackContributionItem,
    PlanACashbackCycleSummary,
    PlanACashbackProgressResponse,
)
from app.services.wallet_service import get_or_create_wallet

logger = logging.getLogger("shopeasy.api.cashback")

router = APIRouter(prefix="/cashback", tags=["Plan A Cashback Engine"])


def mask_phone_number(phone: str) -> str:
    """Mask phone number preserving leading 2 and trailing 4 digits."""
    clean = phone.strip()
    if len(clean) >= 6:
        return f"{clean[:2]}****{clean[-4:]}"
    return "****"



@router.get("/progress", response_model=PlanACashbackProgressResponse)
def get_customer_cashback_progress(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve authenticated customer's cashback progress with 48-bulb representation.
    
    Privacy and Security Invariants:
    1. Authenticated customer access only; customer accesses only their own records.
    2. Restricted to Plan A participants (Plan B users receive 403 Forbidden).
    3. Internal queue IDs and positions are strictly omitted from the response.
    4. 48 bulbs are derived server-side (bulbs_on = completed_contributions * 3).
    5. Pure read endpoint: performs zero financial mutations.
    """
    # Programme check
    if current_user.programme != Programme.PLAN_A:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cashback progress is only available to Plan A participants.",
        )

    # 1. Query the customer's active cashback cycle
    cycle = (
        db.query(PlanACashbackCycle)
        .filter(
            PlanACashbackCycle.recipient_user_id == current_user.id,
            PlanACashbackCycle.status == "ACTIVE",
        )
        .first()
    )

    # If no active cycle, check for most recently completed cycle or waiting entries
    is_completed = False
    if not cycle:
        cycle = (
            db.query(PlanACashbackCycle)
            .filter(
                PlanACashbackCycle.recipient_user_id == current_user.id,
                PlanACashbackCycle.status == "COMPLETED",
            )
            .order_by(PlanACashbackCycle.completed_at.desc(), PlanACashbackCycle.id.desc())
            .first()
        )
        if cycle:
            is_completed = True

    # 2. Check for waiting queue entry if customer has no cycle yet
    cycle_status = "NO_CYCLE"
    current_billing_num: Optional[str] = None

    if cycle:
        cycle_status = cycle.status
        completed_count = cycle.completed_contributions
        total_earned = cycle.total_earned
        is_completed = (cycle.status == "COMPLETED")

        # Resolve Billing Number for display (e.g. AGD-000201)
        bid = db.query(BillingId).filter(BillingId.id == cycle.recipient_billing_id).first()
        if bid:
            current_billing_num = bid.billing_number
    else:
        # Check if customer has an enrolled waiting entry
        waiting_entry = (
            db.query(PlanACashbackEntry)
            .filter(
                PlanACashbackEntry.user_id == current_user.id,
                PlanACashbackEntry.status == "WAITING",
            )
            .order_by(PlanACashbackEntry.queue_position.asc())
            .first()
        )
        if waiting_entry:
            cycle_status = "WAITING"
            bid = db.query(BillingId).filter(BillingId.id == waiting_entry.billing_id).first()
            if bid:
                current_billing_num = bid.billing_number

        completed_count = 0
        total_earned = Decimal("0.00")
        is_completed = False

    # 3. Calculate 48-bulb visual progress
    # Each contribution turns on 3 bulbs
    bulbs_on = completed_count * 3
    bulbs_off = 48 - bulbs_on
    bulb_states = [True] * bulbs_on + [False] * bulbs_off

    # 4. Check wallet and withdrawal status
    wallet = get_or_create_wallet(
        db, user_id=current_user.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
    )
    wallet_balance = wallet.balance

    # Is withdrawable: must have completed 16 contributions (₹4,000) and have >= ₹4,000 balance
    is_withdrawable = is_completed and (wallet_balance >= Decimal("4000.00")) and not wallet.is_frozen

    recent_withdrawal = (
        db.query(Withdrawal)
        .filter(
            Withdrawal.user_id == current_user.id,
            Withdrawal.wallet_id == wallet.id,
        )
        .order_by(Withdrawal.requested_at.desc(), Withdrawal.id.desc())
        .first()
    )
    withdrawal_status_val = recent_withdrawal.status.value if recent_withdrawal else None

    # 5. Populate active cycle earnings and individual ₹250 contributions
    active_cycle_earnings = total_earned if (cycle and cycle.status == "ACTIVE") else Decimal("0.00")
    active_contributions: List[PlanACashbackContributionItem] = []

    if cycle:
        contrib_records = (
            db.query(PlanACashbackContribution)
            .filter(PlanACashbackContribution.cycle_id == cycle.id)
            .order_by(PlanACashbackContribution.created_at.asc(), PlanACashbackContribution.id.asc())
            .all()
        )
        recip_ref = f"Cycle #{cycle.cycle_number} ({current_billing_num})" if current_billing_num else f"Cycle #{cycle.cycle_number}"

        for c_rec in contrib_records:
            c_billing = (
                db.query(BillingId)
                .filter(BillingId.id == c_rec.contributing_billing_id)
                .first()
            )
            c_bnum = c_billing.billing_number if c_billing else f"ID-{c_rec.contributing_billing_id}"
            c_user = db.query(User).filter(User.id == c_rec.contributing_user_id).first()
            masked_phone = mask_phone_number(c_user.phone) if c_user and c_user.phone else None

            active_contributions.append(
                PlanACashbackContributionItem(
                    id=c_rec.id,
                    cycle_id=c_rec.cycle_id,
                    cycle_number=cycle.cycle_number,
                    contributing_billing_id=c_rec.contributing_billing_id,
                    contributing_billing_number=c_bnum,
                    contributing_user_masked_phone=masked_phone,
                    recipient_billing_number=current_billing_num,
                    recipient_reference=recip_ref,
                    amount=c_rec.amount,
                    status=c_rec.status,
                    idempotency_key=c_rec.idempotency_key,
                    created_at=c_rec.created_at,
                )
            )

    return PlanACashbackProgressResponse(
        has_active_cycle=(cycle is not None and cycle.status == "ACTIVE"),
        current_billing_id=current_billing_num,
        current_cycle_number=cycle.cycle_number if cycle else None,
        completed_contributions=completed_count,
        total_contributions_required=16,
        cashback_amount_earned=total_earned,
        target_cashback_amount=Decimal("4000.00"),
        cycle_status=cycle_status,
        is_completed=is_completed,
        bulbs_on=bulbs_on,
        bulbs_off=bulbs_off,
        total_bulbs=48,
        bulb_states=bulb_states,
        is_withdrawable=is_withdrawable,
        withdrawal_status=withdrawal_status_val,
        current_wallet_balance=wallet_balance,
        active_cycle_earnings=active_cycle_earnings,
        active_contributions=active_contributions,
    )


@router.get("/contributions", response_model=List[PlanACashbackContributionItem])
def list_customer_cashback_contributions(
    cycle_id: Optional[int] = Query(None, description="Optional cycle ID filter"),
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve individual ₹250 contributions allocated to the authenticated customer's cashback cycle(s)."""
    if current_user.programme != Programme.PLAN_A:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cashback contributions are only available to Plan A participants.",
        )

    query = db.query(PlanACashbackContribution).filter(
        PlanACashbackContribution.recipient_user_id == current_user.id
    )
    if cycle_id is not None:
        query = query.filter(PlanACashbackContribution.cycle_id == cycle_id)

    contribs = query.order_by(
        PlanACashbackContribution.created_at.asc(),
        PlanACashbackContribution.id.asc()
    ).all()

    # Preload caches for fast serialization
    billing_cache = {}
    cycle_cache = {}
    user_cache = {}
    items: List[PlanACashbackContributionItem] = []

    for c in contribs:
        if c.contributing_billing_id not in billing_cache:
            bid = db.query(BillingId).filter(BillingId.id == c.contributing_billing_id).first()
            billing_cache[c.contributing_billing_id] = bid.billing_number if bid else f"ID-{c.contributing_billing_id}"
        c_bnum = billing_cache[c.contributing_billing_id]

        cycle_num = 1
        recip_bnum = ""
        if c.cycle_id:
            if c.cycle_id not in cycle_cache:
                cyc = db.query(PlanACashbackCycle).filter(PlanACashbackCycle.id == c.cycle_id).first()
                if cyc:
                    rb = db.query(BillingId).filter(BillingId.id == cyc.recipient_billing_id).first()
                    cycle_cache[c.cycle_id] = (cyc.cycle_number, rb.billing_number if rb else "")
                else:
                    cycle_cache[c.cycle_id] = (1, "")
            cycle_num, recip_bnum = cycle_cache[c.cycle_id]

        if c.contributing_user_id not in user_cache:
            cu = db.query(User).filter(User.id == c.contributing_user_id).first()
            user_cache[c.contributing_user_id] = (
                mask_phone_number(cu.phone) if cu and cu.phone else "****"
            )
        masked_phone = user_cache[c.contributing_user_id]
        recip_ref = f"Cycle #{cycle_num} ({recip_bnum})" if recip_bnum else f"Cycle #{cycle_num}"

        items.append(
            PlanACashbackContributionItem(
                id=c.id,
                cycle_id=c.cycle_id,
                cycle_number=cycle_num,
                contributing_billing_id=c.contributing_billing_id,
                contributing_billing_number=c_bnum,
                contributing_user_masked_phone=masked_phone,
                recipient_billing_number=recip_bnum or None,
                recipient_reference=recip_ref,
                amount=c.amount,
                status=c.status,
                idempotency_key=c.idempotency_key,
                created_at=c.created_at,
            )
        )
    return items


@router.get("/cycles", response_model=List[PlanACashbackCycleSummary])
def list_customer_cashback_cycles(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve list of all cashback cycles (active and completed) for the authenticated customer."""
    if current_user.programme != Programme.PLAN_A:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cashback history is only available to Plan A participants.",
        )

    cycles = (
        db.query(PlanACashbackCycle)
        .filter(PlanACashbackCycle.recipient_user_id == current_user.id)
        .order_by(PlanACashbackCycle.started_at.desc(), PlanACashbackCycle.id.desc())
        .all()
    )

    return [
        PlanACashbackCycleSummary(
            cycle_id=c.id,
            cycle_number=c.cycle_number,
            completed_contributions=c.completed_contributions,
            total_earned=c.total_earned,
            status=c.status,
            is_completed=(c.status == "COMPLETED"),
            started_at=c.started_at,
            completed_at=c.completed_at,
        )
        for c in cycles
    ]

