from decimal import Decimal
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import OTPPurpose, UserRole, WalletType
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

logger = logging.getLogger("shopeasy.auth.customer")

router = APIRouter(prefix="/customer", tags=["Customer Authentication"])


@router.post(
    "/register",
    response_model=CustomerRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer account",
)
def register_customer(
    payload: CustomerRegisterRequest,
    db: Session = Depends(get_db),
) -> CustomerRegisterResponse:
    """Register a new customer account with automatic referral code and zero-balance wallets.

    Invariants enforced:
      - Accepts only full_name and 10-digit phone. Extra fields are rejected by schema.
      - Phone must be unique across all users.
      - Automatically generates a unique permanent referral code (REF + 6 chars).
      - Creates customer with role 'customer' and active status.
      - Sets password_hash to NULL initially.
      - Sets referred_by_id to NULL (referral attribution happens at checkout, not registration).
      - Creates both Direct Referral and Sequential Commission wallets with zero balances in the same transaction.
      - Does NOT insert the customer into the beneficiary queue during registration.
      - Never exposes password hashes.
    """
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Check phone uniqueness
    existing_user = db.query(User.id).filter(User.phone == clean_phone).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this mobile number already exists.",
        )

    # Generate collision-checked unique referral code
    try:
        referral_code = generate_referral_code(db)
    except RuntimeError as exc:
        logger.error(f"Referral code generation failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate referral code. Please try again.",
        )

    try:
        # 1. Create user entity
        new_customer = User(
            full_name=payload.full_name,
            phone=clean_phone,
            password_hash=None,
            role=UserRole.CUSTOMER,
            referral_code=referral_code,
            referred_by_id=None,
            is_active=True,
        )
        db.add(new_customer)
        db.flush()  # Assigns new_customer.id

        # 2. Create isolated earning wallets with zero balances
        wallet_direct = Wallet(
            user_id=new_customer.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            balance=Decimal("0.00"),
            total_withdrawn=Decimal("0.00"),
        )
        wallet_sequential = Wallet(
            user_id=new_customer.id,
            wallet_type=WalletType.SEQUENTIAL_COMMISSION,
            balance=Decimal("0.00"),
            total_withdrawn=Decimal("0.00"),
        )
        db.add_all([wallet_direct, wallet_sequential])
        db.flush()

        db.commit()
        db.refresh(new_customer)
    except IntegrityError as exc:
        db.rollback()
        logger.warning(f"Registration race condition on phone {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this mobile number or referral code already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error registering customer {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating your account.",
        )

    logger.info(
        f"Customer registered successfully (ID: {new_customer.id}, Phone: {_mask_phone(clean_phone)}, Referral: {referral_code})."
    )
    return CustomerRegisterResponse.model_validate(new_customer)


@router.post(
    "/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a login OTP for an existing customer",
)
def request_customer_login_otp(
    payload: CustomerOTPRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate and send a single-use login OTP for an existing active customer.

    Enforces 60-second cooldown and 5-minute expiry.
    In development, returns the configured mock DEV_OTP_CODE for convenience.
    In production, never exposes OTP codes in responses.
    """
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    customer = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer account not found. Please register first.",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is deactivated.",
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
        logger.error(f"Error creating login OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate login OTP. Please try again.",
        )

    response_data: Dict[str, Any] = {
        "message": f"OTP successfully sent to +91 {_mask_phone(clean_phone)}.",
        "expires_in_minutes": 5,
    }

    # Development convenience: expose configured mock OTP code
    if settings.ENVIRONMENT.lower() == "development":
        response_data["dev_otp"] = settings.DEV_OTP_CODE

    return response_data


@router.post(
    "/login/otp",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in customer using phone and OTP",
)
def login_customer_via_otp(
    payload: CustomerOTPVerifyRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify single-use login OTP and issue an access JWT."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    customer = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is deactivated.",
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
        logger.error(f"Error verifying OTP for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification error occurred. Please try again.",
        )

    access_token = create_access_token(
        user_id=customer.id,
        role=customer.role.value,
        phone=customer.phone,
    )

    logger.info(f"Customer logged in via OTP (ID: {customer.id}, Phone: {_mask_phone(clean_phone)}).")
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=customer.role,
    )


@router.post(
    "/login/password",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in customer using phone and password",
)
def login_customer_via_password(
    payload: CustomerPasswordLoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate customer via password and issue an access JWT."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    customer = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mobile number or password.",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is deactivated.",
        )

    if customer.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No password has been set for this account. Please log in via OTP or use password reset to configure a password.",
        )

    if not verify_password(payload.password, customer.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mobile number or password.",
        )

    access_token = create_access_token(
        user_id=customer.id,
        role=customer.role.value,
        phone=customer.phone,
    )

    logger.info(f"Customer logged in via password (ID: {customer.id}, Phone: {_mask_phone(clean_phone)}).")
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=customer.role,
    )


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_200_OK,
    summary="Request a password reset OTP for a customer",
)
def request_password_reset_otp(
    payload: CustomerPasswordResetRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate and send an OTP for customer password reset."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    customer = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer account not found.",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is deactivated.",
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
        logger.error(f"Error creating password reset OTP for {_mask_phone(clean_phone)}: {exc}")
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
    summary="Confirm password reset using verified OTP",
)
def confirm_password_reset(
    payload: CustomerPasswordResetConfirmRequest,
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """Verify password reset OTP and update account password hash."""
    try:
        clean_phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    customer = (
        db.query(User)
        .filter(User.phone == clean_phone, User.role == UserRole.CUSTOMER)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer account not found.",
        )

    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is deactivated.",
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

        # Hash new password securely with bcrypt (12 rounds)
        customer.password_hash = hash_password(payload.new_password)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error resetting password for {_mask_phone(clean_phone)}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again.",
        )

    logger.info(f"Password reset successfully for customer (ID: {customer.id}, Phone: {_mask_phone(clean_phone)}).")
    return {"message": "Password has been successfully updated. You may now log in with your new password."}

