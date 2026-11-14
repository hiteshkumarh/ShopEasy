"""Billing ID allocator service coordinating atomic sequence generation and per-unit Billing ID creation."""

import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.billing import BillingCounter, BillingId
from app.models.enums import OrderStatus, PaymentStatus, Programme
from app.models.order import Order, OrderItem
from app.models.user import User

logger = logging.getLogger("shopeasy.billing.allocator")

DEFAULT_SEQUENCE_NAME = "GLOBAL_BILLING_ID"
DEFAULT_BILLING_PREFIX = "AGD"
DEFAULT_PADDING = 6


class BillingAllocationError(Exception):
    """Base exception for billing allocation errors."""
    pass


class IneligibleOrderError(BillingAllocationError):
    """Raised when an order is not in confirmed and payment-completed status."""
    pass


class MissingBillingCounterError(BillingAllocationError):
    """Raised when the required billing sequence counter row does not exist."""
    pass


class InvalidOrderItemsError(BillingAllocationError):
    """Raised when an order has no valid items or non-positive quantities."""
    pass


class ProgrammeResolutionError(BillingAllocationError):
    """Raised when an order's customer programme cannot be determined."""
    pass


class BillingAllocatorService:
    """Service providing atomic, contiguous, database-backed Billing ID sequence allocation."""

    @staticmethod
    def format_billing_number(
        seq_num: int,
        prefix: str = DEFAULT_BILLING_PREFIX,
        padding: int = DEFAULT_PADDING,
    ) -> str:
        """Format a numeric sequence number into a standard Billing ID string (e.g. AGD-000201)."""
        return f"{prefix}-{seq_num:0{padding}d}"

    @classmethod
    def allocate_for_order(
        cls,
        db: Session,
        order: Order,
        sequence_name: str = DEFAULT_SEQUENCE_NAME,
        prefix: str = DEFAULT_BILLING_PREFIX,
        padding: int = DEFAULT_PADDING,
    ) -> List[BillingId]:
        """Allocate exactly one unique Billing ID for each individual purchased product unit in the order.

        Transaction Ownership:
        - This service is transaction-neutral: it queries and updates rows within the caller's active
          session/transaction and flushes changes (`db.flush()`), but NEVER commits or rolls back.
        - The caller retains full ownership of `db.commit()` and `db.rollback()`.
        - If an exception is raised, the session is left uncommitted so the caller can safely roll back.

        Allocation Rules:
        1. Order must be CONFIRMED and payment status must be COMPLETED.
        2. Idempotent: If all units are already allocated, existing Billing IDs are returned without duplicates.
        3. If some units are already allocated, only the missing units are allocated without duplicating existing ones.
        4. Atomically locks the BillingCounter row via `SELECT ... FOR UPDATE` in RDBMS (e.g. MySQL) to guarantee
           contiguous, collision-free sequence numbers under concurrent sessions.
        5. For each order item of quantity N, units are assigned unit_index 1..N.
        """
        # 1. Eligibility validation
        if order.order_status != OrderStatus.CONFIRMED or order.payment_status != PaymentStatus.COMPLETED:
            raise IneligibleOrderError(
                f"Order #{order.id} is ineligible for Billing ID allocation. "
                f"Requires order_status='{OrderStatus.CONFIRMED}' and payment_status='{PaymentStatus.COMPLETED}', "
                f"got order_status='{order.order_status}' and payment_status='{order.payment_status}'."
            )

        # 2. Programme resolution
        programme = None
        if hasattr(order, "user") and order.user is not None and hasattr(order.user, "programme"):
            programme = order.user.programme
        if programme is None:
            user_prog = db.query(User.programme).filter(User.id == order.user_id).scalar()
            if user_prog is not None:
                programme = user_prog

        if programme not in (Programme.PLAN_A, Programme.PLAN_B, Programme.LEGACY):
            raise ProgrammeResolutionError(
                f"Cannot determine valid programme for customer #{order.user_id} on order #{order.id}."
            )

        # 3. Validate order items
        order_items = order.order_items
        if not order_items:
            order_items = (
                db.query(OrderItem)
                .filter(OrderItem.order_id == order.id)
                .order_by(OrderItem.id.asc())
                .all()
            )
        if not order_items:
            raise InvalidOrderItemsError(f"Order #{order.id} has no order items to allocate Billing IDs for.")

        for item in order_items:
            if item.quantity <= 0:
                raise InvalidOrderItemsError(
                    f"OrderItem #{item.id} has invalid non-positive quantity: {item.quantity}."
                )

        # 4. Check existing allocations for idempotency
        existing_allocations = (
            db.query(BillingId)
            .filter(BillingId.order_id == order.id)
            .order_by(BillingId.sequence_number.asc())
            .all()
        )
        allocated_units = {
            (b.order_item_id, b.unit_index) for b in existing_allocations
        }

        # Identify which item units still need allocation
        units_to_allocate: List[Tuple[OrderItem, int]] = []
        for item in order_items:
            for u_idx in range(1, item.quantity + 1):
                if (item.id, u_idx) not in allocated_units:
                    units_to_allocate.append((item, u_idx))

        if not units_to_allocate:
            logger.info(
                f"Order #{order.id} already has all {len(existing_allocations)} Billing IDs allocated. "
                "Returning existing records idempotently."
            )
            return existing_allocations

        needed_count = len(units_to_allocate)

        # 5. Lock BillingCounter and allocate contiguous range
        counter = (
            db.query(BillingCounter)
            .filter(BillingCounter.sequence_name == sequence_name)
            .with_for_update()
            .first()
        )
        if not counter:
            raise MissingBillingCounterError(
                f"Required billing counter sequence '{sequence_name}' not found. "
                "Ensure Alembic migration seeding has completed."
            )

        start_seq = counter.current_value
        end_seq = start_seq + needed_count
        counter.current_value = end_seq

        # 6. Instantiate BillingId records
        new_billing_ids: List[BillingId] = []
        current_seq = start_seq
        for item, u_idx in units_to_allocate:
            current_seq += 1
            b_number = cls.format_billing_number(current_seq, prefix=prefix, padding=padding)
            b_id = BillingId(
                billing_number=b_number,
                sequence_number=current_seq,
                order_id=order.id,
                order_item_id=item.id,
                unit_index=u_idx,
                user_id=order.user_id,
                product_id=item.product_id,
                programme=programme,
                status="ALLOCATED",
            )
            db.add(b_id)
            new_billing_ids.append(b_id)

        # Flush to check DB constraints and assign primary keys without committing
        db.flush()

        logger.info(
            f"Allocated {needed_count} Billing IDs for order #{order.id} "
            f"(sequences {start_seq + 1}..{end_seq}, numbers {new_billing_ids[0].billing_number}.."
            f"{new_billing_ids[-1].billing_number})."
        )

        # Return full ordered list of Billing IDs for this order
        all_order_billing_ids = (
            db.query(BillingId)
            .filter(BillingId.order_id == order.id)
            .order_by(BillingId.sequence_number.asc())
            .all()
        )
        return all_order_billing_ids
