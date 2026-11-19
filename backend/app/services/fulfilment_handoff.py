"""Fulfilment handoff dispatcher hook connecting WP-5 payments to WP-6 fulfilment."""

import logging
from typing import Callable, Optional
from sqlalchemy.orm import Session

from app.services.fulfilment.orchestrator import FulfilmentOrchestrator, FulfilmentResult

logger = logging.getLogger("shopeasy.fulfilment_handoff")


def dispatch_order_commissions(
    order_id: int,
    db: Optional[Session] = None,
    session_factory: Optional[Callable[[], Session]] = None,
) -> None:
    """Post-fulfilment synchronous dispatch hook for Plan A and Plan B commissions (WP-7, WP-8).

    Enforces Programme Routing Isolation:
    - If the order's referrer (via applied_referral_code or purchaser.referred_by_id) belongs to Plan B,
      dispatches exclusively to PlanBCommissionService.
    - Otherwise, dispatches exclusively to PlanACommissionService.
    - Never executes both engines for the same order.
    """
    try:
        from app.models.enums import Programme
        from app.models.order import Order
        from app.models.user import User
        from app.services.commission.plan_a import PlanACommissionService
        from app.services.commission.plan_b import PlanBCommissionService

        # Derive a read-only session to check the referrer's programme
        if session_factory is not None:
            read_session = session_factory()
        elif db is not None:
            from sqlalchemy.orm import sessionmaker
            read_session = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
        else:
            from app.core.database import SessionLocal
            read_session = SessionLocal()

        referrer_programme: Optional[Programme] = None
        try:
            order = read_session.query(Order).filter(Order.id == order_id).first()
            if order:
                # 1. Check applied referral code on the order
                if order.applied_referral_code and order.applied_referral_code.strip():
                    ref_user = (
                        read_session.query(User)
                        .filter(User.referral_code == order.applied_referral_code.strip().upper())
                        .first()
                    )
                    if ref_user:
                        referrer_programme = ref_user.programme

                # 2. Check purchaser's permanent referred_by_id if not resolved
                if referrer_programme is None and order.user_id:
                    purchaser = read_session.query(User).filter(User.id == order.user_id).first()
                    if purchaser and purchaser.referred_by_id:
                        perm_ref = read_session.query(User).filter(User.id == purchaser.referred_by_id).first()
                        if perm_ref:
                            referrer_programme = perm_ref.programme
        finally:
            read_session.close()

        # Exclusive programme routing
        if referrer_programme == Programme.PLAN_B:
            logger.info(
                f"Order #{order_id} has Plan B referrer. Routing exclusively to PlanBCommissionService."
            )
            PlanBCommissionService.process_order_commissions(
                order_id=order_id,
                db=db,
                session_factory=session_factory,
            )
        else:
            logger.info(
                f"Order #{order_id} has {referrer_programme or 'no'} referrer. Routing to PlanACommissionService."
            )
            PlanACommissionService.process_order_commissions(
                order_id=order_id,
                db=db,
                session_factory=session_factory,
            )
    except Exception as exc:
        logger.error(f"Post-fulfilment commission dispatch error on order #{order_id}: {exc}", exc_info=True)
        if db is not None:
            try:
                from app.models.enums import Programme
                from app.models.order import Order
                from app.models.user import User
                from app.services.notification_service import (
                    NotificationEvent,
                    NotificationService,
                )
                order = db.query(Order).filter(Order.id == order_id).first()
                if order:
                    order_user = db.query(User).filter(User.id == order.user_id).first()
                    if order_user and order_user.programme == Programme.PLAN_A:
                        NotificationService.emit_admin_notification(
                            db=db,
                            programme=Programme.PLAN_A,
                            event_type=NotificationEvent.PA_ADMIN_TRANSACTION_FAILURE,
                            title="Transaction Failure Alert",
                            message=f"Commission dispatch failure on Plan A order #{order.id}: {exc}.",
                            reference_type="order",
                            reference_id=order.id,
                        )
            except Exception:
                pass


def dispatch_order_cashback(
    order_id: int,
    db: Optional[Session] = None,
    session_factory: Optional[Callable[[], Session]] = None,
) -> None:
    """Post-fulfilment synchronous dispatch hook for Plan A cashback allocations (WP-10)."""
    try:
        from app.services.cashback.plan_a import PlanACashbackService

        # Dispatch Plan A cashback (only executes for Plan A Billing IDs)
        PlanACashbackService.process_order_cashback(
            order_id=order_id,
            db=db,
            session_factory=session_factory,
        )
    except Exception as exc:
        logger.error(f"Post-fulfilment cashback dispatch error on order #{order_id}: {exc}", exc_info=True)
        if db is not None:
            try:
                from app.models.enums import Programme
                from app.models.order import Order
                from app.models.user import User
                from app.services.notification_service import (
                    NotificationEvent,
                    NotificationService,
                )
                order = db.query(Order).filter(Order.id == order_id).first()
                if order:
                    order_user = db.query(User).filter(User.id == order.user_id).first()
                    if order_user and order_user.programme == Programme.PLAN_A:
                        NotificationService.emit_admin_notification(
                            db=db,
                            programme=Programme.PLAN_A,
                            event_type=NotificationEvent.PA_ADMIN_TRANSACTION_FAILURE,
                            title="Transaction Failure Alert",
                            message=f"Cashback dispatch failure on Plan A order #{order.id}: {exc}.",
                            reference_type="order",
                            reference_id=order.id,
                        )
            except Exception:
                pass


def dispatch_order_fulfilment(
    order_id: int,
    db: Optional[Session] = None,
    session_factory: Optional[Callable[[], Session]] = None,
) -> FulfilmentResult:
    """Synchronous handoff hook triggered after payment confirmation is durably committed.

    WP-5 responsibility: Commit order with order_status='confirmed' and payment_status='completed',
    then trigger this hook.
    WP-6 responsibility: Billing ID allocation, engine claims, and order fulfilment state.

    Transaction Ownership Architecture:
    - This function executes in its own dedicated transaction boundary via FulfilmentOrchestrator.
    - If `db` is provided, the orchestrator derives an isolated dedicated session bound to the same engine,
      strictly ensuring that caller-owned `db` is NEVER committed, rolled back, or closed.
    - If `db` is None and `session_factory` is None, `SessionLocal()` is used.
    - Payment confirmation is committed prior to invoking this hook. A failure during fulfilment
      rolls back uncommitted fulfilment mutations (Billing IDs, claims) without undoing the committed payment.
    - If a crash occurs after commit but before/during handoff, the order remains durably saved
      in the database and the WP-6 recovery worker sweeps unfulfilled confirmed orders.
    """
    logger.info(
        f"Order #{order_id} confirmed. Dispatching to FulfilmentOrchestrator."
    )
    result = FulfilmentOrchestrator.fulfil_order(
        order_id=order_id,
        db=db,
        session_factory=session_factory,
    )
    logger.info(
        f"Fulfilment handoff for order #{order_id} completed with status: {result.status}."
    )
    if result.status in ("COMPLETED", "ALREADY_FULFILLED"):
        dispatch_order_commissions(order_id=order_id, db=db, session_factory=session_factory)
        dispatch_order_cashback(order_id=order_id, db=db, session_factory=session_factory)
    return result
