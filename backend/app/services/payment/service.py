"""Core payment service coordinating payment sessions, events, state transitions, and expiry."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, Optional, Tuple
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.cart import CartItem
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.payment import PaymentAttempt, PaymentEvent
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import User
from app.services.fulfilment_handoff import dispatch_order_fulfilment
from app.services.payment.base import (
    PaymentInitiationResult,
    PaymentProvider,
    PaymentValidationError,
    VerifiedPaymentEvent,
)
from app.services.payment.factory import get_payment_provider

logger = logging.getLogger("shopeasy.payment.service")


class PaymentService:
    """Domain service managing the complete payment lifecycle."""

    @staticmethod
    def create_payment_attempt(
        db: Session,
        order: Order,
        expires_in_minutes: int = 15,
        provider: Optional[PaymentProvider] = None,
        return_url: Optional[str] = None,
    ) -> Tuple[PaymentAttempt, PaymentInitiationResult]:
        """Create a new payment attempt for an order."""
        if provider is None:
            provider = get_payment_provider()

        result = provider.create_payment_attempt(
            order=order,
            db=db,
            expires_in_minutes=expires_in_minutes,
            return_url=return_url,
        )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=expires_in_minutes)

        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference=result.attempt_reference,
            provider=result.provider,
            amount=result.amount,
            currency=result.currency,
            status=PaymentStatus.PENDING,
            expires_at=expires_at,
        )
        db.add(attempt)
        db.flush()

        return attempt, result

    @staticmethod
    def process_verified_event(
        db: Session,
        raw_payload: bytes,
        headers: Dict[str, str],
        provider: Optional[PaymentProvider] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Verify, authenticate, and idempotently process an incoming payment event.

        Executes atomic state machine transitions, referral binding, and stock management.
        """
        if provider is None:
            provider = get_payment_provider()

        # 1. Authenticate and parse inbound event
        event = provider.verify_and_parse_event(raw_payload=raw_payload, headers=headers)

        now = datetime.now(timezone.utc)

        # 2. Concurrency barrier: insert payment_events with unique (provider, provider_event_id)
        # Using a savepoint / nested transaction to catch duplicate constraint cleanly
        try:
            with db.begin_nested():
                event_record = PaymentEvent(
                    provider=event.provider,
                    provider_event_id=event.provider_event_id,
                    event_type=event.event_type,
                    payload_json=json.dumps(event.raw_payload),
                    status="RECEIVED",
                    created_at=now,
                )
                db.add(event_record)
                db.flush()
        except IntegrityError:
            # Another transaction already inserted this (provider, provider_event_id)
            logger.info(
                f"Duplicate payment event received: provider={event.provider}, event_id={event.provider_event_id}. "
                "Returning idempotent acknowledgement."
            )
            existing_event = (
                db.query(PaymentEvent)
                .filter(
                    PaymentEvent.provider == event.provider,
                    PaymentEvent.provider_event_id == event.provider_event_id,
                )
                .first()
            )
            return "ALREADY_PROCESSED", {
                "status": "already_processed",
                "event_id": event.provider_event_id,
                "recorded_status": existing_event.status if existing_event else "UNKNOWN",
            }

        # 3. Lock PaymentAttempt and Order using SELECT ... FOR UPDATE
        attempt = (
            db.query(PaymentAttempt)
            .filter(PaymentAttempt.attempt_reference == event.attempt_reference)
            .with_for_update()
            .first()
        )
        if not attempt:
            event_record.status = "FAILED_VALIDATION"
            event_record.error_message = f"Payment attempt '{event.attempt_reference}' not found."
            db.commit()
            raise PaymentValidationError(f"Payment attempt '{event.attempt_reference}' does not exist.")

        event_record.payment_attempt_id = attempt.id
        event_record.order_id = attempt.order_id

        order = (
            db.query(Order)
            .filter(Order.id == attempt.order_id)
            .with_for_update()
            .first()
        )
        if not order:
            event_record.status = "FAILED_VALIDATION"
            event_record.error_message = f"Order #{attempt.order_id} not found."
            db.commit()
            raise PaymentValidationError(f"Associated order #{attempt.order_id} does not exist.")

        # 4. Strict identity, amount, currency, and provider validations
        if event.provider.lower() != attempt.provider.lower():
            event_record.status = "FAILED_VALIDATION"
            event_record.error_message = f"Provider mismatch: event '{event.provider}' != attempt '{attempt.provider}'."
            db.commit()
            raise PaymentValidationError("Payment provider mismatch.")

        event_amount = Decimal(str(event.amount)).quantize(Decimal("0.01"))
        attempt_amount = Decimal(str(attempt.amount)).quantize(Decimal("0.01"))
        if event_amount != attempt_amount:
            event_record.status = "FAILED_VALIDATION"
            event_record.error_message = (
                f"Amount mismatch: event {event_amount} != attempt {attempt_amount}."
            )
            db.commit()
            raise PaymentValidationError(
                f"Payment amount mismatch: expected {attempt_amount}, received {event_amount}."
            )

        if event.currency.upper() != attempt.currency.upper():
            event_record.status = "FAILED_VALIDATION"
            event_record.error_message = (
                f"Currency mismatch: event '{event.currency}' != attempt '{attempt.currency}'."
            )
            db.commit()
            raise PaymentValidationError("Payment currency mismatch.")

        # 5. State machine transition: Handle payment.completed
        if event.event_type == "payment.completed":
            if order.order_status == OrderStatus.CONFIRMED:
                # Duplicate success event for already confirmed order
                event_record.status = "PROCESSED"
                event_record.processed_at = now
                db.commit()
                return "ALREADY_CONFIRMED", {
                    "status": "already_confirmed",
                    "order_id": order.id,
                    "order_number": order.order_number,
                }

            if order.order_status == OrderStatus.FAILED:
                # Late payment arriving after failure or expiration
                logger.warning(
                    f"Late payment completed for already failed order #{order.id} ({order.order_number}). "
                    "Flagging for financial reconciliation."
                )
                event_record.status = "FLAGGED_FOR_RECONCILIATION"
                event_record.error_message = "LATE_PAYMENT_AFTER_FAILURE: received payment.completed for order in FAILED status."
                event_record.processed_at = now
                # Attempt remains FAILED; Order remains FAILED; stock is NOT decremented again
                db.commit()
                return "FLAGGED_FOR_RECONCILIATION", {
                    "status": "flagged_for_reconciliation",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "reason": "late_payment_after_order_failure",
                }

            if order.order_status == OrderStatus.PENDING_PAYMENT:
                # Normal successful payment confirmation
                attempt.status = PaymentStatus.COMPLETED
                attempt.provider_transaction_id = event.transaction_id or f"TXN-{event.provider_event_id}"
                order.order_status = OrderStatus.CONFIRMED
                order.payment_status = PaymentStatus.COMPLETED
                order.payment_reference = attempt.attempt_reference

                event_record.status = "PROCESSED"
                event_record.processed_at = now

                # Clear customer cart strictly upon successful payment
                db.query(CartItem).filter(CartItem.user_id == order.user_id).delete()

                # Permanent referral binding (WP-4: RG-06, RG-09, RG-11, BR-X1)
                PaymentService._bind_referral_on_payment_success(db, order)

                # Commit payment transaction
                db.commit()

                # Trigger synchronous handoff hook to WP-6 fulfilment
                try:
                    dispatch_order_fulfilment(order.id, db)
                except Exception as exc:
                    logger.error(f"Post-payment fulfilment handoff hook raised exception for order #{order.id}: {exc}")

                return "COMPLETED", {
                    "status": "completed",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "payment_reference": attempt.attempt_reference,
                }

        # 6. State machine transition: Handle payment.failed
        elif event.event_type == "payment.failed":
            if order.order_status == OrderStatus.CONFIRMED:
                # Out-of-order failure event arriving after order was already confirmed
                logger.warning(
                    f"Out-of-order payment failure event received for confirmed order #{order.id}. "
                    "Ignoring event to prevent downgrading confirmed order."
                )
                event_record.status = "IGNORED_OUT_OF_ORDER"
                event_record.processed_at = now
                db.commit()
                return "IGNORED_OUT_OF_ORDER", {
                    "status": "ignored_out_of_order",
                    "order_id": order.id,
                    "order_number": order.order_number,
                }

            if order.order_status == OrderStatus.FAILED:
                # Duplicate failure event
                event_record.status = "PROCESSED"
                event_record.processed_at = now
                db.commit()
                return "ALREADY_FAILED", {
                    "status": "already_failed",
                    "order_id": order.id,
                    "order_number": order.order_number,
                }

            if order.order_status == OrderStatus.PENDING_PAYMENT:
                # First failure transition
                attempt.status = PaymentStatus.FAILED
                attempt.failure_reason = event.failure_reason or "Payment failed at provider."
                order.order_status = OrderStatus.FAILED
                order.payment_status = PaymentStatus.FAILED

                event_record.status = "PROCESSED"
                event_record.processed_at = now

                # Single stock restoration: restore stock to products
                for item in order.order_items:
                    product = (
                        db.query(Product)
                        .filter(Product.id == item.product_id)
                        .with_for_update()
                        .first()
                    )
                    if product:
                        product.stock += item.quantity

                # Cart is preserved (not deleted) for customer retry
                db.commit()
                return "FAILED", {
                    "status": "failed",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "failure_reason": attempt.failure_reason,
                }

        # Unsupported or unknown event type
        event_record.status = "UNHANDLED_EVENT_TYPE"
        db.commit()
        return "UNHANDLED", {"status": "unhandled_event_type", "event_type": event.event_type}

    @staticmethod
    def _bind_referral_on_payment_success(db: Session, order: Order) -> None:
        """Bind permanent referral relationship and audit log on first successful order."""
        customer = db.query(User).filter(User.id == order.user_id).first()
        if not customer:
            return

        code_input = order.applied_referral_code
        if not code_input:
            return

        referrer = (
            db.query(User)
            .filter(User.referral_code == code_input)
            .first()
        )
        if not referrer:
            return

        existing_rel = (
            db.query(ReferralRelationship)
            .filter(ReferralRelationship.referee_id == customer.id)
            .first()
        )
        if customer.referred_by_id is None and existing_rel is None:
            customer.referred_by_id = referrer.id
            new_rel = ReferralRelationship(
                referee_id=customer.id,
                referrer_id=referrer.id,
                referee_programme=customer.programme,
                referrer_programme=referrer.programme,
                referral_code_used=referrer.referral_code,
                binding_channel="checkout",
                is_active=True,
            )
            db.add(new_rel)
            db.flush()

            # Append-only security and operational audit trail
            audit = AuditLog(
                actor_id=customer.id,
                actor_role=customer.role.value if hasattr(customer.role, "value") else str(customer.role),
                action="REFERRAL_RELATIONSHIP_CREATED",
                entity_type="referral_relationship",
                entity_id=str(new_rel.id),
                new_values=json.dumps({
                    "referee_id": customer.id,
                    "referrer_id": referrer.id,
                    "referee_programme": customer.programme.value if hasattr(customer.programme, "value") else str(customer.programme),
                    "referrer_programme": referrer.programme.value if hasattr(referrer.programme, "value") else str(referrer.programme),
                    "referral_code_used": referrer.referral_code,
                    "order_id": order.id,
                    "order_number": order.order_number,
                }),
            )
            db.add(audit)

    @staticmethod
    def expire_stale_payment_attempts(db: Session, batch_size: int = 100) -> int:
        """Find and expire payment attempts that have passed their expires_at deadline.

        Transactional Strategy:
        - Each candidate attempt is processed within its own dedicated savepoint (SAVEPOINT)
          using `savepoint = db.begin_nested()`.
        - The row-lock hierarchy is strictly preserved across all operations:
          1. PaymentAttempt (.with_for_update())
          2. Order (.with_for_update())
          3. Product (.with_for_update())
        - If any candidate fails (e.g., database serialization error, deadlock, unexpected constraint
          conflict, or event ID collision), `savepoint.rollback()` reverts all pending mutations for
          that candidate atomically (reverting stock restoration, attempt state, order state, and event).
        - If the candidate succeeds, `savepoint.commit()` releases the savepoint, and `db.commit()` commits
          the outer transaction to durably persist the candidate before proceeding to the next.
        - Idempotency & Race Protection:
          - If a concurrent webhook or worker modifies the attempt/order first, the re-check under row lock
            skips the candidate without mutating state.
          - Synthetic expiry event IDs incorporate the attempt reference and a cryptographic entropy suffix
            to prevent collisions with external webhook IDs or duplicate executions.
        """
        now = datetime.now(timezone.utc)
        expired_candidates = (
            db.query(PaymentAttempt.id)
            .filter(
                PaymentAttempt.status == PaymentStatus.PENDING,
                PaymentAttempt.expires_at < now,
            )
            .order_by(PaymentAttempt.expires_at.asc())
            .limit(batch_size)
            .all()
        )

        expired_count = 0
        for (candidate_id,) in expired_candidates:
            savepoint = db.begin_nested()
            try:
                # 1. Lock Attempt first (Hierarchy Level 1)
                attempt = (
                    db.query(PaymentAttempt)
                    .filter(PaymentAttempt.id == candidate_id)
                    .with_for_update()
                    .first()
                )
                if not attempt or attempt.status != PaymentStatus.PENDING:
                    savepoint.rollback()
                    continue

                # 2. Lock Order second (Hierarchy Level 2)
                order = (
                    db.query(Order)
                    .filter(Order.id == attempt.order_id)
                    .with_for_update()
                    .first()
                )
                if not order or order.order_status != OrderStatus.PENDING_PAYMENT:
                    savepoint.rollback()
                    continue

                # 3. Lock Products and restore stock once (Hierarchy Level 3)
                for item in order.order_items:
                    product = (
                        db.query(Product)
                        .filter(Product.id == item.product_id)
                        .with_for_update()
                        .first()
                    )
                    if product:
                        product.stock += item.quantity

                # 4. Atomically transition attempt and order to terminal FAILED state
                attempt.status = PaymentStatus.FAILED
                attempt.failure_reason = "PAYMENT_ATTEMPT_EXPIRED"
                order.order_status = OrderStatus.FAILED
                order.payment_status = PaymentStatus.FAILED

                # 5. Insert expiry event in append-only journal with collision-resistant ID
                expiry_event_id = f"exp_{attempt.attempt_reference}_{uuid.uuid4().hex[:8]}"
                expiry_event = PaymentEvent(
                    provider=attempt.provider,
                    provider_event_id=expiry_event_id,
                    event_type="payment.expired",
                    order_id=order.id,
                    payment_attempt_id=attempt.id,
                    payload_json=json.dumps({
                        "reason": "attempt_timeout_exceeded",
                        "attempt_reference": attempt.attempt_reference,
                    }),
                    status="PROCESSED",
                    processed_at=now,
                )
                db.add(expiry_event)
                db.flush()

                # Commit savepoint then commit outer transaction per candidate
                savepoint.commit()
                db.commit()
                expired_count += 1
            except Exception as exc:
                if savepoint.is_active:
                    savepoint.rollback()
                db.rollback()
                logger.error(
                    f"Error expiring payment attempt #{candidate_id}; candidate rolled back atomically: {exc}"
                )

        return expired_count
