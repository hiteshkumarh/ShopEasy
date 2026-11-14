"""Payment webhook endpoints for processing inbound provider events."""

import logging
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.payment.base import (
    PaymentAuthenticationError,
    PaymentValidationError,
)
from app.services.payment.service import PaymentService

logger = logging.getLogger("shopeasy.payments.webhook")

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/events",
    status_code=status.HTTP_200_OK,
    summary="Inbound payment provider webhook callback",
)
async def handle_payment_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive, authenticate, and process inbound webhook events from payment providers."""
    raw_payload = await request.body()
    headers_dict = dict(request.headers)

    try:
        outcome, result = PaymentService.process_verified_event(
            db=db,
            raw_payload=raw_payload,
            headers=headers_dict,
        )
        return {
            "success": True,
            "outcome": outcome,
            "data": result,
        }
    except PaymentAuthenticationError as auth_err:
        logger.warning(f"Payment webhook authentication failed: {auth_err}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(auth_err),
        )
    except PaymentValidationError as val_err:
        logger.warning(f"Payment webhook validation failed: {val_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as exc:
        logger.error(f"Internal error processing payment webhook: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process payment event.",
        )
