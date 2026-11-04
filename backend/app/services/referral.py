import logging
import secrets
import string

from sqlalchemy.orm import Session

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

