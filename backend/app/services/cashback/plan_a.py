"""Core domain service for Plan A Cashback Engine (WP-10).

Governed by confirmed business decisions:
- BR-A1: Every eligible Billing ID contributes independently.
- BR-A2: Independent referral-root queues.
- BR-A3: Each eligible Billing ID first routes its ₹250 contribution, then enqueues as WAITING.
- BR-A4 (Option A): Initial Billing ID in a new queue without an active recipient routes ₹250
  to company-owned unallocated reserve (UNALLOCATED — COMPANY OWNED).
- BR-A5 (Option A): Active recipient's own subsequent purchase routes ₹250 to company-owned unallocated reserve.
- BR-X1: Repeat Plan A referral purchases are excluded from cashback queues and contributions.
- BR-A6: Completed cycle requires exactly 16 contributions of ₹250 (₹4,000.00).

Financial & Locking invariants:
- ED-05 Lock ordering: counter rows -> queue rows -> wallet rows.
- Atomic row locking via SELECT ... FOR UPDATE.
- Cross-table mutual exclusion guarantee: one Billing ID is recorded in either plan_a_cashback_contributions
  or plan_a_unallocated_cashback_reserves, never both.
- Wallet credit of ₹4,000.00 on cycle completion is strictly atomic and idempotent (CB-CREDIT:{cycle_id}).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
import random
import threading
import time
from typing import Callable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.billing import BillingEngineClaim, BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
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
from app.models.referral import ReferralRelationship
from app.models.user import User
from app.services.wallet_service import credit_wallet, get_or_create_wallet

logger = logging.getLogger("shopeasy.cashback.plan_a")

# Contractual Constants
CASHBACK_CONTRIBUTION_AMOUNT = Decimal("250.00")
CASHBACK_CYCLE_COMPLETION_AMOUNT = Decimal("4000.00")
MAX_CYCLE_CONTRIBUTIONS = 16
ZERO_AMOUNT = Decimal("0.00")


@dataclass
class CashbackExecutionResult:
    """Structured result of a single Billing ID cashback processing attempt."""

    billing_id: int
    status: str  # "CONTRIBUTED", "RESERVED_INITIAL_QUEUE", "RESERVED_RECIPIENT_PURCHASE", "SKIPPED_REPEAT_PURCHASE", "ALREADY_PROCESSED", "SKIPPED_NOT_PLAN_A", "SKIPPED_INELIGIBLE", "FAILED"
    queue_id: Optional[int] = None
    queue_entry_id: Optional[int] = None
    queue_position: Optional[int] = None
    contribution_id: Optional[int] = None
    reserve_id: Optional[int] = None
    cycle_id: Optional[int] = None
    recipient_user_id: Optional[int] = None
    cycle_completed: bool = False
    credited_amount: Decimal = ZERO_AMOUNT
    message: Optional[str] = None


class PlanACashbackService:
    """Domain service managing the Plan A sequential cashback engine."""

    _process_lock = threading.RLock()

    @classmethod
    def get_or_create_queue_root_id(
        cls,
        db: Session,
        purchaser_id: int,
        order: Optional[Order] = None,
    ) -> int:
        """Resolve the root customer user ID for the purchaser's queue hierarchy (BR-A2).
        
        Rules:
        - If purchaser has no referral relationship and order has no referral code: purchaser is their own root.
        - If purchaser entered a referral code or has an active ReferralRelationship:
          verify relationship exists and walk up the Plan A referral chain to the root.
        - If an order has an applied referral code, but no ReferralRelationship exists in the database:
          do NOT silently create a detached queue; raise an explicit RuntimeError to prevent incorrect financial posting.
        - If purchaser used a Plan B referral code: Plan B referral does not join Plan B queue;
          referee starts an independent Plan A queue (root is purchaser per BR-A2 item 6).
        """
        # Ambiguity check: order has applied referral code, but relationship wasn't created
        if order and order.applied_referral_code:
            rel_exists = (
                db.query(ReferralRelationship)
                .filter(
                    ReferralRelationship.referee_id == purchaser_id,
                    ReferralRelationship.is_active == True,  # noqa: E712
                )
                .first()
            )
            if not rel_exists:
                raise RuntimeError(
                    f"Ambiguous referral queue routing: Order #{order.id} applied referral code "
                    f"'{order.applied_referral_code}', but no active ReferralRelationship exists for customer #{purchaser_id}."
                )

        curr_id = purchaser_id
        visited = set()

        while curr_id not in visited:
            visited.add(curr_id)
            rel = (
                db.query(ReferralRelationship)
                .filter(
                    ReferralRelationship.referee_id == curr_id,
                    ReferralRelationship.is_active == True,  # noqa: E712
                )
                .first()
            )
            if not rel:
                return curr_id

            # Rule BR-A2 item 6: If referred by Plan B, do not join Plan B queue
            if rel.referrer_programme != Programme.PLAN_A:
                return curr_id

            # Referrer is Plan A: advance to referrer
            curr_id = rel.referrer_id

        # Safeguard against cyclic graphs
        return curr_id

    @classmethod
    def get_or_create_queue(cls, db: Session, root_user_id: int, for_update: bool = True) -> PlanACashbackQueue:
        """Retrieve or initialize an independent FIFO cashback queue (BR-A2)."""
        query = db.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == root_user_id)
        if for_update:
            query = query.with_for_update()

        queue = query.first()
        if not queue:
            try:
                with db.begin_nested():
                    queue = PlanACashbackQueue(
                        root_user_id=root_user_id,
                        last_allocated_position=0,
                        active_cycle_id=None,
                    )
                    db.add(queue)
                    db.flush()
            except IntegrityError:
                query = db.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == root_user_id)
                if for_update:
                    query = query.with_for_update()
                queue = query.first()
                if not queue:
                    raise RuntimeError(f"Unable to retrieve queue for root user #{root_user_id} after collision.")

        return queue

    @classmethod
    def is_repeat_referral_purchase(cls, db: Session, order: Order, purchaser_id: int) -> bool:
        """Check if order is a Plan A repeat purchase with a referral code (BR-X1).
        
        Rules:
        - If order does not have an applied referral code, it is not a repeat referral purchase.
        - If purchaser has prior confirmed orders, this is a repeat purchase.
        """
        if not order.applied_referral_code or not order.applied_referral_code.strip():
            return False

        # Check for prior confirmed/paid orders for this customer
        prior_order = (
            db.query(Order.id)
            .filter(
                Order.user_id == purchaser_id,
                Order.id != order.id,
                Order.order_status == OrderStatus.CONFIRMED,
                Order.payment_status == PaymentStatus.COMPLETED,
            )
            .first()
        )
        return prior_order is not None

    @classmethod
    def process_billing_id(
        cls,
        billing_id: int,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        max_retries: int = 5,
    ) -> CashbackExecutionResult:
        """Process cashback allocation for a single Billing ID atomically with concurrency retry.
        
        Enforces:
        - Bounded per-item transaction isolation.
        - Pessimistic row locking in ED-05 order (BillingId/Order -> Queue -> Wallet).
        - Idempotency barrier (returns existing record if already processed).
        - Mutual exclusion: one Billing ID is recorded in either contribution or reserve table, never both.
        - BR-A1, BR-A2, BR-A3, BR-A4, BR-A5, BR-X1, BR-A6 compliance.
        """
        for attempt in range(max_retries):
            sleep_time: Optional[float] = None
            with cls._process_lock:
                if session_factory is not None:
                    cb_db = session_factory()
                elif db is not None:
                    cb_db = sessionmaker(
                        bind=db.get_bind(),
                        autocommit=False,
                        autoflush=False,
                    )()
                else:
                    cb_db = SessionLocal()

                try:
                    return cls._process_billing_id_once(billing_id, cb_db)
                except (IntegrityError, OperationalError) as exc:
                    cb_db.rollback()
                    # Handle concurrent race condition cleanly
                    existing_contrib = (
                        cb_db.query(PlanACashbackContribution)
                        .filter(PlanACashbackContribution.contributing_billing_id == billing_id)
                        .first()
                    )
                    if existing_contrib:
                        entry = cb_db.query(PlanACashbackEntry).filter(PlanACashbackEntry.billing_id == billing_id).first()
                        return CashbackExecutionResult(
                            billing_id=billing_id,
                            status="ALREADY_PROCESSED",
                            queue_id=existing_contrib.queue_id,
                            queue_entry_id=entry.id if entry else None,
                            queue_position=entry.queue_position if entry else None,
                            contribution_id=existing_contrib.id,
                            cycle_id=existing_contrib.cycle_id,
                            recipient_user_id=existing_contrib.recipient_user_id,
                            message="Cashback contribution was already processed concurrently.",
                        )
                    existing_reserve = (
                        cb_db.query(PlanAUnallocatedCashbackReserve)
                        .filter(PlanAUnallocatedCashbackReserve.billing_id == billing_id)
                        .first()
                    )
                    if existing_reserve:
                        entry = cb_db.query(PlanACashbackEntry).filter(PlanACashbackEntry.billing_id == billing_id).first()
                        return CashbackExecutionResult(
                            billing_id=billing_id,
                            status="ALREADY_PROCESSED",
                            queue_id=existing_reserve.queue_id,
                            queue_entry_id=entry.id if entry else None,
                            queue_position=entry.queue_position if entry else None,
                            reserve_id=existing_reserve.id,
                            message="Billing ID was already recorded in company-owned unallocated reserve concurrently.",
                        )

                    # Retry on transient uniqueness or lock collision if retries remain
                    if attempt < max_retries - 1:
                        sleep_time = 0.05 * (2 ** attempt) + random.uniform(0.01, 0.05)
                        logger.warning(
                            f"Concurrency collision processing cashback for Billing ID #{billing_id} "
                            f"(attempt {attempt + 1}/{max_retries}): {exc}. Retrying in {sleep_time:.3f}s..."
                        )
                    else:
                        logger.error(f"IntegrityError processing cashback for Billing ID #{billing_id}: {exc}")
                        return CashbackExecutionResult(
                            billing_id=billing_id,
                            status="FAILED",
                            message=str(exc),
                        )
                except Exception as exc:
                    cb_db.rollback()
                    logger.error(f"Error processing cashback for Billing ID #{billing_id}: {exc}", exc_info=True)
                    return CashbackExecutionResult(
                        billing_id=billing_id,
                        status="FAILED",
                        message=str(exc),
                    )
                finally:
                    cb_db.close()

            if sleep_time is not None:
                time.sleep(sleep_time)

        return CashbackExecutionResult(
            billing_id=billing_id,
            status="FAILED",
            message=f"Failed to process cashback after {max_retries} attempts.",
        )

    @classmethod
    def _process_billing_id_once(
        cls,
        billing_id: int,
        cb_db: Session,
    ) -> CashbackExecutionResult:
        """Internal single-attempt execution under an active session."""
        try:
            # 1. Fast-path idempotency check across both tables
            existing_contrib = (
                cb_db.query(PlanACashbackContribution)
                .filter(PlanACashbackContribution.contributing_billing_id == billing_id)
                .first()
            )
            if existing_contrib:
                entry = (
                    cb_db.query(PlanACashbackEntry)
                    .filter(PlanACashbackEntry.billing_id == billing_id)
                    .first()
                )
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    queue_id=existing_contrib.queue_id,
                    queue_entry_id=entry.id if entry else None,
                    queue_position=entry.queue_position if entry else None,
                    contribution_id=existing_contrib.id,
                    cycle_id=existing_contrib.cycle_id,
                    recipient_user_id=existing_contrib.recipient_user_id,
                    message="Cashback contribution was already processed for this Billing ID.",
                )

            existing_reserve = (
                cb_db.query(PlanAUnallocatedCashbackReserve)
                .filter(PlanAUnallocatedCashbackReserve.billing_id == billing_id)
                .first()
            )
            if existing_reserve:
                entry = (
                    cb_db.query(PlanACashbackEntry)
                    .filter(PlanACashbackEntry.billing_id == billing_id)
                    .first()
                )
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    queue_id=existing_reserve.queue_id,
                    queue_entry_id=entry.id if entry else None,
                    queue_position=entry.queue_position if entry else None,
                    reserve_id=existing_reserve.id,
                    recipient_user_id=None,
                    message="Billing ID was already recorded in company-owned unallocated reserve.",
                )

            # 2. Lock BillingId row
            bid = (
                cb_db.query(BillingId)
                .filter(BillingId.id == billing_id)
                .with_for_update()
                .first()
            )
            if not bid:
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="FAILED",
                    message=f"BillingId #{billing_id} not found.",
                )

            # Programme boundary check
            if bid.programme != Programme.PLAN_A:
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="SKIPPED_NOT_PLAN_A",
                    message=f"BillingId #{billing_id} belongs to programme '{bid.programme}', not PLAN_A.",
                )

            # Re-check under lock
            existing_contrib_locked = (
                cb_db.query(PlanACashbackContribution)
                .filter(PlanACashbackContribution.contributing_billing_id == billing_id)
                .first()
            )
            if existing_contrib_locked:
                entry = cb_db.query(PlanACashbackEntry).filter(PlanACashbackEntry.billing_id == billing_id).first()
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    queue_id=existing_contrib_locked.queue_id,
                    queue_entry_id=entry.id if entry else None,
                    queue_position=entry.queue_position if entry else None,
                    contribution_id=existing_contrib_locked.id,
                    cycle_id=existing_contrib_locked.cycle_id,
                    recipient_user_id=existing_contrib_locked.recipient_user_id,
                    message="Cashback contribution was already processed for this Billing ID.",
                )

            existing_reserve_locked = (
                cb_db.query(PlanAUnallocatedCashbackReserve)
                .filter(PlanAUnallocatedCashbackReserve.billing_id == billing_id)
                .first()
            )
            if existing_reserve_locked:
                entry = cb_db.query(PlanACashbackEntry).filter(PlanACashbackEntry.billing_id == billing_id).first()
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="ALREADY_PROCESSED",
                    queue_id=existing_reserve_locked.queue_id,
                    queue_entry_id=entry.id if entry else None,
                    queue_position=entry.queue_position if entry else None,
                    reserve_id=existing_reserve_locked.id,
                    message="Billing ID was already recorded in company-owned unallocated reserve.",
                )

            # 3. Lock and inspect parent Order
            order = (
                cb_db.query(Order)
                .filter(Order.id == bid.order_id)
                .with_for_update()
                .first()
            )
            if not order:
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="FAILED",
                    message=f"Parent Order #{bid.order_id} not found.",
                )

            purchaser_id = order.user_id

            # 4. Check BR-X1: Repeat Plan A purchase with referral code
            if cls.is_repeat_referral_purchase(cb_db, order, purchaser_id):
                logger.info(
                    f"Billing ID #{billing_id} (Order #{order.id}) is a repeat Plan A referral purchase (BR-X1). "
                    f"Bypassing cashback engine."
                )
                return CashbackExecutionResult(
                    billing_id=billing_id,
                    status="SKIPPED_REPEAT_PURCHASE",
                    message="Repeat Plan A purchase using a referral code is excluded from cashback (BR-X1).",
                )

            # 5. Lock Queue row in ED-05 order
            root_user_id = cls.get_or_create_queue_root_id(cb_db, purchaser_id, order=order)
            queue = cls.get_or_create_queue(cb_db, root_user_id=root_user_id, for_update=True)

            # 6. Determine Active Recipient / Active Cycle
            active_cycle: Optional[PlanACashbackCycle] = None
            if queue.active_cycle_id is not None:
                active_cycle = (
                    cb_db.query(PlanACashbackCycle)
                    .filter(
                        PlanACashbackCycle.id == queue.active_cycle_id,
                        PlanACashbackCycle.queue_id == queue.id,
                    )
                    .with_for_update()
                    .first()
                )

            # If no active cycle pointer, check if there's any active cycle in queue
            if not active_cycle:
                active_cycle = (
                    cb_db.query(PlanACashbackCycle)
                    .filter(
                        PlanACashbackCycle.queue_id == queue.id,
                        PlanACashbackCycle.status == "ACTIVE",
                    )
                    .with_for_update()
                    .first()
                )
                if active_cycle:
                    queue.active_cycle_id = active_cycle.id

            # 7. Route Contribution according to BR-A4, BR-A5, or Standard Contribution
            contrib_record: Optional[PlanACashbackContribution] = None
            reserve_record: Optional[PlanAUnallocatedCashbackReserve] = None
            cycle_completed_now = False
            credited_amount = ZERO_AMOUNT

            # Case BR-A4: Initial Billing ID in brand-new queue (no active recipient ahead)
            if not active_cycle:
                reserve_record = PlanAUnallocatedCashbackReserve(
                    queue_id=queue.id,
                    billing_id=bid.id,
                    customer_id=purchaser_id,
                    amount=CASHBACK_CONTRIBUTION_AMOUNT,
                    status="UNALLOCATED — COMPANY OWNED",
                    idempotency_key=f"CB-RES:{bid.id}",
                )
                cb_db.add(reserve_record)
                cb_db.flush()
                logger.info(
                    f"BR-A4 applied: Billing ID #{billing_id} is first in new queue #{queue.id}. "
                    f"Recorded ₹{CASHBACK_CONTRIBUTION_AMOUNT} into company-owned reserve."
                )

            # Case BR-A5: Active recipient's own subsequent purchase
            elif active_cycle.recipient_user_id == purchaser_id:
                reserve_record = PlanAUnallocatedCashbackReserve(
                    queue_id=queue.id,
                    billing_id=bid.id,
                    customer_id=purchaser_id,
                    amount=CASHBACK_CONTRIBUTION_AMOUNT,
                    status="UNALLOCATED — COMPANY OWNED",
                    idempotency_key=f"CB-RES:{bid.id}",
                )
                cb_db.add(reserve_record)
                cb_db.flush()
                logger.info(
                    f"BR-A5 applied: Purchaser #{purchaser_id} is active recipient for cycle #{active_cycle.id}. "
                    f"Recorded ₹{CASHBACK_CONTRIBUTION_AMOUNT} into company-owned reserve."
                )

            # Case Standard: Active recipient ahead receives ₹250 contribution
            else:
                # Assert cycle invariant before contribution
                if active_cycle.completed_contributions >= MAX_CYCLE_CONTRIBUTIONS:
                    raise RuntimeError(
                        f"Active cycle #{active_cycle.id} is already full ({active_cycle.completed_contributions} contributions). "
                        f"Cannot accept contribution."
                    )

                contrib_record = PlanACashbackContribution(
                    queue_id=queue.id,
                    cycle_id=active_cycle.id,
                    contributing_billing_id=bid.id,
                    contributing_user_id=purchaser_id,
                    recipient_user_id=active_cycle.recipient_user_id,
                    amount=CASHBACK_CONTRIBUTION_AMOUNT,
                    status="ALLOCATED",
                    idempotency_key=f"CB-CONTRIB:{bid.id}",
                )
                cb_db.add(contrib_record)

                # Atomically increment cycle counters
                active_cycle.completed_contributions += 1
                active_cycle.total_earned += CASHBACK_CONTRIBUTION_AMOUNT

                logger.info(
                    f"Contributed ₹{CASHBACK_CONTRIBUTION_AMOUNT} from Billing ID #{billing_id} "
                    f"to Cycle #{active_cycle.id} (recipient #{active_cycle.recipient_user_id}). "
                    f"Progress: {active_cycle.completed_contributions}/{MAX_CYCLE_CONTRIBUTIONS} (₹{active_cycle.total_earned})."
                )

                # Check if cycle completes (16 contributions = ₹4,000.00)
                if active_cycle.completed_contributions == MAX_CYCLE_CONTRIBUTIONS:
                    cycle_completed_now = True
                    active_cycle.status = "COMPLETED"
                    active_cycle.completed_at = datetime.now(timezone.utc)

                    # Update queue entry status
                    recipient_entry = (
                        cb_db.query(PlanACashbackEntry)
                        .filter(PlanACashbackEntry.id == active_cycle.queue_entry_id)
                        .with_for_update()
                        .first()
                    )
                    if recipient_entry:
                        recipient_entry.status = "COMPLETED"
                        recipient_entry.completed_at = datetime.now(timezone.utc)

                    # Wallet credit in ED-05 order (queue -> wallet)
                    credit_key = f"CB-CREDIT:{active_cycle.id}"
                    wallet, tx = credit_wallet(
                        db=cb_db,
                        user_id=active_cycle.recipient_user_id,
                        wallet_type=WalletType.SEQUENTIAL_COMMISSION,
                        amount=CASHBACK_CYCLE_COMPLETION_AMOUNT,
                        reference_type=WalletReferenceType.SEQUENTIAL_COMMISSION,
                        reference_id=active_cycle.id,
                        idempotency_key=credit_key,
                    )
                    credited_amount = CASHBACK_CYCLE_COMPLETION_AMOUNT
                    logger.info(
                        f"Cycle #{active_cycle.id} COMPLETED. Credited ₹{CASHBACK_CYCLE_COMPLETION_AMOUNT} "
                        f"to customer #{active_cycle.recipient_user_id} wallet #{wallet.id} (tx #{tx.id})."
                    )

                    # Clear queue active cycle pointer
                    queue.active_cycle_id = None

                    # Emit in-dashboard notification for Plan A cycle completed (R-10)
                    from app.services.notification_service import (
                        NotificationEvent,
                        NotificationService,
                    )
                    NotificationService.emit_admin_notification(
                        db=cb_db,
                        programme=Programme.PLAN_A,
                        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED,
                        title="Cashback Cycle Completed",
                        message=(
                            f"Cashback cycle #{active_cycle.id} for customer #{active_cycle.recipient_user_id} "
                            f"completed successfully (₹{CASHBACK_CYCLE_COMPLETION_AMOUNT:,.2f})."
                        ),
                        reference_type="cycle",
                        reference_id=active_cycle.id,
                    )

            # 8. Enqueue the Purchaser's Billing ID (BR-A3)
            # Allocation occurs strictly after contribution routing
            max_entry_pos = (
                cb_db.query(func.coalesce(func.max(PlanACashbackEntry.queue_position), 0))
                .filter(PlanACashbackEntry.queue_id == queue.id)
                .scalar()
            )
            new_position = max(int(queue.last_allocated_position or 0), int(max_entry_pos or 0)) + 1
            queue.last_allocated_position = new_position

            entry_status = "WAITING"
            # Only activate immediately if brand-new queue with no prior active cycle
            should_activate_immediately = (queue.active_cycle_id is None) and (active_cycle is None)

            entry = PlanACashbackEntry(
                queue_id=queue.id,
                user_id=purchaser_id,
                billing_id=bid.id,
                queue_position=new_position,
                status="ACTIVE" if should_activate_immediately else entry_status,
                enrolled_at=datetime.now(timezone.utc),
                activated_at=datetime.now(timezone.utc) if should_activate_immediately else None,
            )
            cb_db.add(entry)
            cb_db.flush()

            # If should activate immediately, create new cycle for this entry
            if should_activate_immediately:
                max_cycle_num = (
                    cb_db.query(func.coalesce(func.max(PlanACashbackCycle.cycle_number), 0))
                    .filter(PlanACashbackCycle.queue_id == queue.id)
                    .scalar()
                )
                new_cycle_number = int(max_cycle_num) + 1
                new_cycle = PlanACashbackCycle(
                    queue_id=queue.id,
                    queue_entry_id=entry.id,
                    recipient_user_id=purchaser_id,
                    recipient_billing_id=bid.id,
                    cycle_number=new_cycle_number,
                    completed_contributions=0,
                    total_earned=ZERO_AMOUNT,
                    status="ACTIVE",
                    started_at=datetime.now(timezone.utc),
                )
                cb_db.add(new_cycle)
                cb_db.flush()
                queue.active_cycle_id = new_cycle.id
                logger.info(
                    f"New cycle #{new_cycle.id} (Cycle #{new_cycle_number}) started for queue entry #{entry.id} "
                    f"(user #{purchaser_id}, billing #{bid.id}) in queue #{queue.id}."
                )

            # If an existing cycle completed and we didn't activate this purchaser immediately (e.g. earlier waiting entries exist)
            elif queue.active_cycle_id is None:
                # Find the next WAITING entry in FIFO order
                # Exclude users who have completed 3 cycles (48 contributions / 48 bulbs completed)
                graduated_user_ids = [
                    row[0]
                    for row in cb_db.query(PlanACashbackCycle.recipient_user_id)
                    .filter(
                        PlanACashbackCycle.queue_id == queue.id,
                        PlanACashbackCycle.status == "COMPLETED",
                    )
                    .group_by(PlanACashbackCycle.recipient_user_id)
                    .having(func.count(PlanACashbackCycle.id) >= 3)
                    .all()
                ]

                next_entry_query = (
                    cb_db.query(PlanACashbackEntry)
                    .filter(
                        PlanACashbackEntry.queue_id == queue.id,
                        PlanACashbackEntry.status == "WAITING",
                    )
                )
                if graduated_user_ids:
                    next_entry_query = next_entry_query.filter(
                        ~PlanACashbackEntry.user_id.in_(graduated_user_ids)
                    )

                next_entry = (
                    next_entry_query
                    .order_by(PlanACashbackEntry.queue_position.asc())
                    .with_for_update()
                    .first()
                )
                if next_entry:
                    next_entry.status = "ACTIVE"
                    next_entry.activated_at = datetime.now(timezone.utc)
                    max_cycle_num = (
                        cb_db.query(func.coalesce(func.max(PlanACashbackCycle.cycle_number), 0))
                        .filter(PlanACashbackCycle.queue_id == queue.id)
                        .scalar()
                    )
                    next_cycle_number = int(max_cycle_num) + 1
                    next_cycle = PlanACashbackCycle(
                        queue_id=queue.id,
                        queue_entry_id=next_entry.id,
                        recipient_user_id=next_entry.user_id,
                        recipient_billing_id=next_entry.billing_id,
                        cycle_number=next_cycle_number,
                        completed_contributions=0,
                        total_earned=ZERO_AMOUNT,
                        status="ACTIVE",
                        started_at=datetime.now(timezone.utc),
                    )
                    cb_db.add(next_cycle)
                    cb_db.flush()
                    queue.active_cycle_id = next_cycle.id
                    logger.info(
                        f"Advanced queue #{queue.id}: activated entry #{next_entry.id} (user #{next_entry.user_id}) "
                        f"as new cycle #{next_cycle.id} (Cycle #{next_cycle_number})."
                    )

            status_str = "CONTRIBUTED"
            if reserve_record is not None:
                if not active_cycle:
                    status_str = "RESERVED_INITIAL_QUEUE"
                else:
                    status_str = "RESERVED_RECIPIENT_PURCHASE"

            # Pre-extract scalars before commit to prevent attribute expiration race in concurrent environments
            queue_id_val = queue.id
            entry_id_val = entry.id
            entry_pos_val = entry.queue_position
            contrib_id_val = contrib_record.id if contrib_record else None
            reserve_id_val = reserve_record.id if reserve_record else None
            cycle_id_val = active_cycle.id if active_cycle else None
            recip_user_id_val = active_cycle.recipient_user_id if active_cycle else None

            # 9. Commit transaction
            cb_db.commit()

            return CashbackExecutionResult(
                billing_id=billing_id,
                status=status_str,
                queue_id=queue_id_val,
                queue_entry_id=entry_id_val,
                queue_position=entry_pos_val,
                contribution_id=contrib_id_val,
                reserve_id=reserve_id_val,
                cycle_id=cycle_id_val,
                recipient_user_id=recip_user_id_val,
                cycle_completed=cycle_completed_now,
                credited_amount=credited_amount,
                message=f"Cashback processed successfully with status {status_str}.",
            )
        finally:
            pass

    @classmethod
    def process_order_cashback(
        cls,
        order_id: int,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> List[CashbackExecutionResult]:
        """Process cashback sequentially for all eligible Plan A Billing IDs in an order."""
        def get_session() -> Session:
            if session_factory is not None:
                return session_factory()
            if db is not None:
                return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
            return SessionLocal()

        read_session = get_session()
        try:
            billing_ids = (
                read_session.query(BillingId.id)
                .filter(
                    BillingId.order_id == order_id,
                    BillingId.programme == Programme.PLAN_A,
                )
                .order_by(BillingId.unit_index.asc(), BillingId.sequence_number.asc())
                .all()
            )
            bids = [r[0] for r in billing_ids]
        finally:
            read_session.close()

        results: List[CashbackExecutionResult] = []
        for bid_id in bids:
            res = cls.process_billing_id(billing_id=bid_id, db=db, session_factory=session_factory)
            results.append(res)

        return results

    @classmethod
    def get_cashback_state(
        cls,
        db: Session,
        user_id: int,
    ) -> dict:
        """Query user's cashback queue entries, active cycles, and history for API/dashboard."""
        entries = (
            db.query(PlanACashbackEntry)
            .filter(PlanACashbackEntry.user_id == user_id)
            .order_by(PlanACashbackEntry.queue_position.asc())
            .all()
        )

        cycles = (
            db.query(PlanACashbackCycle)
            .filter(PlanACashbackCycle.recipient_user_id == user_id)
            .order_by(PlanACashbackCycle.started_at.desc())
            .all()
        )

        return {
            "user_id": user_id,
            "entries_count": len(entries),
            "entries": [
                {
                    "id": e.id,
                    "queue_id": e.queue_id,
                    "billing_id": e.billing_id,
                    "queue_position": e.queue_position,
                    "status": e.status,
                    "enrolled_at": e.enrolled_at.isoformat() if e.enrolled_at else None,
                    "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                }
                for e in entries
            ],
            "cycles_count": len(cycles),
            "cycles": [
                {
                    "id": c.id,
                    "queue_id": c.queue_id,
                    "queue_entry_id": c.queue_entry_id,
                    "completed_contributions": c.completed_contributions,
                    "total_earned": float(c.total_earned),
                    "status": c.status,
                    "started_at": c.started_at.isoformat() if c.started_at else None,
                    "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                }
                for c in cycles
            ],
        }

