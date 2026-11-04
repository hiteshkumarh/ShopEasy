from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
from typing import Any, Dict, Optional, Union

import bcrypt
import jwt

from app.core.config import settings

logger = logging.getLogger("shopeasy.security")


def hash_password(password: str) -> str:
    """Hash a plaintext password securely using bcrypt with 12 rounds."""
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an existing bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: Union[int, str],
    role: str,
    phone: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate an HS256 JWT access token for an authenticated user.

    Claims included:
      - sub: user ID as string
      - role: role string ('customer' or 'admin')
      - phone: user mobile number
      - type: 'access'
      - iat: issued-at timestamp (UTC)
      - exp: expiration timestamp (UTC)
    """
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "role": str(role),
        "phone": str(phone),
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(
    token: str, expected_type: Optional[str] = None
) -> Dict[str, Any]:
    """Decode and verify a JWT signature and expiry using the configured algorithm.

    Args:
        token: Encoded JWT string.
        expected_type: Optional expected 'type' claim (e.g. 'access' or 'mfa_pending').

    Returns:
        The decoded claims payload dictionary.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is invalid, signature verification fails,
                              malformed, or type mismatches.
    """
    if not token or not isinstance(token, str):
        raise jwt.InvalidTokenError("Token must be a non-empty string.")

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        logger.warning("Token verification failed: token has expired.")
        raise
    except jwt.InvalidTokenError as exc:
        logger.warning(f"Token verification failed: {type(exc).__name__}.")
        raise
    except Exception as exc:
        logger.warning(f"Unexpected error decoding token: {type(exc).__name__}.")
        raise jwt.InvalidTokenError("Malformed or unparseable token.") from exc

    if expected_type is not None and payload.get("type") != expected_type:
        logger.warning(
            f"Token type mismatch: expected '{expected_type}', got '{payload.get('type')}'."
        )
        raise jwt.InvalidTokenError(f"Invalid token type: expected '{expected_type}'.")

    return payload


def create_mfa_token(user_id: Union[int, str]) -> str:
    """Generate an ephemeral HS256 JWT MFA challenge token for an administrator.

    Claims included:
      - sub: admin user ID as string
      - role: 'admin'
      - type: 'mfa_pending'
      - iat: issued-at timestamp (UTC)
      - exp: 5 minutes from issuance (UTC)
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=5)

    payload = {
        "sub": str(user_id),
        "role": "admin",
        "type": "mfa_pending",
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def hash_otp(otp_code: str) -> str:
    """Hash an OTP code using HMAC-SHA256 with OTP_HMAC_SECRET.

    Returns:
        A 64-character lowercase hexadecimal HMAC-SHA256 digest.
    """
    if not otp_code or not isinstance(otp_code, str):
        raise ValueError("OTP code cannot be empty.")

    clean_code = otp_code.strip()
    secret_bytes = settings.OTP_HMAC_SECRET.encode("utf-8")
    return hmac.new(
        secret_bytes,
        clean_code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_otp_hash(candidate_otp: str, stored_hash: str) -> bool:
    """Verify a candidate OTP against a stored 64-character HMAC-SHA256 digest using constant-time comparison."""
    if not candidate_otp or not stored_hash:
        return False
    if not isinstance(candidate_otp, str) or not isinstance(stored_hash, str):
        return False

    candidate_hash = hash_otp(candidate_otp)
    return hmac.compare_digest(candidate_hash, stored_hash.strip())
