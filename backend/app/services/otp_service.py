from datetime import datetime, timedelta
import logging
import secrets
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_otp, verify_otp_hash
from app.models.enums import OTPPurpose
from app.models.user import OTP

logger = logging.getLogger("shopeasy.otp")

OTP_EXPIRY_MINUTES = 5
OTP_COOLDOWN_SECONDS = 60


def _mask_phone(phone: str) -> str:
    """Mask phone number for safe log output."""
    if not phone:
        return "****"
    return phone[:3] + "****" + phone[-3:] if len(phone) >= 7 else "****"


def normalize_phone(phone: str) -> str:
    """Normalize and validate a 10-digit mobile number."""
    if not phone:
        raise ValueError("Phone number cannot be empty.")
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        raise ValueError(
            f"Phone number must be exactly 10 digits, got '{phone}'"
        )
    return digits


def generate_otp() -> str:
    """Generate a 6-digit one-time password.

    In development, returns settings.DEV_OTP_CODE ('123456').
    Outside development, returns a cryptographically secure random 6-digit code.
    """
    if settings.ENVIRONMENT.lower() == "development":
        return settings.DEV_OTP_CODE
    # Cryptographically secure 6-digit OTP (100000 - 999999)
    return f"{secrets.randbelow(900000) + 100000:06d}"


def create_otp(
    db: Session,
    phone: str,
    purpose: OTPPurpose,
) -> OTP:
    """Create and persist a new transient OTP record with cooldown and expiry.

    Enforces a 60-second resend cooldown for the same phone number and purpose.
    Marks any prior unused OTPs for this phone and purpose as superseded.
    Expiry is set to exactly 5 minutes from creation.

    Args:
        db: Active SQLAlchemy database session.
        phone: 10-digit mobile number.
        purpose: OTPPurpose enum value (LOGIN, PASSWORD_RESET, ADMIN_MFA).

    Returns:
        The newly created and flushed OTP database record.

    Raises:
        ValueError: If cooldown is active or phone format is invalid.
    """
    clean_phone = normalize_phone(phone)
    now = datetime.now()

    # 1. Enforce 60-second cooldown for the same phone and purpose
    cooldown_cutoff = now - timedelta(seconds=OTP_COOLDOWN_SECONDS)
    recent_otp = (
        db.query(OTP)
        .filter(
            OTP.phone == clean_phone,
            OTP.purpose == purpose,
            OTP.created_at >= cooldown_cutoff,
        )
        .order_by(OTP.created_at.desc())
        .first()
    )

    if recent_otp:
        elapsed = (now - recent_otp.created_at).total_seconds()
        remaining = max(1, int(OTP_COOLDOWN_SECONDS - elapsed))
        raise ValueError(
            f"Please wait {remaining} seconds before requesting a new OTP."
        )

    # 2. Invalidate any prior unused OTPs for this phone and purpose
    db.query(OTP).filter(
        OTP.phone == clean_phone,
        OTP.purpose == purpose,
        OTP.is_used == False,  # noqa: E712
    ).update({"is_used": True})

    # 3. Generate raw OTP and hash using HMAC-SHA256 for secure storage
    raw_code = generate_otp()
    hashed_code = hash_otp(raw_code)
    expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

    otp_record = OTP(
        phone=clean_phone,
        otp_code=hashed_code,
        purpose=purpose,
        is_used=False,
        expires_at=expires_at,
    )
    db.add(otp_record)
    db.flush()

    logger.info(
        f"OTP successfully created for phone {_mask_phone(clean_phone)} with purpose '{purpose.value}'."
    )
    return otp_record


def verify_otp(
    db: Session,
    phone: str,
    purpose: OTPPurpose,
    otp_code: str,
) -> bool:
    """Verify an OTP code against unexpired and unused database records.

    Matches phone, purpose, and OTP code.
    Rejects expired or already-used OTPs.
    Uses pessimistic row-level locking (with_for_update) to prevent concurrent reuse.
    Atomically marks the verified OTP as used.

    Args:
        db: Active SQLAlchemy database session.
        phone: 10-digit mobile number.
        purpose: OTPPurpose enum value.
        otp_code: 6-digit candidate OTP code.

    Returns:
        True if verification succeeded and OTP was marked used; False otherwise.
    """
    if not otp_code or not isinstance(otp_code, str):
        return False

    clean_phone = normalize_phone(phone)
    clean_code = otp_code.strip()
    now = datetime.now()

    # Query latest unused OTP with row-level lock to prevent concurrent double-verification
    otp_record = (
        db.query(OTP)
        .filter(
            OTP.phone == clean_phone,
            OTP.purpose == purpose,
            OTP.is_used == False,  # noqa: E712
        )
        .order_by(OTP.created_at.desc())
        .with_for_update()
        .first()
    )

    if not otp_record:
        logger.warning(
            f"OTP verification failed: no active unused OTP for phone {_mask_phone(clean_phone)} and purpose '{purpose.value}'."
        )
        return False

    # Check expiry
    if otp_record.expires_at < now:
        logger.warning(
            f"OTP verification failed: OTP has expired for phone {_mask_phone(clean_phone)}."
        )
        return False

    # Check code match using constant-time HMAC comparison
    if not verify_otp_hash(clean_code, otp_record.otp_code):
        logger.warning(
            f"OTP verification failed: incorrect OTP code provided for phone {_mask_phone(clean_phone)}."
        )
        return False

    # Atomically mark as used
    otp_record.is_used = True
    db.flush()

    logger.info(
        f"OTP verified successfully and marked used for phone {_mask_phone(clean_phone)} with purpose '{purpose.value}'."
    )
    return True

