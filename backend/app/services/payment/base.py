"""Abstract Payment Provider interface and DTO definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.order import Order


class PaymentError(Exception):
    """Base exception for payment domain errors."""
    pass


class PaymentAuthenticationError(PaymentError):
    """Raised when payment webhook/event authentication fails."""
    pass


class PaymentValidationError(PaymentError):
    """Raised when payment event data fails integrity/consistency validation."""
    pass


@dataclass(frozen=True)
class PaymentInitiationResult:
    """Standardized result of a payment session/attempt creation."""
    attempt_reference: str
    provider: str
    amount: Decimal
    currency: str
    checkout_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class VerifiedPaymentEvent:
    """Standardized data parsed from an authenticated payment provider event."""
    provider: str
    provider_event_id: str
    event_type: str
    attempt_reference: str
    amount: Decimal
    currency: str
    raw_payload: Dict[str, Any]
    transaction_id: Optional[str] = None
    failure_reason: Optional[str] = None


class PaymentProvider(ABC):
    """Abstract base class for all payment providers."""

    @abstractmethod
    def create_payment_attempt(
        self,
        order: Order,
        db: Session,
        expires_in_minutes: int = 15,
        return_url: Optional[str] = None,
    ) -> PaymentInitiationResult:
        """Create a payment session/attempt for the specified order."""
        pass

    @abstractmethod
    def verify_and_parse_event(
        self,
        raw_payload: bytes,
        headers: Dict[str, str],
    ) -> VerifiedPaymentEvent:
        """Authenticate and parse an incoming webhook event.

        Raises PaymentAuthenticationError if the event cannot be authenticated.
        Raises PaymentValidationError if required fields are missing or malformed.
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Unique identifier string of the provider (e.g. 'simulated', 'razorpay')."""
        pass
