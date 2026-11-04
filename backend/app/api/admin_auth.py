import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_mfa_token,
    decode_access_token,
    verify_password,
)
from app.models.enums import OTPPurpose, UserRole
from app.models.user import User
from app.schemas.auth import (
    AdminMFAVerifyRequest,
    AdminOTPRequest,
    AdminOTPVerifyRequest,
    AdminPasswordLoginRequest,
    MFARequiredResponse,
    TokenResponse,
)
from app.services.otp_service import (
    _mask_phone,
    create_otp,
    normalize_phone,
    verify_otp,
)

logger = logging.getLogger("shopeasy.auth.admin")

router = APIRouter(prefix="/admin", tags=["Admin Authentication"])


@router.post(
    "/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a login OTP for an administrator",
)
def request_admin_login_otp(
    payload: AdminOTPRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate and send an OTP for an existing active administrator.

    Enforces:
      - Account must be pre-provisioned with role 'admin'. Customers are rejected.
      - Account must be active.
      - 60-second resend cooldown and 5-minute expiry.
      - Returns mock dev_otp in development mode only; never exposes OTP in production.
    """
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    admin = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.ADMIN)
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Administrator account not found.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator account is deactivated.",
        )

    try:
        otp_record = create_otp(db, clean_phone, OTPPurpose.LOGIN)
        db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Error creating admin login OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate admin login OTP. Please try again.",
        )

    response_data: Dict[str, Any] = {
        "message": f"Administrator OTP successfully sent to +91 {_mask_phone(clean_phone)}.",
        "expires_in_minutes": 5,
    }

    if settings.ENVIRONMENT.lower() == "development":
        response_data["dev_otp"] = settings.DEV_OTP_CODE

    return response_data


@router.post(
    "/login/otp",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in administrator using phone and OTP",
)
def login_admin_via_otp(
    payload: AdminOTPVerifyRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify administrator login OTP and issue a full access JWT."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    admin = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.ADMIN)
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator account is deactivated.",
        )

    try:
        is_valid = verify_otp(db, clean_phone, OTPPurpose.LOGIN, payload.otp_code)
        if not is_valid:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired administrator OTP code.",
            )
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error verifying admin OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification error occurred. Please try again.",
        )

    access_token = create_access_token(
        user_id=admin.id,
        role=admin.role.value,
        phone=admin.phone,
    )

    logger.info(f"Administrator logged in via OTP (ID: {admin.id}, Phone: {_mask_phone(clean_phone)}).")
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=admin.role,
    )


@router.post(
    "/login/password",
    response_model=MFARequiredResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate administrator via password and initiate mandatory MFA challenge",
)
def login_admin_via_password(
    payload: AdminPasswordLoginRequest,
    db: Session = Depends(get_db),
) -> MFARequiredResponse:
    """Authenticate administrator password and trigger mandatory second-factor OTP.

    Security Invariant:
      Does NOT issue a full access JWT.
      Instead, issues an ephemeral 5-minute MFA challenge JWT (type='mfa_pending')
      and dispatches an ADMIN_MFA second-factor OTP.
    """
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    admin = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.ADMIN)
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator account is deactivated.",
        )

    if not admin.password_hash or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
        )

    try:
        # Create second-factor MFA OTP
        create_otp(db, clean_phone, OTPPurpose.ADMIN_MFA)
        db.commit()
    except ValueError as exc:
        # Respect cooldown if an MFA request is already in flight
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Error creating admin MFA OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate MFA challenge. Please try again.",
        )

    # Issue ephemeral 5-minute MFA challenge token (type='mfa_pending')
    mfa_token = create_mfa_token(user_id=admin.id)

    logger.info(f"Administrator password verified; MFA challenge dispatched (ID: {admin.id}, Phone: {_mask_phone(clean_phone)}).")
    return MFARequiredResponse(
        mfa_token=mfa_token,
        token_type="mfa",
        expires_in=300,
        mfa_required=True,
    )


@router.post(
    "/mfa/verify",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete administrator second-factor MFA verification and issue access token",
)
def verify_admin_mfa(
    payload: AdminMFAVerifyRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify administrator MFA challenge token and OTP, issuing full access JWT."""
    try:
        mfa_payload = decode_access_token(payload.mfa_token, expected_type="mfa_pending")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA challenge token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA challenge token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate subject and role claims
    token_role = mfa_payload.get("role")
    token_sub = mfa_payload.get("sub")
    if token_role != "admin" or not token_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA token claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        admin_id = int(token_sub)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject in MFA token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Always verify against the live database
    admin = db.query(User).filter(User.id == admin_id).first()
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator account not found.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator account is deactivated.",
        )

    if admin.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account does not hold administrator privileges.",
        )

    # Verify second-factor OTP code
    try:
        is_valid = verify_otp(
            db, admin.phone, OTPPurpose.ADMIN_MFA, payload.otp_code
        )
        if not is_valid:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired MFA OTP code.",
            )
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error verifying admin MFA OTP for {_mask_phone(admin.phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MFA verification failed. Please try again.",
        )

    # All factors verified: issue full access JWT
    access_token = create_access_token(
        user_id=admin.id,
        role=admin.role.value,
        phone=admin.phone,
    )

    logger.info(f"Administrator MFA successfully completed (ID: {admin.id}, Phone: {_mask_phone(admin.phone)}). Full access token issued.")
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=admin.role,
    )

