"""Simulated payment endpoints for development and automated testing environments only."""

import json
import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.enums import OrderStatus, PaymentStatus, UserRole
from app.models.order import Order
from app.models.payment import PaymentAttempt
from app.models.user import User
from app.services.payment.service import PaymentService

logger = logging.getLogger("shopeasy.payments.simulated")

router = APIRouter(prefix="/payments/simulated", tags=["Simulated Payments"])


class SimulatePaymentRequest(BaseModel):
    """Payload to trigger simulated payment callback in dev/test mode."""

    attempt_reference: str = Field(..., description="Unique attempt reference string returned during checkout")
    action: str = Field("success", description="Action to simulate: 'success' or 'failure'")
    failure_reason: Optional[str] = Field(None, description="Optional reason if simulating failure")


@router.post(
    "/simulate",
    status_code=status.HTTP_200_OK,
    summary="Simulate payment gateway callback (Development/Testing Only)",
)
def simulate_payment(
    payload: SimulatePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger a simulated gateway webhook callback for a pending payment attempt.

    Enforces ownership: ordinary customers can only simulate payments for their own orders.
    Administrators can simulate payments for any order.
    """
    if settings.is_production or not settings.ALLOW_SIMULATED_PAYMENTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulated payment endpoints are disabled.",
        )

    attempt = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.attempt_reference == payload.attempt_reference)
        .first()
    )
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment attempt '{payload.attempt_reference}' not found.",
        )

    order = db.query(Order).filter(Order.id == attempt.order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order #{attempt.order_id} not found.",
        )

    # Ownership check: must be owner or admin
    is_admin = (
        current_user.role == UserRole.ADMIN
        if hasattr(current_user.role, "value")
        else str(current_user.role) == "admin"
    )
    if not is_admin and order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You can only simulate payments for your own orders.",
        )

    if order.order_status != OrderStatus.PENDING_PAYMENT or attempt.status != PaymentStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot simulate payment for order in '{order.order_status.value}' / attempt in '{attempt.status.value}'.",
        )

    # Construct genuine simulated webhook payload
    event_type = "payment.completed" if payload.action.lower() == "success" else "payment.failed"
    event_id = f"sim_evt_{uuid.uuid4().hex[:12]}"
    sim_payload = {
        "event_id": event_id,
        "event_type": event_type,
        "attempt_reference": attempt.attempt_reference,
        "amount": float(attempt.amount),
        "currency": attempt.currency,
        "transaction_id": f"SIM-TXN-{uuid.uuid4().hex[:8].upper()}" if event_type == "payment.completed" else None,
        "failure_reason": payload.failure_reason or ("Simulated payment failure" if event_type == "payment.failed" else None),
    }

    raw_bytes = json.dumps(sim_payload).encode("utf-8")
    headers = {
        "X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET,
        "Content-Type": "application/json",
    }

    outcome, result = PaymentService.process_verified_event(
        db=db,
        raw_payload=raw_bytes,
        headers=headers,
    )

    return {
        "success": True,
        "outcome": outcome,
        "data": result,
    }
