from datetime import datetime
from decimal import Decimal
import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.commission import SequentialCommission
from app.models.enums import (
    CycleStatus,
    QueueStatus,
    WalletReferenceType,
    WalletType,
)
from app.models.order import Order
from app.models.queue import BeneficiaryQueue, CommissionCycle, QueueControl
from app.services.wallet_service import credit_wallet

logger = logging.getLogger("shopeasy.queue")

COMMISSION_AMOUNT = Decimal("250.00")
MAX_COMMISSIONS_PER_CYCLE = 16


def lock_queue_control(db: Session) -> QueueControl:
    """Acquire a pessimistic exclusive row-level lock on the singleton QueueControl row.

    Serializes global beneficiary queue modifications, cycle progressions,
    and commission distributions across concurrent transactions.

    Args:
        db: Active SQLAlchemy database session.

    Returns:
        The locked QueueControl singleton instance (id=1).
    """
    queue_control = (
        db.query(QueueControl)
        .filter(QueueControl.id == 1)
        .with_for_update()
        .first()
    )
    if not queue_control:
        # Failsafe if not seeded
        queue_control = QueueControl(
            id=1,
            active_cycle_id=None,
            active_beneficiary_id=None,
            active_cycle_status=None,
            last_allocated_position=0,
        )
        db.add(queue_control)
        db.flush()
        db.refresh(queue_control)

    return queue_control


def determine_sequential_eligibility(
    queue_control: QueueControl,
    buyer_id: int,
    has_power_bank: bool,
) -> Tuple[bool, Optional[int]]:
    """Determine whether an order qualifies for the ₹250 Sequential Commission.

    Must be called under the QueueControl lock.

    Rules:
      - Order must contain at least one eligible product (Power Bank).
      - An active beneficiary must exist in the queue.
      - The buyer must NOT be that active beneficiary (own-order exclusion).

    Args:
        queue_control: Locked QueueControl row.
        buyer_id: ID of customer placing the order.
        has_power_bank: Whether the order includes at least one Power Bank unit.

    Returns:
        Tuple of (applies: bool, active_beneficiary_id: Optional[int]).
    """
    active_beneficiary_id = queue_control.active_beneficiary_id
    if has_power_bank and active_beneficiary_id is not None and active_beneficiary_id != buyer_id:
        return True, active_beneficiary_id
    return False, active_beneficiary_id


def enroll_customer_in_queue(
    db: Session,
    customer_id: int,
    queue_control: QueueControl,
) -> BeneficiaryQueue:
    """Enroll a customer into the global FIFO beneficiary queue on their first successful order.

    Rules:
      - Chronological FIFO sequence (`queue_position = last_allocated_position + 1`).
      - Initial Queue Bootstrap: If no active beneficiary exists, the customer is immediately
        activated (`status = ACTIVE`) and their lifetime `CommissionCycle` is initialized with
        0 completed commissions and ₹0.00 earned.
      - If an active beneficiary already exists, the customer enters as `status = WAITING`.
      - Lifetime limit: Unique constraint `uq_queue_user` ensures one queue entry per customer.

    Args:
        db: Active SQLAlchemy database session.
        customer_id: ID of the customer placing their first successful order.
        queue_control: Locked QueueControl instance.

    Returns:
        The created BeneficiaryQueue record.
    """
    # 1. Check if customer is already enrolled (idempotency guard)
    existing_entry = (
        db.query(BeneficiaryQueue)
        .filter(BeneficiaryQueue.user_id == customer_id)
        .first()
    )
    if existing_entry:
        logger.info(
            f"Customer #{customer_id} already enrolled in beneficiary queue at position #{existing_entry.queue_position}."
        )
        return existing_entry

    # 2. Assign next chronological queue position
    queue_control.last_allocated_position += 1
    new_position = queue_control.last_allocated_position
    now = datetime.utcnow()

    # 3. Check for initial queue activation (bootstrap)
    if queue_control.active_beneficiary_id is None:
        # Bootstrap: customer becomes active beneficiary immediately
        queue_entry = BeneficiaryQueue(
            user_id=customer_id,
            queue_position=new_position,
            status=QueueStatus.ACTIVE,
            enrolled_at=now,
            activated_at=now,
        )
        db.add(queue_entry)
        db.flush()

        # Initialize lifetime CommissionCycle (0 / 16 commissions)
        cycle = CommissionCycle(
            queue_entry_id=queue_entry.id,
            beneficiary_id=customer_id,
            cycle_number=1,
            status=CycleStatus.ACTIVE,
            completed_commissions=0,
            total_earned=Decimal("0.00"),
            started_at=now,
        )
        db.add(cycle)
        db.flush()

        # Update QueueControl active pointers
        queue_control.active_cycle_id = cycle.id
        queue_control.active_beneficiary_id = customer_id
        queue_control.active_cycle_status = CycleStatus.ACTIVE
        queue_control.updated_at = now

        logger.info(
            f"Bootstrapped customer #{customer_id} as the active beneficiary at queue position #{new_position} "
            f"(cycle #{cycle.id})."
        )
        return queue_entry

    # 4. Standard enrollment: enter as waiting
    queue_entry = BeneficiaryQueue(
        user_id=customer_id,
        queue_position=new_position,
        status=QueueStatus.WAITING,
        enrolled_at=now,
    )
    db.add(queue_entry)
    db.flush()

    logger.info(
        f"Enrolled customer #{customer_id} in beneficiary queue at position #{new_position} (status=waiting)."
    )
    return queue_entry


