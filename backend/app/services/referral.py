import logging
import secrets
import string

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.user import User

logger = logging.getLogger("shopeasy.referral")

# Referral code formatting: REF + 6 uppercase alphanumeric characters
REFERRAL_CODE_PREFIX = "REF"
REFERRAL_CODE_RANDOM_LENGTH = 6
MAX_COLLISION_RETRIES = 5
ALPHANUMERIC_CHARS = string.ascii_uppercase + string.digits


def generate_referral_code(db: Session) -> str:
    """Generate a unique, collision-resistant referral code for a customer.

    Format: 'REF' + 6 uppercase alphanumeric characters (total length: 9 chars).
    Maximum allowed length in schema: 20 characters.
    Checks uniqueness in the database with up to 5 retry attempts.

    Args:
        db: Active SQLAlchemy database session.

    Returns:
        A unique referral code string.

    Raises:
        RuntimeError: If unable to generate a unique code within 5 attempts.
    """
    for attempt in range(1, MAX_COLLISION_RETRIES + 1):
        suffix = "".join(
            secrets.choice(ALPHANUMERIC_CHARS)
            for _ in range(REFERRAL_CODE_RANDOM_LENGTH)
        )
        code = f"{REFERRAL_CODE_PREFIX}{suffix}"

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
) -> User:
    """Validate referral code eligibility without modifying database state.

    Enforces:
      1. Non-empty referral code input.
      2. Self-referral prohibition against customer's own referral code.
      3. Referrer existence in the database.
      4. Self-referral prohibition against referrer's user ID.
      5. Referrer role is CUSTOMER (rejects administrator referral codes).
      6. Referrer account is active.
      7. Customer prior order check (prohibits referral attribution if customer
         already placed a confirmed order or already has a permanent referrer).

    Args:
        db: Active SQLAlchemy database session.
        customer: Authenticated customer attempting to use the referral code.
        referral_code: Referral code string provided by the customer.

    Returns:
        User: The validated active referrer entity.

    Raises:
        HTTPException(400): If any validation condition fails.
    """
    code = referral_code.strip() if referral_code else ""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referral code cannot be empty.",
        )

    # 1. Self-referral check using customer's own referral code
    if customer.referral_code and code.upper() == customer.referral_code.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Self-referral is strictly prohibited. You cannot use your own referral code.",
        )

    # 2. Query referrer
    referrer = (
        db.query(User)
        .filter(func.upper(User.referral_code) == code.upper())
        .first()
    )
    if not referrer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid referral code. Referrer does not exist.",
        )

    # 3. Prohibit self-referral by user ID
    if referrer.id == customer.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Self-referral is strictly prohibited.",
        )

    # 4. Prohibit admin referral codes
    if referrer.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid referral code. Administrator referral codes cannot be used.",
        )

    # 5. Check referrer active status
    if not referrer.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referral code owner account is inactive.",
        )

    # 6. First successful order enforcement (prohibit attribution if already placed orders or bound)
    prior_confirmed_orders = (
        db.query(Order.id)
        .filter(
            Order.user_id == customer.id,
            Order.order_status == OrderStatus.CONFIRMED,
        )
        .count()
    )
    if prior_confirmed_orders > 0 or customer.referred_by_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referral attribution is only applicable on your first successful order and cannot be modified.",
        )

    return referrer
