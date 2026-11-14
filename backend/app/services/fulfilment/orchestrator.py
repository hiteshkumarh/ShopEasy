"""Fulfilment orchestrator coordinating atomic Billing ID allocation, engine claims, and order fulfilment."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Callable, List, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.billing import BillingEngineClaim, BillingId
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.services.billing.allocator import BillingAllocatorService

logger = logging.getLogger("shopeasy.fulfilment.orchestrator")


@dataclass
class FulfilmentResult:
    """Structured result of an order fulfilment attempt."""

    status: str  # "COMPLETED", "ALREADY_FULFILLED", "INELIGIBLE", "FAILED"
    order_id: int
    order_number: Optional[str] = None
    billing_id_count: int = 0
    billing_numbers: List[str] = field(default_factory=list)
    engine_claim_count: int = 0
    message: Optional[str] = None


class FulfilmentOrchestrator:
    """Domain service orchestrating post-payment order fulfilment.

    Responsibilities:
    1. Lock and inspect Order eligibility (`order_status == CONFIRMED` and `payment_status == COMPLETED`).
    2. Enforce idempotency: skip already-fulfilled orders without duplicating rows.
    3. Allocate Billing IDs via `BillingAllocatorService` (1 ID per purchased product unit).
    4. Create exactly one `BillingEngineClaim` per Billing ID, strictly matching `BillingId.programme`.
    5. Atomically transition `order.is_fulfilled = True` and set `order.fulfilled_at = now`.
    6. Commit all fulfilment records together in a single atomic database transaction.
    """

    @classmethod
    def fulfil_order(
        cls,
        order_id: int,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> FulfilmentResult:
        """Execute atomic post-payment fulfilment for a confirmed order.

        Transaction Ownership Architecture:
        - The fulfilment transaction has ONE explicit owner: a dedicated session created
          specifically for fulfilment.
        - The orchestrator NEVER calls `db.commit()` or `db.rollback()` on a caller-owned `db` session.
        - If `session_factory` is provided, the dedicated session is instantiated via `session_factory()`.
        - If `db` is provided (e.g. caller session from payment service or test fixtures), the orchestrator
          derives a dedicated session bound to `db.get_bind()`. The caller-owned `db` session is left untouched,
          so pending uncommitted changes in `db` are neither committed nor discarded.
        - If neither is provided, `SessionLocal()` is instantiated.
        - All fulfilment modifications (locking order, sequence counter increment, BillingId allocation,
          BillingEngineClaim creation, and order fulfilment state transition) happen in the dedicated session
          and commit together atomically.
        - On any failure, the dedicated session rolls back, cleanly discarding all uncommitted fulfilment
          mutations, and the dedicated session is closed in `finally`.
        """
        # 1. Resolve dedicated fulfilment session
        if session_factory is not None:
            fulfilment_db = session_factory()
        elif db is not None:
            fulfilment_db = sessionmaker(
                bind=db.get_bind(),
                autocommit=False,
                autoflush=False,
            )()
        else:
            fulfilment_db = SessionLocal()

        try:
            # 2. Lock Order row (Hierarchy Level 1)
            order = (
                fulfilment_db.query(Order)
                .filter(Order.id == order_id)
                .with_for_update()
                .first()
            )
            if not order:
                logger.warning(f"Fulfilment attempted for non-existent order #{order_id}.")
                return FulfilmentResult(
                    status="INELIGIBLE",
                    order_id=order_id,
                    message=f"Order #{order_id} does not exist.",
                )

            # 3. Check if already fulfilled (Idempotency)
            if order.is_fulfilled:
                existing_bids = (
                    fulfilment_db.query(BillingId)
                    .filter(BillingId.order_id == order.id)
                    .order_by(BillingId.sequence_number.asc())
                    .all()
                )
                existing_claims = (
                    fulfilment_db.query(BillingEngineClaim)
                    .join(BillingId, BillingEngineClaim.billing_id == BillingId.id)
                    .filter(BillingId.order_id == order.id)
                    .all()
                )
                logger.info(
                    f"Order #{order.id} is already fulfilled. Returning existing {len(existing_bids)} Billing IDs."
                )
                return FulfilmentResult(
                    status="ALREADY_FULFILLED",
                    order_id=order.id,
                    order_number=order.order_number,
                    billing_id_count=len(existing_bids),
                    billing_numbers=[b.billing_number for b in existing_bids],
                    engine_claim_count=len(existing_claims),
                    message="Order was already fulfilled.",
                )

            # 4. Check Eligibility: must be CONFIRMED and COMPLETED
            if order.order_status != OrderStatus.CONFIRMED or order.payment_status != PaymentStatus.COMPLETED:
                logger.warning(
                    f"Order #{order.id} is ineligible for fulfilment: "
                    f"order_status='{order.order_status}', payment_status='{order.payment_status}'."
                )
                return FulfilmentResult(
                    status="INELIGIBLE",
                    order_id=order.id,
                    order_number=order.order_number,
                    message=(
                        f"Order #{order.id} is ineligible for fulfilment. "
                        f"Requires order_status='{OrderStatus.CONFIRMED}' and payment_status='{PaymentStatus.COMPLETED}', "
                        f"got order_status='{order.order_status}' and payment_status='{order.payment_status}'."
                    ),
                )

            # 5. Invoke BillingAllocatorService to allocate Billing IDs
            # BillingAllocatorService is transaction-neutral (flushes without committing)
            billing_ids = BillingAllocatorService.allocate_for_order(db=fulfilment_db, order=order)

            # 6. Create BillingEngineClaim for each Billing ID
            # Rule: Exactly one claim per Billing ID; claim.engine must strictly equal billing_id.programme
            created_claims = []
            for b_id in billing_ids:
                existing_claim = (
                    fulfilment_db.query(BillingEngineClaim)
                    .filter(BillingEngineClaim.billing_id == b_id.id)
                    .first()
                )
                if existing_claim is None:
                    claim = BillingEngineClaim(
                        billing_id=b_id.id,
                        engine=b_id.programme,
                        status="PENDING",
                    )
                    fulfilment_db.add(claim)
                    created_claims.append(claim)
                else:
                    if existing_claim.engine != b_id.programme:
                        raise ValueError(
                            f"Claim engine '{existing_claim.engine}' does not match "
                            f"BillingId programme '{b_id.programme}' for billing_id #{b_id.id}."
                        )
                    created_claims.append(existing_claim)

            # Flush claims to verify uniqueness and constraints
            fulfilment_db.flush()

            # 7. Mark order fulfilled only after all Billing IDs and claims exist
            now = datetime.now(timezone.utc)
            order.is_fulfilled = True
            order.fulfilled_at = now
            fulfilment_db.flush()

            # 8. Commit atomic fulfilment transaction
            fulfilment_db.commit()

            logger.info(
                f"Successfully fulfilled order #{order.id} ({order.order_number}): "
                f"{len(billing_ids)} Billing IDs and {len(created_claims)} engine claims created."
            )

            return FulfilmentResult(
                status="COMPLETED",
                order_id=order.id,
                order_number=order.order_number,
                billing_id_count=len(billing_ids),
                billing_numbers=[b.billing_number for b in billing_ids],
                engine_claim_count=len(created_claims),
                message="Order fulfilment completed successfully.",
            )

        except Exception as exc:
            fulfilment_db.rollback()
            logger.error(f"Error fulfilling order #{order_id}: {exc}", exc_info=True)
            raise
        finally:
            fulfilment_db.close()
