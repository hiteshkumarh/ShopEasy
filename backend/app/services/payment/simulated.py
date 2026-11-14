"""Simulated Payment Provider for development and automated testing environments."""

from decimal import Decimal
import json
import logging
from typing import Any, Dict, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.order import Order
from app.services.payment.base import (
    PaymentAuthenticationError,
    PaymentInitiationResult,
    PaymentProvider,
    PaymentValidationError,
    VerifiedPaymentEvent,
)

logger = logging.getLogger("shopeasy.payment.simulated")


class SimulatedPaymentProvider(PaymentProvider):
    """Simulated payment provider for development and testing.

    Safety: Strictly prohibited in production environments.
    """

    def get_provider_name(self) -> str:
        return "simulated"

    def create_payment_attempt(
        self,
        order: Order,
        db: Session,
        expires_in_minutes: int = 15,
        return_url: Optional[str] = None,
    ) -> PaymentInitiationResult:
        attempt_ref = f"SIM-ATT-{uuid.uuid4().hex[:12].upper()}"
        amount = Decimal(str(order.total_amount)).quantize(Decimal("0.01"))
        checkout_url = f"/simulated-checkout?attempt_id={attempt_ref}&order_id={order.id}"

        return PaymentInitiationResult(
            attempt_reference=attempt_ref,
            provider="simulated",
            amount=amount,
            currency="INR",
            checkout_url=checkout_url,
            metadata={
                "order_number": order.order_number,
                "expires_in_minutes": expires_in_minutes,
            },
        )

    def verify_and_parse_event(
        self,
        raw_payload: bytes,
        headers: Dict[str, str],
    ) -> VerifiedPaymentEvent:
        # 1. Authenticate simulated request header
        # Case-insensitive header lookup
        auth_header = None
        for k, v in headers.items():
            if k.lower() == "x-shopeasy-simulated-auth":
                auth_header = v
                break

        expected_secret = settings.SIMULATED_PAYMENT_SECRET
        if not auth_header or auth_header.strip() != expected_secret:
            logger.warning("Simulated payment webhook rejected: invalid or missing X-ShopEasy-Simulated-Auth header.")
            raise PaymentAuthenticationError("Unauthorized: Missing or invalid simulated payment authorization header.")

        # 2. Parse payload
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except Exception as exc:
            raise PaymentValidationError(f"Invalid JSON payload in payment event: {exc}")

        event_id = payload.get("event_id") or payload.get("provider_event_id")
        event_type = payload.get("event_type")
        attempt_ref = payload.get("attempt_reference")
        raw_amount = payload.get("amount")
        currency = payload.get("currency", "INR")

        if not event_id or not event_type or not attempt_ref or raw_amount is None:
            raise PaymentValidationError(
                "Missing required payment event fields: event_id, event_type, attempt_reference, and amount are required."
            )

        try:
            amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        except Exception as exc:
            raise PaymentValidationError(f"Invalid decimal amount '{raw_amount}': {exc}")

        return VerifiedPaymentEvent(
            provider="simulated",
            provider_event_id=str(event_id),
            event_type=str(event_type),
            attempt_reference=str(attempt_ref),
            amount=amount,
            currency=str(currency).upper(),
            raw_payload=payload,
            transaction_id=payload.get("transaction_id"),
            failure_reason=payload.get("failure_reason"),
        )
