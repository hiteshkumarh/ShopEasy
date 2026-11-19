"""Notification service managing in-dashboard alerts for Arya Global Digital (WP-11).

Enforces the exact PRD / confirmed R-10 notification matrix:

Plan A Events:
  1. Admin: Cashback cycle completed (PA_ADMIN_CASHBACK_CYCLE_COMPLETED).
  2. Admin: Cashback withdrawal requested (PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED).
  3. Admin: Important transaction failure (PA_ADMIN_TRANSACTION_FAILURE).

Plan B Events:
  1. Distributor: Order delivered (PB_DISTRIBUTOR_ORDER_DELIVERED).
  2. Admin: Blocked distributor withdrawal requested (PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED).
  3. Distributor: Wallet unfrozen (PB_DISTRIBUTOR_WALLET_UNFROZEN).
  4. Distributor: Successful withdrawal payout (PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS).

Prohibited Events (Rejected by service):
  - No SMS, email, WhatsApp, or external webhooks.
  - No customer SMS/email notifications.
  - No Plan B commission credit or ₹500/₹50 notifications.
  - No admin notifications for failed Plan B payments, orders, or registrations.

Invariants:
- Uses existing Notification model (app.models.notification.Notification).
- Operates within caller's transaction without independent commit.
- Idempotency / duplicate suppression: will not emit duplicate alerts for the same event and entity reference.
"""

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import List, Optional, Union

from sqlalchemy.orm import Session

from app.models.enums import Programme, UserRole
from app.models.notification import Notification
from app.models.order import Order
from app.models.user import User

logger = logging.getLogger("shopeasy.notifications")


class NotificationEvent(str, Enum):
    """Authoritative whitelist of permitted in-dashboard notification events (R-10)."""

    # Plan A Events (Admin recipients)
    PA_ADMIN_CASHBACK_CYCLE_COMPLETED = "PA_ADMIN_CASHBACK_CYCLE_COMPLETED"
    PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED = "PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED"
    PA_ADMIN_TRANSACTION_FAILURE = "PA_ADMIN_TRANSACTION_FAILURE"

    # Plan B Events
    PB_DISTRIBUTOR_ORDER_DELIVERED = "PB_DISTRIBUTOR_ORDER_DELIVERED"
    PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED = "PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED"
    PB_DISTRIBUTOR_WALLET_UNFROZEN = "PB_DISTRIBUTOR_WALLET_UNFROZEN"
    PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS = "PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS"