def process_sequential_commission(
    db: Session,
    order: Order,
    active_beneficiary_id: int,
    queue_control: QueueControl,
) -> SequentialCommission:
    """Credit ₹250 to the active beneficiary and manage 16-commission cycle progression and queue rotation.

    Must be executed under the QueueControl lock.

    Steps:
      1. Lock active CommissionCycle row.
      2. Record SequentialCommission ledger row.
      3. Increment cycle completed_commissions and total_earned.
      4. Credit active beneficiary's Sequential Commission Wallet with ₹250.
      5. If completed_commissions reaches 16:
         a. Close cycle (`status = COMPLETED`).
         b. Close current queue entry (`status = COMPLETED`).
         c. Rotate queue: activate next waiting customer in FIFO order.
         d. If no waiting customer exists, set QueueControl active pointers to NULL.

    Args:
        db: Active SQLAlchemy database session.
        order: Confirmed source Order generating the commission.
        active_beneficiary_id: User ID of the active beneficiary.
        queue_control: Locked QueueControl row.

    Returns:
        Created SequentialCommission instance.
    """
    now = datetime.utcnow()

    # 1. Lock active commission cycle
    active_cycle = (
        db.query(CommissionCycle)
        .filter(CommissionCycle.id == queue_control.active_cycle_id)
        .with_for_update()
        .first()
    )
    if not active_cycle or active_cycle.status != CycleStatus.ACTIVE:
        raise RuntimeError(
            f"Active commission cycle #{queue_control.active_cycle_id} not found or not in active state."
        )

    next_commission_number = active_cycle.completed_commissions + 1
    if next_commission_number > MAX_COMMISSIONS_PER_CYCLE:
        raise RuntimeError(
            f"Commission cycle #{active_cycle.id} has already reached maximum {MAX_COMMISSIONS_PER_CYCLE} commissions."
        )

    # 2. Record SequentialCommission
    seq_comm = SequentialCommission(
        cycle_id=active_cycle.id,
        beneficiary_id=active_beneficiary_id,
        source_order_id=order.id,
        commission_number=next_commission_number,
        amount=COMMISSION_AMOUNT,
        created_at=now,
    )
    db.add(seq_comm)
    db.flush()

    # 3. Advance cycle counters
    active_cycle.completed_commissions = next_commission_number
    active_cycle.total_earned += COMMISSION_AMOUNT

    # 4. Credit beneficiary's Sequential Commission Wallet
    credit_wallet(
        db=db,
        user_id=active_beneficiary_id,
        wallet_type=WalletType.SEQUENTIAL_COMMISSION,
        amount=COMMISSION_AMOUNT,
        reference_type=WalletReferenceType.SEQUENTIAL_COMMISSION,
        reference_id=seq_comm.id,
        idempotency_key=f"SC-{order.id}-{seq_comm.id}",
    )

    logger.info(
        f"Credited commission #{next_commission_number}/{MAX_COMMISSIONS_PER_CYCLE} (₹{COMMISSION_AMOUNT}) "
        f"for order #{order.id} to beneficiary #{active_beneficiary_id} (cycle #{active_cycle.id})."
    )

    # 5. Check for 16-commission cycle completion and rotation
    if next_commission_number == MAX_COMMISSIONS_PER_CYCLE:
        logger.info(
            f"Commission cycle #{active_cycle.id} reached 16 commissions for customer #{active_beneficiary_id} "
            f"(16 commissions = ₹4,000.00 earned). Initiating queue rotation..."
        )

        # Step 1: Temporarily clear QueueControl active pointers.
        # This satisfies chk_qc_active_triple ((NULL, NULL, NULL)) and detaches fk_qc_active_cycle from active_cycle.
        queue_control.active_cycle_id = None
        queue_control.active_beneficiary_id = None
        queue_control.active_cycle_status = None
        queue_control.updated_at = now
        db.flush()

        # Step 2: Safely mark current cycle and current queue entry as COMPLETED.
        # This removes the 'active' state, clearing the singleton active_flag for both tables.
        active_cycle.status = CycleStatus.COMPLETED
        active_cycle.completed_at = now

        curr_queue_entry = (
            db.query(BeneficiaryQueue)
            .filter(BeneficiaryQueue.id == active_cycle.queue_entry_id)
            .with_for_update()
            .first()
        )
        if curr_queue_entry:
            curr_queue_entry.status = QueueStatus.COMPLETED
            curr_queue_entry.completed_at = now
        db.flush()

        # Step 3: Check for next waiting customer in FIFO sequence
        next_waiting = (
            db.query(BeneficiaryQueue)
            .filter(BeneficiaryQueue.status == QueueStatus.WAITING)
            .order_by(BeneficiaryQueue.queue_position.asc())
            .with_for_update()
            .first()
        )

        if next_waiting:
            # Activate next customer (now the single active entry, satisfying uq_queue_active_singleton)
            next_waiting.status = QueueStatus.ACTIVE
            next_waiting.activated_at = now

            # Open their single lifetime cycle (now the single active cycle, satisfying uq_cycles_active_singleton)
            new_cycle = CommissionCycle(
                queue_entry_id=next_waiting.id,
                beneficiary_id=next_waiting.user_id,
                cycle_number=1,
                status=CycleStatus.ACTIVE,
                completed_commissions=0,
                total_earned=Decimal("0.00"),
                started_at=now,
            )
            db.add(new_cycle)
            db.flush()

            # Step 4: Update QueueControl to point to the newly activated cycle
            queue_control.active_cycle_id = new_cycle.id
            queue_control.active_beneficiary_id = next_waiting.user_id
            queue_control.active_cycle_status = CycleStatus.ACTIVE
            queue_control.updated_at = now
            db.flush()

            logger.info(
                f"Queue advanced: customer #{next_waiting.user_id} activated at position #{next_waiting.queue_position} "
                f"(new cycle #{new_cycle.id})."
            )
        else:
            logger.info("Queue rotation completed: no waiting customers in queue. QueueControl remains idle.")

    return seq_comm
