"""Payment provider factory with strict production security safeguards."""

from app.core.config import settings
from app.services.payment.base import PaymentProvider
from app.services.payment.simulated import SimulatedPaymentProvider


def get_payment_provider() -> PaymentProvider:
    """Resolve and instantiate the active payment provider.

    Enforces fail-closed safeguards: simulated payment provider is strictly
    forbidden in production with zero fallback.
    """
    provider_name = settings.PAYMENT_PROVIDER.strip().lower()

    if settings.is_production:
        if provider_name == "simulated" or settings.ALLOW_SIMULATED_PAYMENTS:
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: SimulatedPaymentProvider is strictly "
                "forbidden in production environment. Zero fallback permitted."
            )

    if provider_name == "simulated":
        return SimulatedPaymentProvider()

    if provider_name == "razorpay":
        # Placeholder for future live provider in subsequent production stage
        raise NotImplementedError(
            "RazorpayPaymentProvider is not configured in this development environment."
        )

    raise ValueError(f"Unsupported PAYMENT_PROVIDER: '{provider_name}'")
