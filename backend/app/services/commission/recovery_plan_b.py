"""Recovery worker sweeping unprocessed Plan B generation commissions (WP-8)."""

from dataclasses import dataclass, field
import logging
import time
from typing import Callable, List, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.billing import BillingEngineClaim, BillingId
from app.models.commission import PlanBCommission
from app.models.enums import Programme
from app.services.commission.plan_b import PlanBCommissionService

logger = logging.getLogger("shopeasy.commission.recovery_plan_b")


@dataclass
class PlanBCommissionRecoveryResult:
    """Structured result of a Plan B commission recovery sweep."""

    candidates_found: int = 0
    orders_processed: int = 0
    commissions_created: int = 0
    already_processed_count: int = 0
    failed_count: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


class PlanBCommissionRecoveryWorker:
    """Batch recovery worker finding and processing unhandled Plan B commissions."""

    @classmethod
    def run_sweep(
        cls,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        batch_size: Optional[int] = None,
    ) -> PlanBCommissionRecoveryResult:
        """Execute a single sweep over unhandled Plan B Billing IDs.

        Guarantees:
        - Independent of synchronous hook success.
        - Bounded candidate discovery query in a short-lived read session.
        - Per-order transaction isolation (failure on one candidate does not abort others).
        - Idempotency protection against concurrent sweepers.
        """
        start_time = time.perf_counter()
        limit = batch_size or 50

        def get_session() -> Session:
            if session_factory is not None:
                return session_factory()
            if db is not None:
                return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
            return SessionLocal()

        # Step 1: Query distinct candidate order IDs having allocated Billing IDs missing generation commissions
        candidate_order_ids: List[int] = []
        read_session = get_session()
        try:
            from sqlalchemy.orm import aliased
            from app.models.order import Order
            from app.models.user import User

            CodeReferrer = aliased(User)
            Purchaser = aliased(User)
            PermReferrer = aliased(User)

            rows = (
                read_session.query(BillingId.order_id)
                .join(Order, Order.id == BillingId.order_id)
                .outerjoin(
                    PlanBCommission,
                    (PlanBCommission.billing_id == BillingId.id) & (PlanBCommission.commission_type == "GENERATION"),
                )
                .outerjoin(CodeReferrer, CodeReferrer.referral_code == Order.applied_referral_code)
                .outerjoin(Purchaser, Purchaser.id == Order.user_id)
                .outerjoin(PermReferrer, PermReferrer.id == Purchaser.referred_by_id)
                .filter(
                    BillingId.status == "ALLOCATED",
                    PlanBCommission.id.is_(None),
                    (BillingId.programme == Programme.PLAN_B) | (CodeReferrer.programme == Programme.PLAN_B) | (PermReferrer.programme == Programme.PLAN_B),
                )
                .distinct()
                .limit(limit)
                .all()
            )
            candidate_order_ids = [r[0] for r in rows]
        except Exception as exc:
            logger.error(f"Error querying pending Plan B commission candidates: {exc}", exc_info=True)
            return PlanBCommissionRecoveryResult(
                candidates_found=0,
                duration_seconds=round(time.perf_counter() - start_time, 4),
                errors=[f"Failed to query candidate order IDs: {exc}"],
            )
        finally:
            read_session.close()

        result = PlanBCommissionRecoveryResult(
            candidates_found=len(candidate_order_ids),
        )

        if not candidate_order_ids:
            result.duration_seconds = round(time.perf_counter() - start_time, 4)
            return result

        logger.info(
            f"Plan B commission recovery sweep found {len(candidate_order_ids)} candidate orders: {candidate_order_ids}"
        )

        # Step 2: Process each candidate order in its own dedicated transaction
        for order_id in candidate_order_ids:
            try:
                exec_res = PlanBCommissionService.process_order_commissions(
                    order_id=order_id,
                    db=db,
                    session_factory=session_factory,
                )
                result.orders_processed += 1
                if exec_res.status == "COMPLETED":
                    result.commissions_created += len(exec_res.generation_commission_ids)
                    if exec_res.direct_net_credited > 0:
                        result.commissions_created += 1
                elif exec_res.status == "ALREADY_PROCESSED":
                    result.already_processed_count += 1
                elif exec_res.status == "FAILED":
                    result.failed_count += 1
                    if exec_res.message:
                        result.errors.append(f"Order #{order_id}: {exec_res.message}")
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(f"Order #{order_id} unhandled exception: {exc}")
                logger.error(f"Plan B commission recovery error on Order #{order_id}: {exc}", exc_info=True)

        result.duration_seconds = round(time.perf_counter() - start_time, 4)
        return result


if __name__ == "__main__":
    import sys
    res = PlanBCommissionRecoveryWorker.run_sweep()
    logger.info(f"Plan B commission recovery sweep completed: {res}")
    sys.exit(0 if res.failed_count == 0 else 1)

