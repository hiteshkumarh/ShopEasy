"""Recovery worker sweeping unprocessed Plan A cashback allocations (WP-10)."""

from dataclasses import dataclass, field
import logging
import time
from typing import Callable, List, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.billing import BillingEngineClaim, BillingId
from app.models.cashback import PlanACashbackContribution, PlanAUnallocatedCashbackReserve
from app.models.enums import Programme
from app.services.cashback.plan_a import PlanACashbackService

logger = logging.getLogger("shopeasy.cashback.recovery_plan_a")


@dataclass
class PlanACashbackRecoveryResult:
    """Structured result of a cashback recovery sweep."""

    candidates_found: int = 0
    processed_count: int = 0
    contributed_count: int = 0
    reserved_initial_count: int = 0
    reserved_recipient_count: int = 0
    skipped_repeat_count: int = 0
    already_processed_count: int = 0
    failed_count: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


class PlanACashbackRecoveryWorker:
    """Batch recovery worker finding and processing unhandled Plan A cashback contributions."""

    @classmethod
    def run_sweep(
        cls,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        batch_size: Optional[int] = None,
    ) -> PlanACashbackRecoveryResult:
        """Execute a single sweep over unhandled Plan A Billing IDs.

        Guarantees:
        - Independent of synchronous hook success.
        - Bounded candidate discovery query in a short-lived read session.
        - Avoids changing shared BillingEngineClaim.status or processed_at.
        - Per-item transaction isolation (failure on one candidate does not abort others).
        - Safe row locking and idempotency protection against concurrent sweepers.
        """
        start_time = time.perf_counter()
        limit = batch_size or 50

        def get_session() -> Session:
            if session_factory is not None:
                return session_factory()
            if db is not None:
                return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
            return SessionLocal()

        # Step 1: Query candidate Billing IDs missing both contribution and reserve records
        candidate_bids: List[int] = []
        read_session = get_session()
        try:
            rows = (
                read_session.query(BillingId.id)
                .join(BillingEngineClaim, BillingEngineClaim.billing_id == BillingId.id)
                .outerjoin(PlanACashbackContribution, PlanACashbackContribution.contributing_billing_id == BillingId.id)
                .outerjoin(PlanAUnallocatedCashbackReserve, PlanAUnallocatedCashbackReserve.billing_id == BillingId.id)
                .filter(
                    BillingId.programme == Programme.PLAN_A,
                    BillingEngineClaim.engine == Programme.PLAN_A,
                    PlanACashbackContribution.id.is_(None),
                    PlanAUnallocatedCashbackReserve.id.is_(None),
                )
                .order_by(BillingId.sequence_number.asc())
                .limit(limit)
                .all()
            )
            candidate_bids = [r[0] for r in rows]
        except Exception as exc:
            logger.error(f"Error querying pending cashback candidates: {exc}", exc_info=True)
            return PlanACashbackRecoveryResult(
                candidates_found=0,
                duration_seconds=round(time.perf_counter() - start_time, 4),
                errors=[f"Failed to query candidate billing IDs: {exc}"],
            )
        finally:
            read_session.close()

        result = PlanACashbackRecoveryResult(
            candidates_found=len(candidate_bids),
        )

        if not candidate_bids:
            result.duration_seconds = round(time.perf_counter() - start_time, 4)
            return result

        logger.info(
            f"Plan A cashback recovery sweep found {len(candidate_bids)} candidates: {candidate_bids}"
        )

        # Step 2: Process each candidate individually
        for bid_id in candidate_bids:
            try:
                exec_result = PlanACashbackService.process_billing_id(
                    billing_id=bid_id,
                    db=db,
                    session_factory=session_factory,
                )
                result.processed_count += 1
                if exec_result.status == "CONTRIBUTED":
                    result.contributed_count += 1
                elif exec_result.status == "RESERVED_INITIAL_QUEUE":
                    result.reserved_initial_count += 1
                elif exec_result.status == "RESERVED_RECIPIENT_PURCHASE":
                    result.reserved_recipient_count += 1
                elif exec_result.status == "SKIPPED_REPEAT_PURCHASE":
                    result.skipped_repeat_count += 1
                elif exec_result.status == "ALREADY_PROCESSED":
                    result.already_processed_count += 1
                elif exec_result.status == "FAILED":
                    result.failed_count += 1
                    if exec_result.message:
                        result.errors.append(f"BID #{bid_id}: {exec_result.message}")
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(f"BID #{bid_id}: {str(exc)}")
                logger.error(f"Recovery failed for Billing ID #{bid_id}: {exc}", exc_info=True)

        result.duration_seconds = round(time.perf_counter() - start_time, 4)
        logger.info(
            f"Plan A cashback recovery sweep completed in {result.duration_seconds}s. "
            f"Processed: {result.processed_count}, Contributed: {result.contributed_count}, "
            f"Reserved Initial: {result.reserved_initial_count}, Reserved Recipient: {result.reserved_recipient_count}, "
            f"Skipped Repeat: {result.skipped_repeat_count}, Failed: {result.failed_count}"
        )
        return result

