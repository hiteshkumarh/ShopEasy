import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.user import User
from app.schemas.referral import ReferralValidateRequest, ReferralValidateResponse
from app.services.referral import validate_referral_code

logger = logging.getLogger("shopeasy.api.referrals")

router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.post(
    "/validate",
    response_model=ReferralValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate referral code eligibility for the current customer",
)
def validate_referral(
    payload: ReferralValidateRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
) -> ReferralValidateResponse:
    """Validate referral code eligibility without modifying database state.

    Enforces:
      - Authenticated customer required.
      - Code must exist and belong to an active customer.
      - Prohibits self-referral and administrator codes.
      - Customer must not have placed any prior successful orders or already be bound.
      - Never mutates customer.referred_by_id or commits database state.
    """
    referrer = validate_referral_code(
        db=db,
        customer=current_user,
        referral_code=payload.referral_code,
    )

    return ReferralValidateResponse(
        is_valid=True,
        referral_code=referrer.referral_code,
        referrer_name=referrer.full_name,
        message="Valid referral code.",
    )
