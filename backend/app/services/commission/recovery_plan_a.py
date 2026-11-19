"""Recovery worker sweeping unprocessed Plan A commissions (WP-7)."""

from dataclasses import dataclass, field
import logging
import time
from typing import Callable, List, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.billing import BillingEngineClaim, BillingId
from app.models.commission import PlanACommission
from app.models.enums import Programme
from app.services.commission.plan_a import PlanACommissionService

logger = logging.getLogger("shopeasy.commission.recovery_plan_a")


@dataclass
class PlanACommissionRecoveryResult:
    """Structured result of a commission recovery sweep."""

    candidates_found: int = 0
    processed_count: int = 0
    earned_count: int = 0
    unallocated_count: int = 0
    ineligible_count: int = 0
    already_processed_count: int = 0
    failed_count: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


class PlanACommissionRecoveryWorker:
    """Batch recovery worker finding and processing unhandled Plan A commissions."""

    @classmethod
    def run_sweep(
        cls,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        batch_size: Optional[int] = None,
    ) -> PlanACommissionRecoveryResult:
        """Execute a single sweep over unhandled Plan A Billing IDs.

        Guarantees:
        - Independent of synchronous hook success.
        - Bounded candidate discovery query in a short-lived read session.
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

        # Step 1: Query candidate Billing IDs missing a PlanACommission record
        candidate_bids: List[int] = []
        read_session = get_session()
        try:
            rows = (
                read_session.query(BillingId.id)
                .join(BillingEngineClaim, BillingEngineClaim.billing_id == BillingId.id)
                .outerjoin(PlanACommission, PlanACommission.billing_id == BillingId.id)
                .filter(
                    BillingId.programme == Programme.PLAN_A,
                    BillingEngineClaim.engine == Programme.PLAN_A,
                    PlanACommission.id.is_(None),
                )
                .order_by(BillingId.sequence_number.asc())
                .limit(limit)
                .all()
            )
            candidate_bids = [r[0] for r in rows]
        except Exception as exc:
            logger.error(f"Error querying pending commission candidates: {exc}", exc_info=True)
            return PlanACommissionRecoveryResult(
                candidates_found=0,
                duration_seconds=round(time.perf_counter() - start_time, 4),
                errors=[f"Failed to query candidate billing IDs: {exc}"],
            )
        finally:
            read_session.close()

        result = PlanACommissionRecoveryResult(
            candidates_found=len(candidate_bids),
        )

        if not candidate_bids:
            result.duration_seconds = round(time.perf_counter() - start_time, 4)
            return result

        logger.info(
            f"Plan A commission recovery sweep found {len(candidate_bids)} candidates: {candidate_bids}"
        )

        # Step 2: Process each candidate in its own dedicated transaction
        for bid in candidate_bids:
            try:
                exec_res = PlanACommissionService.process_billing_id(
                    billing_id=bid,
                    db=db,
                    session_factory=session_factory,
                )
                result.processed_count += 1
                if exec_res.status == "EARNED":
                    result.earned_count += 1
                elif exec_res.status == "UNALLOCATED_NO_REFERRER":
                    result.unallocated_count += 1
                elif exec_res.status == "INELIGIBLE_REFERRER":
                    result.ineligible_count += 1
                elif exec_res.status == "ALREADY_PROCESSED":
                    result.already_processed_count += 1
                elif exec_res.status == "FAILED":
                    result.failed_count += 1
                    if exec_res.message:
                        result.errors.append(f"BillingId #{bid}: {exec_res.message}")
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(f"BillingId #{bid} unhandled exception: {exc}")
                logger.error(f"Commission recovery error on BillingId #{bid}: {exc}", exc_info=True)

        result.duration_seconds = round(time.perf_counter() - start_time, 4)
        return result


if __name__ == "__main__":
    import sys
    res = PlanACommissionRecoveryWorker.run_sweep()
    logger.info(f"Commission recovery sweep completed: {res}")
    sys.exit(0 if res.failed_count == 0 else 1)

