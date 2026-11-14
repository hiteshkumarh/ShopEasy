"""Fulfilment handoff dispatcher hook connecting WP-5 payments to WP-6 fulfilment."""

import logging
from typing import Callable, Optional
from sqlalchemy.orm import Session

from app.services.fulfilment.orchestrator import FulfilmentOrchestrator, FulfilmentResult

logger = logging.getLogger("shopeasy.fulfilment_handoff")


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
    return result