class NotificationService:
    """Service for emitting and managing in-dashboard notifications."""

    @classmethod
    def emit_notification(
        cls,
        db: Session,
        user_id: int,
        programme: Programme,
        event_type: Union[NotificationEvent, str],
        title: str,
        message: str,
        reference_type: Optional[str] = None,
        reference_id: Optional[Union[int, str]] = None,
    ) -> Notification:
        """Emit an in-dashboard notification adhering strictly to R-10 rules.

        Args:
            db: Active database session (uncommitted).
            user_id: Recipient user ID (administrator or distributor).
            programme: Scoping programme (Programme.PLAN_A or Programme.PLAN_B).
            event_type: Permitted NotificationEvent member.
            title: Short notification title.
            message: Full notification content.
            reference_type: Optional source entity type (e.g. "cycle", "withdrawal", "order").
            reference_id: Optional source entity ID.

        Raises:
            ValueError: If event_type is not in the permitted whitelist or violates programme boundaries.

        Returns:
            Created Notification entity (flushed, uncommitted).
        """
        # Validate event is permitted
        if isinstance(event_type, NotificationEvent):
            event_str = event_type.value
        else:
            try:
                event_str = NotificationEvent(str(event_type)).value
            except ValueError:
                raise ValueError(
                    f"Prohibited or invalid notification event: '{event_type}'. "
                    f"Only the 7 explicitly confirmed R-10 in-dashboard events are allowed."
                )

        # Enforce programme alignment
        if event_str.startswith("PA_") and programme != Programme.PLAN_A:
            raise ValueError(f"Event '{event_str}' belongs to Plan A, but programme '{programme.value}' was specified.")
        if event_str.startswith("PB_") and programme != Programme.PLAN_B:
            raise ValueError(f"Event '{event_str}' belongs to Plan B, but programme '{programme.value}' was specified.")

        ref_id_str = str(reference_id).strip() if reference_id is not None else None
        ref_type_str = reference_type.strip() if reference_type else None

        # Duplicate suppression: prevent duplicate alert for identical user, event, and reference
        if ref_type_str and ref_id_str:
            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user_id,
                    Notification.event_type == event_str,
                    Notification.reference_type == ref_type_str,
                    Notification.reference_id == ref_id_str,
                )
                .first()
            )
            if existing:
                logger.info(
                    f"Duplicate notification suppressed for user #{user_id}, event '{event_str}', "
                    f"ref={ref_type_str}#{ref_id_str}. Existing notification #{existing.id} returned."
                )
                return existing

        notification = Notification(
            user_id=user_id,
            programme=programme,
            event_type=event_str,
            title=title.strip(),
            message=message.strip(),
            reference_type=ref_type_str,
            reference_id=ref_id_str,
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )

        db.add(notification)
        db.flush()

        logger.info(
            f"Notification emitted: id=#{notification.id}, user=#{user_id}, prog={programme.value}, event='{event_str}'"
        )
        return notification

    @classmethod
    def emit_admin_notification(
        cls,
        db: Session,
        programme: Programme,
        event_type: Union[NotificationEvent, str],
        title: str,
        message: str,
        reference_type: Optional[str] = None,
        reference_id: Optional[Union[int, str]] = None,
        admin_id: Optional[int] = None,
    ) -> List[Notification]:
        """Emit notification to active administrators within caller's transaction.

        Args:
            db: Active database session (uncommitted).
            programme: Scoping programme (Programme.PLAN_A or Programme.PLAN_B).
            event_type: Permitted NotificationEvent member.
            title: Short notification title.
            message: Full notification content.
            reference_type: Optional source entity type (e.g. "cycle", "withdrawal", "order").
            reference_id: Optional source entity ID.
            admin_id: Optional specific administrator ID to notify. If omitted, all active
                      administrators are resolved from the database.

        Returns:
            List of created Notification entities (flushed, uncommitted).
        """
        if admin_id is not None:
            admins = (
                db.query(User)
                .filter(User.id == admin_id, User.role == UserRole.ADMIN, User.is_active == True)
                .all()
            )
        else:
            admins = (
                db.query(User)
                .filter(User.role == UserRole.ADMIN, User.is_active == True)
                .all()
            )

        if not admins:
            logger.warning(
                f"No active administrator found to receive '{event_type}' alert "
                f"(programme={programme.value}, ref={reference_type}#{reference_id})."
            )
            return []

        notifications: List[Notification] = []
        for admin in admins:
            n = cls.emit_notification(
                db=db,
                user_id=admin.id,
                programme=programme,
                event_type=event_type,
                title=title,
                message=message,
                reference_type=reference_type,
                reference_id=reference_id,
            )
            notifications.append(n)
        return notifications

    @classmethod
    def notify_order_delivered(
        cls,
        db: Session,
        order_id: int,
        verified_delivery: bool = False,
    ) -> Optional[Notification]:
        """Notify referring distributor when a Plan B order is verified delivered (OP-02 / R-10 / R-26).

        Safety & Deferral Invariants:
        - The platform does not assume physical delivery based solely on order existence
          or order.is_fulfilled.
        - Physical courier integration is deferred under confirmed decision OP-02 / R-26.
        - If verified_delivery=False (the default), this function fails safely and returns None
          without emitting any false in-dashboard notification.
        - When verified courier delivery evidence is explicitly supplied (verified_delivery=True),
          it resolves the referring distributor and emits PB_DISTRIBUTOR_ORDER_DELIVERED
          with duplicate suppression and caller transaction ownership.

        Args:
            db: Active database session (uncommitted).
            order_id: The ID of the delivered order.
            verified_delivery: Boolean flag indicating verified physical delivery evidence from
                               an automated courier integration. Defaults to False.

        Returns:
            Created Notification entity if verified delivery evidence is present and referring
            distributor was notified, else None.
        """
        # 1. Fail safely if verified courier delivery evidence is missing (OP-02 / R-26)
        if not verified_delivery:
            logger.info(
                f"Order #{order_id} delivery notification deferred: verified courier delivery "
                f"evidence is required before emitting PB_DISTRIBUTOR_ORDER_DELIVERED (OP-02 / R-26)."
            )
            return None

        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.warning(f"Cannot emit order delivery notification: order #{order_id} not found.")
            return None

        purchaser = db.query(User).filter(User.id == order.user_id).first()
        if not purchaser or purchaser.programme != Programme.PLAN_B:
            return None

        # Resolve referring distributor via applied referral code or permanent relationship
        distributor: Optional[User] = None
        if order.applied_referral_code and order.applied_referral_code.strip():
            distributor = (
                db.query(User)
                .filter(User.referral_code == order.applied_referral_code.strip().upper())
                .first()
            )

        if not distributor and purchaser.referred_by_id:
            distributor = (
                db.query(User)
                .filter(User.id == purchaser.referred_by_id)
                .first()
            )

        if not distributor:
            logger.info(f"No referring distributor found for delivered order #{order_id}.")
            return None

        # Self-purchases generate no distributor notification
        if distributor.id == purchaser.id:
            logger.info(f"Self-purchased order #{order_id}: skipping delivery notification.")
            return None

        return cls.emit_notification(
            db=db,
            user_id=distributor.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_DISTRIBUTOR_ORDER_DELIVERED,
            title="Order Delivered",
            message=f"Referred order #{order.id} ({order.order_number}) was successfully delivered.",
            reference_type="order",
            reference_id=order.id,
        )

