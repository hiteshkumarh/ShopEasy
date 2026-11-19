"""Fulfilment recovery worker domain service for sweeping unfulfilled confirmed orders."""

from dataclasses import dataclass, field
import logging
import time
from typing import Callable, List, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator, FulfilmentResult

logger = logging.getLogger("shopeasy.fulfilment.recovery")


@dataclass
class FulfilmentRecoveryResult:
    """Structured result of a fulfilment recovery sweep."""

    candidates_found: int = 0
    orders_fulfilled: int = 0
    orders_already_fulfilled: int = 0
    orders_ineligible: int = 0
    orders_failed: int = 0
    failed_order_ids: List[int] = field(default_factory=list)
    processed_order_ids: List[int] = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


class FulfilmentRecoveryWorker:
    """Domain service that periodically sweeps and recovers unfulfilled confirmed orders.

    Selection Criteria:
    - order_status == OrderStatus.CONFIRMED
    - payment_status == PaymentStatus.COMPLETED
    - is_fulfilled == False

    Exclusion Rules:
    - Orders in PENDING_PAYMENT, FAILED, CANCELLED, or other states are excluded.
    - Orders where payment_status != COMPLETED (e.g. PENDING, FAILED) are excluded.
    - Orders with is_fulfilled == True are excluded.

    Batch & Concurrency Safety:
    1. Bounded Batch: Queries candidate order IDs up to `batch_size` ordered by ID asc.
       Does NOT load entire entities into a long-lived transaction.
    2. Per-Order Transaction: Each candidate is processed in its own dedicated database session
       via `FulfilmentOrchestrator.fulfil_order(order_id=candidate_id)`.
    3. Row Locking & Idempotency: `FulfilmentOrchestrator` locks the order row (`with_for_update()`)
       and verifies `is_fulfilled`. If another concurrent worker or webhook already fulfilled it,
       it returns `ALREADY_FULFILLED` without error or duplicate records.
    4. Fault Isolation: Failure of one candidate order is logged and recorded in `failed_order_ids`;
       the worker continues processing the remaining candidates.
    5. Clean Cleanup: Sessions are deterministically closed in `finally` blocks.
    """

    @classmethod
    def run_sweep(
        cls,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        batch_size: Optional[int] = None,
    ) -> FulfilmentRecoveryResult:
        """Execute a single recovery sweep over unfulfilled confirmed orders."""
        start_time = time.perf_counter()
        limit = batch_size or settings.FULFILMENT_RECOVERY_BATCH_SIZE

        # Session factory resolution
        def get_session() -> Session:
            if session_factory is not None:
                return session_factory()
            if db is not None:
                return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
            return SessionLocal()

        # Step 1: Query candidate IDs using a short-lived read query
        candidate_ids: List[int] = []
        read_session = get_session()
        try:
            candidates = (
                read_session.query(Order.id)
                .filter(
                    Order.order_status == OrderStatus.CONFIRMED,
                    Order.payment_status == PaymentStatus.COMPLETED,
                    Order.is_fulfilled == False,  # noqa: E712
                )
                .order_by(Order.id.asc())
                .limit(limit)
                .all()
            )
            candidate_ids = [c[0] for c in candidates]
        except Exception as exc:
            logger.error(f"Error querying recovery candidate orders: {exc}", exc_info=True)
            return FulfilmentRecoveryResult(
                candidates_found=0,
                duration_seconds=round(time.perf_counter() - start_time, 4),
                errors=[f"Failed to query candidate orders: {exc}"],
            )
        finally:
            read_session.close()

        result = FulfilmentRecoveryResult(
            candidates_found=len(candidate_ids),
        )

        if not candidate_ids:
            result.duration_seconds = round(time.perf_counter() - start_time, 4)
            return result

        logger.info(
            f"Fulfilment recovery sweep found {len(candidate_ids)} candidate orders: {candidate_ids}"
        )

        # Step 2: Process each candidate in its own dedicated transaction
        for order_id in candidate_ids:
            try:
                # Orchestrator handles locking, idempotency, atomic commit, and rollback
                orch_result: FulfilmentResult = FulfilmentOrchestrator.fulfil_order(
                    order_id=order_id,
                    session_factory=get_session,
                )
                result.processed_order_ids.append(order_id)

                if orch_result.status == "COMPLETED":
                    result.orders_fulfilled += 1
                    logger.info(f"Recovery worker fulfilled order #{order_id}.")
                    from app.services.fulfilment_handoff import dispatch_order_commissions, dispatch_order_cashback
                    dispatch_order_commissions(order_id=order_id, session_factory=get_session)
                    dispatch_order_cashback(order_id=order_id, session_factory=get_session)
                elif orch_result.status == "ALREADY_FULFILLED":
                    result.orders_already_fulfilled += 1
                    logger.info(f"Recovery worker skipped order #{order_id}: already fulfilled.")
                elif orch_result.status == "INELIGIBLE":
                    result.orders_ineligible += 1
                    logger.warning(
                        f"Recovery worker skipped order #{order_id}: ineligible ({orch_result.message})."
                    )
                else:
                    result.orders_failed += 1
                    result.failed_order_ids.append(order_id)
                    result.errors.append(f"Order #{order_id} failed: {orch_result.message}")

            except Exception as exc:
                result.orders_failed += 1
                result.failed_order_ids.append(order_id)
                error_msg = f"Unexpected error fulfilling order #{order_id}: {exc}"
                result.errors.append(error_msg)
                logger.error(error_msg, exc_info=True)

        result.duration_seconds = round(time.perf_counter() - start_time, 4)
        logger.info(
            f"Fulfilment recovery sweep completed in {result.duration_seconds}s: "
            f"{result.orders_fulfilled} fulfilled, {result.orders_already_fulfilled} already fulfilled, "
            f"{result.orders_failed} failed, {result.orders_ineligible} ineligible."
        )
        return result


def main() -> int:
    """CLI entry point for running a fulfilment recovery sweep.

    Returns:
      0 - Sweep completed successfully with no failed orders and no sweep errors.
      1 - One or more orders failed or a sweep-level error (e.g. database query error) occurred.
    """
    logging.basicConfig(level=logging.INFO)
    logger.info("Executing ShopEasy fulfilment recovery sweep via CLI...")
    res = FulfilmentRecoveryWorker.run_sweep()
    logger.info(
        f"Sweep completed in {res.duration_seconds}s: "
        f"{res.orders_fulfilled} fulfilled, {res.orders_already_fulfilled} already fulfilled, "
        f"{res.orders_failed} failed, {len(res.errors)} sweep errors."
    )
    if res.errors:
        for err in res.errors:
            logger.error(f"Sweep error: {err}")
    return 1 if res.orders_failed > 0 or res.errors else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
