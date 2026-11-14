import logging
from decimal import Decimal
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import AccountStatus, OTPPurpose, Programme, UserRole, WalletType
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import (
    CustomerOTPRequest,
    CustomerOTPVerifyRequest,
    CustomerPasswordLoginRequest,
    CustomerPasswordResetConfirmRequest,
    CustomerPasswordResetRequest,
    CustomerRegisterRequest,
    CustomerRegisterResponse,
    TokenResponse,
)
from app.services.otp_service import (
    _mask_phone,
    create_otp,
    normalize_phone,
    verify_otp,
)
from app.services.referral import generate_referral_code

logger = logging.getLogger("shopeasy.auth.distributor")

router = APIRouter(prefix="/distributor", tags=["Plan B Distributor Authentication"])


@router.post(
    "/register",
    response_model=CustomerRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new Plan B distributor account",
)
def register_distributor(
    payload: CustomerRegisterRequest,
    db: Session = Depends(get_db),
) -> CustomerRegisterResponse:
    """Register a new Plan B distributor account with automatic PB-prefix referral code.

    Enforces:
      - Programme selection must be PLAN_B.
      - Phone uniqueness across all programmes (RG-02).
      - Unique referral code with 'PB' prefix (RG-03).
      - Referral eligibility is initially inactive until first qualifying purchase (BR-X2).
      - Zero referral code required at registration (RG-04, R-12).
      - Standard isolated earning wallets created.
    """
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Enforce Plan B registration on this endpoint
    if payload.programme != Programme.PLAN_B:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Distributor registration is strictly for Plan B. Plan A customers must register via the customer portal.",
        )

    # Check phone uniqueness across all programmes
    existing_user = db.query(User.id).filter(User.phone == clean_phone).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this mobile number already exists.",
        )

    # Generate collision-checked unique referral code with PB prefix
    try:
        referral_code = generate_referral_code(db, programme=Programme.PLAN_B)
    except RuntimeError as exc:
        logger.error(f"Distributor referral code generation failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate referral code. Please try again.",
        )

    try:
        hashed_pwd = hash_password(payload.password)
        new_distributor = User(
            full_name=payload.full_name,
            phone=clean_phone,
            password_hash=hashed_pwd,
            role=UserRole.CUSTOMER,
            programme=Programme.PLAN_B,
            account_status=AccountStatus.ACTIVE,
            referral_code=referral_code,
            referred_by_id=None,
            is_active=True,
        )
        db.add(new_distributor)
        db.flush()

        wallet_direct = Wallet(
            user_id=new_distributor.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            balance=Decimal("0.00"),
            total_withdrawn=Decimal("0.00"),
        )
        wallet_sequential = Wallet(
            user_id=new_distributor.id,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            balance=Decimal("0.00"),
            total_withdrawn=Decimal("0.00"),
        )
        db.add_all([wallet_direct, wallet_sequential])
        db.flush()

        db.commit()
        db.refresh(new_distributor)
    except IntegrityError as exc:
        db.rollback()
        logger.warning(f"Registration race condition on phone {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this mobile number or referral code already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error registering distributor {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating your account.",
        )

    logger.info(
        f"Plan B distributor registered (ID: {new_distributor.id}, Phone: {_mask_phone(clean_phone)}, Referral: {referral_code})."
    )
    return CustomerRegisterResponse.model_validate(new_distributor)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in Plan B distributor using phone and password",
)
@router.post(
    "/login/password",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in Plan B distributor using phone and password",
)
def login_distributor_via_password(
    payload: CustomerPasswordLoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate Plan B distributor via password and issue access JWT.

    Enforces:
      - Plan A credentials cannot log into Plan B portal (RG-12).
      - Deactivated distributors cannot log in (403 Forbidden).
      - Blocked distributors CAN log in and view their account (200 OK).
    """
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    distributor = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not distributor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mobile number or password.",
        )

    # Programme portal separation (RG-12)
    if distributor.programme != Programme.PLAN_B:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials for Plan B distributor portal. Plan A customers must log in via the customer portal.",
        )

    # Deactivated distributors cannot log in
    if distributor.account_status == AccountStatus.DEACTIVATED or not distributor.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Distributor account is deactivated.",
        )

    # Note: BLOCKED distributors ARE allowed to log in and view their account (RG-14)

    if distributor.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No password configured. Please log in via OTP or use password reset.",
        )

    if not verify_password(payload.password, distributor.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mobile number or password.",
        )

    access_token = create_access_token(
        user_id=distributor.id,
        role=distributor.role.value,
        phone=distributor.phone,
        extra_claims={
            "programme": distributor.programme.value,
            "account_status": distributor.account_status.value,
        },
    )

    logger.info(f"Distributor logged in via password (ID: {distributor.id}, Phone: {_mask_phone(clean_phone)}).")
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=distributor.role,
        programme=distributor.programme,
        account_status=distributor.account_status,
    )


@router.post(
    "/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a login OTP for an existing Plan B distributor",
)
def request_distributor_login_otp(
    payload: CustomerOTPRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate and send a single-use login OTP for a Plan B distributor."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    distributor = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not distributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Distributor account not found. Please register first.",
        )

    if distributor.programme != Programme.PLAN_B:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials for Plan B distributor portal.",
        )

    if distributor.account_status == AccountStatus.DEACTIVATED or not distributor.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Distributor account is deactivated.",
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
        logger.error(f"Error creating distributor login OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate login OTP. Please try again.",
        )

    response_data: Dict[str, Any] = {
        "message": f"OTP successfully sent to +91 {_mask_phone(clean_phone)}.",
        "expires_in_minutes": 5,
    }

    if settings.ENVIRONMENT.lower() == "development":
        response_data["dev_otp"] = settings.DEV_OTP_CODE

    return response_data


@router.post(
    "/login/otp",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in Plan B distributor using phone and OTP",
)
def login_distributor_via_otp(
    payload: CustomerOTPVerifyRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify single-use login OTP for Plan B distributor and issue access JWT."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    distributor = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not distributor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    if distributor.programme != Programme.PLAN_B:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials for Plan B distributor portal.",
        )

    if distributor.account_status == AccountStatus.DEACTIVATED or not distributor.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Distributor account is deactivated.",
        )

    try:
        is_valid = verify_otp(db, clean_phone, OTPPurpose.LOGIN, payload.otp_code)
        if not is_valid:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired OTP code.",
            )
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error verifying distributor OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification error occurred. Please try again.",
        )

    access_token = create_access_token(
        user_id=distributor.id,
        role=distributor.role.value,
        phone=distributor.phone,
        extra_claims={
            "programme": distributor.programme.value,
            "account_status": distributor.account_status.value,
        },
    )

    logger.info(f"Distributor logged in via OTP (ID: {distributor.id}, Phone: {_mask_phone(clean_phone)}).")
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=distributor.role,
        programme=distributor.programme,
        account_status=distributor.account_status,
    )


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_200_OK,
    summary="Request a password reset OTP for a Plan B distributor",
)
def request_distributor_password_reset_otp(
    payload: CustomerPasswordResetRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate and send an OTP for distributor password reset."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    distributor = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not distributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Distributor account not found.",
        )

    if distributor.programme != Programme.PLAN_B:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials for Plan B distributor portal.",
        )

    if distributor.account_status == AccountStatus.DEACTIVATED or not distributor.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Distributor account is deactivated.",
        )

    try:
        otp_record = create_otp(db, clean_phone, OTPPurpose.PASSWORD_RESET)
        db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Error creating distributor password reset OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate password reset OTP. Please try again.",
        )

    response_data: Dict[str, Any] = {
        "message": f"Password reset OTP sent to +91 {_mask_phone(clean_phone)}.",
        "expires_in_minutes": 5,
    }

    if settings.ENVIRONMENT.lower() == "development":
        response_data["dev_otp"] = settings.DEV_OTP_CODE

    return response_data


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_200_OK,
    summary="Confirm password reset using verified OTP for Plan B distributor",
)
def confirm_distributor_password_reset(
    payload: CustomerPasswordResetConfirmRequest,
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """Verify password reset OTP and update distributor account password hash."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    distributor = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not distributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Distributor account not found.",
        )

    if distributor.programme != Programme.PLAN_B:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials for Plan B distributor portal.",
        )

    if distributor.account_status == AccountStatus.DEACTIVATED or not distributor.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Distributor account is deactivated.",
        )

    try:
        is_valid = verify_otp(
            db, clean_phone, OTPPurpose.PASSWORD_RESET, payload.otp_code
        )
        if not is_valid:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OTP code.",
            )

        distributor.password_hash = hash_password(payload.new_password)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error resetting distributor password for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again.",
        )

    logger.info(f"Distributor password reset (ID: {distributor.id}, Phone: {_mask_phone(clean_phone)}).")
    return {"message": "Password has been successfully updated. You may now log in with your new password."}
