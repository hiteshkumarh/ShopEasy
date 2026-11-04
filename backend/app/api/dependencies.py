import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.enums import UserRole
from app.models.user import User

logger = logging.getLogger("shopeasy.auth")

# OAuth2 password bearer scheme for token extraction from Authorization header
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/customer/login/password",
    auto_error=False,
)

AUTH_HEADER = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate Bearer access token and load the active database user.

    Enforces:
      - Presence of Authorization Bearer token.
      - Signature and expiration validity via decode_access_token().
      - Token claim type == 'access' (rejects MFA challenge tokens).
      - Valid user ID in sub claim.
      - User existence in database.
      - User active status (is_active == True).
      - Synchronized role: token role claim must match database role.

    Returns:
        Authenticated User ORM entity.

    Raises:
        HTTPException 401: If token is missing, invalid, expired, MFA-only,
                           or if user is missing, inactive, or role mismatched.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers=AUTH_HEADER,
        )

    try:
        payload = decode_access_token(token, expected_type="access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired. Please log in again.",
            headers=AUTH_HEADER,
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers=AUTH_HEADER,
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject identifier is missing.",
            headers=AUTH_HEADER,
        )

    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user subject in token.",
            headers=AUTH_HEADER,
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers=AUTH_HEADER,
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated.",
            headers=AUTH_HEADER,
        )

    token_role = payload.get("role")
    if token_role != user.role.value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token role does not match user account role.",
            headers=AUTH_HEADER,
        )

    return user


def require_customer(current_user: User = Depends(get_current_user)) -> User:
    """Authorize authenticated customer users.

    Rejects administrator users with HTTP 403 Forbidden.
    """
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Customer privileges required.",
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Authorize authenticated administrator users.

    Rejects customer users with HTTP 403 Forbidden.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Administrator privileges required.",
        )
    return current_user

