import logging
import secrets
import string
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order
from app.models.referral import ReferralRelationship
from app.models.user import User

logger = logging.getLogger("shopeasy.referral")

# Referral code formatting: Programme prefix + 6 uppercase alphanumeric characters
REFERRAL_CODE_RANDOM_LENGTH = 6
MAX_COLLISION_RETRIES = 5
ALPHANUMERIC_CHARS = string.ascii_uppercase + string.digits


def generate_referral_code(
    db: Session, programme: Programme = Programme.PLAN_A
) -> str:
    """Generate a unique, collision-resistant referral code for a customer or distributor.

    Prefixes:
      - Programme.PLAN_A: 'PA' + 6 characters (e.g. PA7X9Q2K)
      - Programme.PLAN_B: 'PB' + 6 characters (e.g. PB3M8W1R)
      - Programme.LEGACY: 'REF' + 6 characters (e.g. REF4J8L9P)

    Args:
        db: Active SQLAlchemy database session.
        programme: Programme classification for code prefix selection.

    Returns:
        A unique referral code string.

    Raises:
        RuntimeError: If unable to generate a unique code within 5 attempts.
    """
    if programme == Programme.PLAN_B:
        prefix = "PB"
    elif programme == Programme.PLAN_A:
        prefix = "PA"
    else:
        prefix = "REF"

    for attempt in range(1, MAX_COLLISION_RETRIES + 1):
        suffix = "".join(
            secrets.choice(ALPHANUMERIC_CHARS)
            for _ in range(REFERRAL_CODE_RANDOM_LENGTH)
        )
        code = f"{prefix}{suffix}"

        # Verify uniqueness in database
        existing = db.query(User.id).filter(User.referral_code == code).first()
        if not existing:
            return code

        logger.warning(
            f"Referral code collision detected on '{code}' (attempt {attempt}/{MAX_COLLISION_RETRIES}). Retrying..."
        )

    raise RuntimeError(
        f"Failed to generate a unique referral code after {MAX_COLLISION_RETRIES} attempts."
    )


def validate_referral_code(
    db: Session,
    customer: User,
    referral_code: str,
    target_programme: Optional[Programme] = None,
) -> User:
    """Validate referral code eligibility without modifying database state.

    Enforces:
      1. Non-empty referral code input.
      2. Programme-specific exact error messages:
         - Plan A: "Invalid Referral"
         - Plan B: "Wrong Referral ID"
      3. Self-referral prohibition against customer's own referral code or ID.
      4. Referrer existence in the database.
      5. Referrer role is CUSTOMER (rejects administrator referral codes).
      6. Direction rules (RG-08):
         - Allowed: A->A, B->A
         - Forbidden: A->B, B->B (Plan B distributors cannot be referred)
      7. Referrer account status (RG-14):
         - Deactivated/inactive accounts cannot refer.
         - Blocked Plan B distributors may log in/view but cannot refer or earn.
      8. Referrer purchase/eligibility requirement:
         - Plan A: Requires at least one confirmed paid purchase / paid Billing ID (RG-07).
         - Plan B: Newly registered distributor code is inactive; requires a successful
           qualifying purchase before becoming eligible (BR-X2, RG-10A).
      9. Referee binding rules (BR-X1, RG-06, RG-09):
         - If referee is already permanently bound to a referrer, cannot change to another.
         - If referee placed previous orders without a referral code (unreferred), they MAY
           enter a referral code on a later order (BR-X1 Option B).

    Args:
        db: Active SQLAlchemy database session.
        customer: Authenticated customer attempting to use the referral code.
        referral_code: Referral code string provided by the customer.
        target_programme: Optional programme context for validation.

    Returns:
        User: The validated active referrer entity.

    Raises:
        HTTPException(400): If any validation condition fails with exact message:
                            "Invalid Referral" (Plan A) or "Wrong Referral ID" (Plan B).
    """
    code = referral_code.strip() if referral_code else ""

    # Initial error message determination based on prefix or explicit target programme
    is_plan_b_context = (
        target_programme == Programme.PLAN_B
        or (bool(code) and code.upper().startswith("PB"))
    )
    initial_err_msg = "Wrong Referral ID" if is_plan_b_context else "Invalid Referral"

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=initial_err_msg,
        )

    # 1. Lookup referrer by referral code
    referrer = (
        db.query(User)
        .filter(func.upper(User.referral_code) == code.upper())
        .first()
    )
    if not referrer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=initial_err_msg,
        )

    # Determine authoritative error message based on referrer programme and context
    is_plan_b_referrer = (
        referrer.programme == Programme.PLAN_B
        or code.upper().startswith("PB")
        or target_programme == Programme.PLAN_B
    )
    err_msg = "Wrong Referral ID" if is_plan_b_referrer else "Invalid Referral"

    # 2. Self-referral prohibition
    if customer.referral_code and code.upper() == customer.referral_code.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )
    if referrer.id == customer.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    # 3. Prohibit admin referral codes
    if referrer.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    # 4. Direction rules (RG-08): Allowed: A->A, B->A. Forbidden: A->B, B->B.
    if customer.programme == Programme.PLAN_B:
        # Plan B distributors cannot be referred by anyone
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    # 5. Referrer account status check (RG-14)
    if not referrer.is_active or referrer.account_status == AccountStatus.DEACTIVATED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    if referrer.account_status == AccountStatus.BLOCKED:
        # Blocked distributor may view but cannot refer or earn
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    # 6. Referrer purchase/eligibility requirements
    if referrer.programme == Programme.PLAN_A:
        # Plan A referrer eligibility requires a paid Billing ID / confirmed paid purchase (RG-07)
        paid_orders_count = (
            db.query(Order.id)
            .filter(
                Order.user_id == referrer.id,
                Order.order_status == OrderStatus.CONFIRMED,
                Order.payment_status == PaymentStatus.COMPLETED,
            )
            .count()
        )
        if paid_orders_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Referral",
            )
    elif referrer.programme == Programme.PLAN_B:
        # Plan B distributor referral eligibility activates only after a successful
        # qualifying purchase (BR-X2, RG-10A)
        paid_orders_count = (
            db.query(Order.id)
            .filter(
                Order.user_id == referrer.id,
                Order.order_status == OrderStatus.CONFIRMED,
                Order.payment_status == PaymentStatus.COMPLETED,
            )
            .count()
        )
        if paid_orders_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wrong Referral ID",
            )

    # 7. Referee binding check (BR-X1, RG-06, RG-09)
    existing_relationship = (
        db.query(ReferralRelationship)
        .filter(ReferralRelationship.referee_id == customer.id)
        .first()
    )
    already_bound_referrer_id = (
        existing_relationship.referrer_id
        if existing_relationship
        else customer.referred_by_id
    )
    if already_bound_referrer_id is not None:
        if already_bound_referrer_id != referrer.id:
            # Relationship is permanent once established; cannot change referrer
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=err_msg,
            )

    return referrer
