"""Core domain service for Plan A direct referral commission processing (WP-7)."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Callable, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.billing import BillingEngineClaim, BillingId
from app.models.commission import PlanACommission
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletReferenceType,
    WalletType,
)
from app.models.order import Order
from app.models.user import User
from app.services.wallet_service import credit_wallet

logger = logging.getLogger("shopeasy.commission.plan_a")

# Contractual amounts for Plan A Power Bank (₹3,999.00)
GROSS_COMMISSION_POOL = Decimal("750.00")
OPERATIONAL_COST_AMOUNT = Decimal("35.00")
TDS_AMOUNT = Decimal("15.00")
NET_DIRECT_COMMISSION_AMOUNT = Decimal("700.00")
ZERO_AMOUNT = Decimal("0.00")


@dataclass
class CommissionExecutionResult:
    """Structured result of a single Billing ID commission processing attempt."""

    billing_id: int
    status: str  # "EARNED", "UNALLOCATED_NO_REFERRER", "INELIGIBLE_REFERRER", "ALREADY_PROCESSED", "SKIPPED_NOT_PLAN_A", "FAILED"
    commission_id: Optional[int] = None
    referrer_id: Optional[int] = None
    net_credited: Decimal = ZERO_AMOUNT
    message: Optional[str] = None


class PlanACommissionService:
    """Domain service managing the Plan A direct referral commission engine."""

    @classmethod
    def process_billing_id(
        cls,
        billing_id: int,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> CommissionExecutionResult:
        """Process commission for a single Billing ID atomically.

        Enforces:
        - Bounded per-item transaction isolation.
        - Pessimistic row locking on MySQL / TiDB.
        - Idempotency barrier (returns existing record if already processed).
        - Referrer eligibility re-verification at execution time (RG-14).
        - Atomic commission recording and wallet ledger credit.
        - Unallocated / ineligible purchases receive zero wallet credit (BR-A7 neutrality).
        - Preserves BillingEngineClaim.status without mutation.
        """
        # 1. Resolve dedicated session
        if session_factory is not None:
            comm_db = session_factory()
        elif db is not None:
            comm_db = sessionmaker(
                bind=db.get_bind(),
                autocommit=False,
                autoflush=False,
            )()
        else:
            comm_db = SessionLocal()

        try:
            # 2. Check if already processed (Fast-path idempotency check)
            existing_comm = (
                comm_db.query(PlanACommission)
                .filter(PlanACommission.billing_id == billing_id)
                .first()
            )
            if existing_comm:
                return CommissionExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    commission_id=existing_comm.id,
                    referrer_id=existing_comm.referrer_id,
                    net_credited=existing_comm.net_amount if existing_comm.status == "EARNED" else ZERO_AMOUNT,
                    message="Commission was already processed for this Billing ID.",
                )

            # 3. Lock BillingId row
            bid = (
                comm_db.query(BillingId)
                .filter(BillingId.id == billing_id)
                .with_for_update()
                .first()
            )
            if not bid:
                return CommissionExecutionResult(
                    billing_id=billing_id,
                    status="FAILED",
                    message=f"BillingId #{billing_id} not found.",
                )

            # Programme boundary check
            if bid.programme != Programme.PLAN_A:
                return CommissionExecutionResult(
                    billing_id=billing_id,
                    status="SKIPPED_NOT_PLAN_A",
                    message=f"BillingId #{billing_id} belongs to programme '{bid.programme}', not PLAN_A.",
                )

            # Re-check under lock in case of concurrent worker race
            existing_comm_locked = (
                comm_db.query(PlanACommission)
                .filter(PlanACommission.billing_id == billing_id)
                .first()
            )
            if existing_comm_locked:
                return CommissionExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    commission_id=existing_comm_locked.id,
                    referrer_id=existing_comm_locked.referrer_id,
                    net_credited=existing_comm_locked.net_amount if existing_comm_locked.status == "EARNED" else ZERO_AMOUNT,
                    message="Commission was already processed for this Billing ID.",
                )

            # 4. Lock and inspect parent Order
            order = (
                comm_db.query(Order)
                .filter(Order.id == bid.order_id)
                .with_for_update()
                .first()
            )
            if not order:
                return CommissionExecutionResult(
                    billing_id=billing_id,
                    status="FAILED",
                    message=f"Parent Order #{bid.order_id} not found.",
                )

            purchaser_id = order.user_id
            applied_code = order.applied_referral_code
            idempotency_key = f"PA-COMM:{billing_id}"
            now = datetime.now(timezone.utc)

            # 5. Case A: Unreferred order (BR-A7 neutrality)
            if not applied_code or not applied_code.strip():
                comm = PlanACommission(
                    billing_id=bid.id,
                    order_id=order.id,
                    purchaser_id=purchaser_id,
                    referrer_id=None,
                    applied_referral_code=None,
                    gross_amount=GROSS_COMMISSION_POOL,
                    operational_cost_amount=ZERO_AMOUNT,
                    tds_amount=ZERO_AMOUNT,
                    net_amount=ZERO_AMOUNT,
                    status="UNALLOCATED_NO_REFERRER",
                    idempotency_key=idempotency_key,
                    processed_at=now,
                )
                comm_db.add(comm)
                comm_db.commit()
                return CommissionExecutionResult(
                    billing_id=bid.id,
                    status="UNALLOCATED_NO_REFERRER",
                    commission_id=comm.id,
                    referrer_id=None,
                    net_credited=ZERO_AMOUNT,
                    message="Order had no applied referral code. Unallocated pool recorded neutrally.",
                )

            # 6. Case B: Referral code present -> Validate referrer eligibility at execution time
            referrer = (
                comm_db.query(User)
                .filter(User.referral_code == applied_code.strip().upper())
                .first()
            )

            # Cross-Programme Routing Protection: If referrer belongs to Plan B,
            # Plan A direct commission must NOT process this Billing ID.
            if referrer and referrer.programme == Programme.PLAN_B:
                logger.info(
                    f"BillingId #{bid.id} (Order #{order.id}) has Plan B referrer #{referrer.id} "
                    f"({referrer.referral_code}). Skipping Plan A commission processing."
                )
                return CommissionExecutionResult(
                    billing_id=bid.id,
                    status="SKIPPED_PLAN_B_REFERRER",
                    referrer_id=referrer.id,
                    net_credited=ZERO_AMOUNT,
                    message="Referrer belongs to Plan B. Plan A direct commission skipped.",
                )

            is_eligible = True
            ineligible_reason = ""

            if not referrer:
                is_eligible = False
                ineligible_reason = f"Referral code '{applied_code}' does not match any user."
            elif not referrer.is_active or referrer.account_status == AccountStatus.DEACTIVATED:
                is_eligible = False
                ineligible_reason = "Referrer account is deactivated or inactive (RG-14)."
            elif referrer.account_status == AccountStatus.BLOCKED:
                is_eligible = False
                ineligible_reason = "Referrer account is blocked (RG-14: cannot refer or earn)."
            elif referrer.role != UserRole.CUSTOMER:
                is_eligible = False
                ineligible_reason = "Referrer has administrative role."
            elif referrer.id == purchaser_id:
                is_eligible = False
                ineligible_reason = "Self-referral is prohibited."
            else:
                # Purchase qualification requirement (RG-07 for Plan A, BR-X2 for Plan B)
                paid_purchase_count = (
                    comm_db.query(Order.id)
                    .filter(
                        Order.user_id == referrer.id,
                        Order.order_status == OrderStatus.CONFIRMED,
                        Order.payment_status == PaymentStatus.COMPLETED,
                    )
                    .count()
                )
                if paid_purchase_count == 0:
                    is_eligible = False
                    ineligible_reason = "Referrer has no qualifying confirmed paid purchase."

            # If Ineligible: Record neutrally without wallet credit
            if not is_eligible:
                comm = PlanACommission(
                    billing_id=bid.id,
                    order_id=order.id,
                    purchaser_id=purchaser_id,
                    referrer_id=referrer.id if referrer else None,
                    applied_referral_code=applied_code,
                    gross_amount=GROSS_COMMISSION_POOL,
                    operational_cost_amount=ZERO_AMOUNT,
                    tds_amount=ZERO_AMOUNT,
                    net_amount=ZERO_AMOUNT,
                    status="INELIGIBLE_REFERRER",
                    idempotency_key=idempotency_key,
                    processed_at=now,
                )
                comm_db.add(comm)
                comm_db.commit()
                return CommissionExecutionResult(
                    billing_id=bid.id,
                    status="INELIGIBLE_REFERRER",
                    commission_id=comm.id,
                    referrer_id=referrer.id if referrer else None,
                    net_credited=ZERO_AMOUNT,
                    message=f"Referrer ineligible: {ineligible_reason}",
                )

            # 7. Case C: Eligible Referrer -> Record EARNED and credit wallet atomically
            comm = PlanACommission(
                billing_id=bid.id,
                order_id=order.id,
                purchaser_id=purchaser_id,
                referrer_id=referrer.id,
                applied_referral_code=applied_code,
                gross_amount=GROSS_COMMISSION_POOL,
                operational_cost_amount=OPERATIONAL_COST_AMOUNT,
                tds_amount=TDS_AMOUNT,
                net_amount=NET_DIRECT_COMMISSION_AMOUNT,
                status="EARNED",
                idempotency_key=idempotency_key,
                processed_at=now,
            )
            comm_db.add(comm)
            comm_db.flush()

            # Credit wallet atomically in the same session
            credit_wallet(
                db=comm_db,
                user_id=referrer.id,
                wallet_type=WalletType.DIRECT_REFERRAL,
                amount=NET_DIRECT_COMMISSION_AMOUNT,
                reference_type=WalletReferenceType.DIRECT_REFERRAL,
                reference_id=comm.id,
                idempotency_key=idempotency_key,
            )

            # Atomic commit of commission row and wallet transaction
            comm_db.commit()

            logger.info(
                f"Successfully awarded ₹700 net direct commission to referrer #{referrer.id} "
                f"for BillingId #{bid.id} (Order #{order.id})."
            )
            return CommissionExecutionResult(
                billing_id=bid.id,
                status="EARNED",
                commission_id=comm.id,
                referrer_id=referrer.id,
                net_credited=NET_DIRECT_COMMISSION_AMOUNT,
                message=f"Awarded ₹700 net commission to referrer #{referrer.id}.",
            )

        except IntegrityError as exc:
            comm_db.rollback()
            # Handle duplicate race condition cleanly
            existing = (
                comm_db.query(PlanACommission)
                .filter(PlanACommission.billing_id == billing_id)
                .first()
            )
            if existing:
                return CommissionExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    commission_id=existing.id,
                    referrer_id=existing.referrer_id,
                    net_credited=existing.net_amount if existing.status == "EARNED" else ZERO_AMOUNT,
                    message="Concurrent worker processed this Billing ID.",
                )
            logger.error(f"IntegrityError processing commission for BillingId #{billing_id}: {exc}")
            return CommissionExecutionResult(
                billing_id=billing_id,
                status="FAILED",
                message=f"Database constraint violation: {exc}",
            )
        except Exception as exc:
            comm_db.rollback()
            logger.error(f"Unexpected error processing commission for BillingId #{billing_id}: {exc}", exc_info=True)
            return CommissionExecutionResult(
                billing_id=billing_id,
                status="FAILED",
                message=str(exc),
            )
        finally:
            comm_db.close()

    @classmethod
    def process_order_commissions(
        cls,
        order_id: int,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> List[CommissionExecutionResult]:
        """Process Plan A direct commissions for all Billing IDs belonging to an order.

        Each Billing ID is processed in its own dedicated, isolated transaction.
        """
        # Session for resolving billing IDs
        if session_factory is not None:
            read_db = session_factory()
        elif db is not None:
            read_db = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
        else:
            read_db = SessionLocal()

        b_ids: List[int] = []
        try:
            # Fast-path check: If order has an applied referral code from a Plan B distributor,
            # or purchaser is referred by Plan B, Plan A must not process commissions for this order.
            order = read_db.query(Order).filter(Order.id == order_id).first()
            if order:
                ref_user = None
                if order.applied_referral_code and order.applied_referral_code.strip():
                    ref_user = (
                        read_db.query(User)
                        .filter(User.referral_code == order.applied_referral_code.strip().upper())
                        .first()
                    )
                if not ref_user and order.user_id:
                    purchaser = read_db.query(User).filter(User.id == order.user_id).first()
                    if purchaser and purchaser.referred_by_id:
                        ref_user = read_db.query(User).filter(User.id == purchaser.referred_by_id).first()
                if ref_user and ref_user.programme == Programme.PLAN_B:
                    logger.info(
                        f"Order #{order_id} has Plan B referrer #{ref_user.id}. "
                        f"Skipping Plan A order commission dispatch."
                    )
                    return []

            rows = (
                read_db.query(BillingId.id)
                .filter(
                    BillingId.order_id == order_id,
                    BillingId.programme == Programme.PLAN_A,
                )
                .order_by(BillingId.sequence_number.asc())
                .all()
            )
            b_ids = [r[0] for r in rows]
        finally:
            read_db.close()

        results: List[CommissionExecutionResult] = []
        for bid in b_ids:
            res = cls.process_billing_id(
                billing_id=bid,
                db=db,
                session_factory=session_factory,
            )
            results.append(res)
        return results

