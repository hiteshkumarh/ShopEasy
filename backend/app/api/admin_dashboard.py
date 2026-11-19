import base64
from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
import re
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.billing import BillingId
from app.models.enums import OrderStatus, UserRole, WithdrawalStatus
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.models.wallet import Wallet, WalletFreezeHistory, Withdrawal
from app.schemas.wallet import (
    AdminWalletFreezeByPhoneRequest,
    AdminWalletFreezeByPhoneResponse,
    AdminWalletFreezeRequest,
    AdminWalletUnfreezeByPhoneRequest,
    AdminWithdrawalReviewRequest,
    UserWalletsLookupResponse,
    UserWalletSummary,
    WalletFreezeHistoryResponse,
    WithdrawalResponse,
)
from app.services.wallet_service import (
    admin_approve_withdrawal,
    admin_reject_withdrawal,
    freeze_wallet,
    unfreeze_wallet,
)

logger = logging.getLogger("shopeasy.admin.dashboard")

router = APIRouter(
    prefix="/admin",
    tags=["Admin Dashboard and Management"],
    dependencies=[Depends(require_admin)],
)


class AdminDashboardStatsResponse(BaseModel):
    total_products: int
    total_orders: int
    total_customers: int
    total_revenue: Decimal
    total_items_sold: int = 0

    model_config = ConfigDict(from_attributes=True)


class AdminOrderItemDTO(BaseModel):
    id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    model_config = ConfigDict(from_attributes=True)


class AdminOrderDTO(BaseModel):
    id: int
    order_number: str
    billing_id: Optional[str] = None
    billing_ids: List[str] = []
    customer_name: str
    customer_phone: str
    total_amount: Decimal
    order_status: str
    payment_status: str
    created_at: datetime
    items: List[AdminOrderItemDTO] = []

    model_config = ConfigDict(from_attributes=True)


class AdminOrderListResponse(BaseModel):
    total: int
    items: List[AdminOrderDTO]

    model_config = ConfigDict(from_attributes=True)


class AdminCustomerDTO(BaseModel):
    id: int
    full_name: str
    phone: str
    referral_code: Optional[str] = None
    created_at: datetime
    is_active: bool
    total_orders: int
    total_spent: Decimal

    model_config = ConfigDict(from_attributes=True)


class AdminCustomerListResponse(BaseModel):
    total: int
    items: List[AdminCustomerDTO]

    model_config = ConfigDict(from_attributes=True)


@router.get(
    "/dashboard/stats",
    response_model=AdminDashboardStatsResponse,
    summary="Get real-time statistics for admin dashboard",
)
def get_admin_dashboard_stats(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminDashboardStatsResponse:
    """Return live metrics from the database:
    - total_products: count of catalog products
    - total_customers: count of users with role='customer' (excludes admin)
    - total_orders: count of successful confirmed orders
    - total_revenue: sum of total_amount for successful confirmed orders
    """
    total_products = db.query(Product).count()
    total_customers = db.query(User).filter(User.role == UserRole.CUSTOMER).count()
    total_orders = (
        db.query(Order).filter(Order.order_status == OrderStatus.CONFIRMED).count()
    )
    total_revenue = (
        db.query(func.coalesce(func.sum(Order.total_amount), Decimal("0.00")))
        .filter(Order.order_status == OrderStatus.CONFIRMED)
        .scalar()
    )
    total_items_sold = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.order_status == OrderStatus.CONFIRMED)
        .scalar()
    )

    return AdminDashboardStatsResponse(
        total_products=total_products,
        total_orders=total_orders,
        total_customers=total_customers,
        total_revenue=total_revenue or Decimal("0.00"),
        total_items_sold=int(total_items_sold or 0),
    )


@router.get(
    "/orders",
    response_model=AdminOrderListResponse,
    summary="List all customer orders for admin inspection",
)
def get_admin_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Optional search by Order ID, Order Number, or Billing ID"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminOrderListResponse:
    """Retrieve all customer orders with buyer details, snapshot items, and company Billing IDs."""
    query = (
        db.query(Order)
        .options(
            joinedload(Order.user),
            joinedload(Order.order_items),
            joinedload(Order.billing_ids),
        )
        .order_by(Order.created_at.desc())
    )

    if search and search.strip():
        s = search.strip()
        conds = [Order.order_number.ilike(f"%{s}%")]
        if s.isdigit():
            conds.append(Order.id == int(s))
        conds.append(Order.billing_ids.any(BillingId.billing_number.ilike(f"%{s}%")))
        conds.append(Order.user.has(User.phone.ilike(f"%{s}%")))
        conds.append(Order.user.has(User.full_name.ilike(f"%{s}%")))
        query = query.filter(or_(*conds))

    total = query.count()
    orders = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for o in orders:
        order_bids = [b.billing_number for b in o.billing_ids if b.billing_number]
        b_id_str = ", ".join(order_bids) if order_bids else None

        items.append(
            AdminOrderDTO(
                id=o.id,
                order_number=o.order_number,
                billing_id=b_id_str,
                billing_ids=order_bids,
                customer_name=o.user.full_name if o.user else "Unknown Customer",
                customer_phone=o.user.phone if o.user else "N/A",
                total_amount=o.total_amount,
                order_status=o.order_status.value if hasattr(o.order_status, "value") else str(o.order_status),
                payment_status=o.payment_status.value if hasattr(o.payment_status, "value") else str(o.payment_status),
                created_at=o.created_at,
                items=[
                    AdminOrderItemDTO(
                        id=i.id,
                        product_name=i.product_name,
                        quantity=i.quantity,
                        unit_price=i.unit_price,
                        line_total=i.line_total,
                    )
                    for i in o.order_items
                ],
            )
        )

    return AdminOrderListResponse(total=total, items=items)


@router.get(
    "/customers",
    response_model=AdminCustomerListResponse,
    summary="List registered customer accounts (excluding admins)",
)
def get_admin_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminCustomerListResponse:
    """Retrieve registered customer accounts, strictly excluding administrators."""
    query = (
        db.query(User)
        .filter(User.role == UserRole.CUSTOMER)
        .order_by(User.created_at.desc())
    )

    total = query.count()
    customers = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for c in customers:
        # Calculate customer total orders and total spend from confirmed orders
        orders_info = (
            db.query(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), Decimal("0.00")),
            )
            .filter(
                Order.user_id == c.id,
                Order.order_status == OrderStatus.CONFIRMED,
            )
            .first()
        )
        ord_count = orders_info[0] if orders_info else 0
        total_spent = orders_info[1] if orders_info else Decimal("0.00")

        items.append(
            AdminCustomerDTO(
                id=c.id,
                full_name=c.full_name,
                phone=c.phone,
                referral_code=c.referral_code,
                created_at=c.created_at,
                is_active=c.is_active,
                total_orders=ord_count,
                total_spent=total_spent,
            )
        )

    return AdminCustomerListResponse(total=total, items=items)


class UploadImageRequest(BaseModel):
    filename: str
    base64_data: str


@router.post(
    "/upload-image",
    summary="Upload product image file (base64 encoded)",
)
def upload_product_image(
    payload: UploadImageRequest,
    current_admin: User = Depends(require_admin),
):
    """Save an uploaded image to frontend/uploads/ and return its relative URL."""
    ext = Path(payload.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        ext = ".jpg"

    base64_str = payload.base64_data
    if "," in base64_str:
        base64_str = base64_str.split(",", 1)[1]

    try:
        file_bytes = base64.b64decode(base64_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 image data.",
        )

    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image file exceeds maximum 10MB limit.",
        )

    # Save file to frontend/uploads
    backend_dir = Path(__file__).resolve().parent.parent.parent
    upload_dir = backend_dir.parent / "frontend" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(payload.filename).stem)[:30]
    unique_filename = f"{clean_name}_{uuid.uuid4().hex[:8]}{ext}"
    target_path = upload_dir / unique_filename

    with open(target_path, "wb") as f:
        f.write(file_bytes)

    return {"url": f"/uploads/{unique_filename}"}


# --------------------------------------------------------------------------
# WP-9: Administrative Withdrawal Review and Wallet Freeze Management
# --------------------------------------------------------------------------

@router.get(
    "/withdrawals/pending",
    response_model=List[WithdrawalResponse],
    summary="List pending withdrawal requests requiring administrative review",
)
def list_pending_withdrawals(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Retrieve all withdrawal requests in REQUESTED status (e.g. from blocked distributors)."""
    pending = (
        db.query(Withdrawal)
        .options(joinedload(Withdrawal.wallet))
        .filter(Withdrawal.status == WithdrawalStatus.REQUESTED)
        .order_by(Withdrawal.requested_at.asc(), Withdrawal.id.asc())
        .all()
    )
    return [WithdrawalResponse.model_validate(w) for w in pending]


@router.post(
    "/withdrawals/{withdrawal_id}/approve",
    response_model=WithdrawalResponse,
    summary="Approve a pending withdrawal for a blocked distributor",
)
def approve_pending_withdrawal(
    withdrawal_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve a REQUESTED withdrawal, debiting the wallet and issuing a simulated payout receipt."""
    try:
        withdrawal = admin_approve_withdrawal(
            db=db,
            withdrawal_id=withdrawal_id,
            admin_id=current_admin.id,
        )
        db.commit()
        db.refresh(withdrawal)
        if not withdrawal.wallet:
            withdrawal.wallet = db.query(Wallet).filter(Wallet.id == withdrawal.wallet_id).first()
        return WithdrawalResponse.model_validate(withdrawal)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error approving withdrawal #{withdrawal_id}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve withdrawal.",
        )


@router.post(
    "/withdrawals/{withdrawal_id}/reject",
    response_model=WithdrawalResponse,
    summary="Reject a pending withdrawal for a blocked distributor",
)
def reject_pending_withdrawal(
    withdrawal_id: int,
    payload: AdminWithdrawalReviewRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reject a REQUESTED withdrawal with a mandatory reason. Funds remain in user wallet."""
    try:
        withdrawal = admin_reject_withdrawal(
            db=db,
            withdrawal_id=withdrawal_id,
            admin_id=current_admin.id,
            reason=payload.reason or "",
        )
        db.commit()
        db.refresh(withdrawal)
        if not withdrawal.wallet:
            withdrawal.wallet = db.query(Wallet).filter(Wallet.id == withdrawal.wallet_id).first()
        return WithdrawalResponse.model_validate(withdrawal)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error rejecting withdrawal #{withdrawal_id}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject withdrawal.",
        )


@router.post(
    "/wallets/{wallet_id}/freeze",
    response_model=dict,
    summary="Freeze a wallet to block further withdrawal requests",
)
def freeze_customer_wallet(
    wallet_id: int,
    payload: AdminWalletFreezeRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Freeze a customer wallet and record audit history."""
    try:
        wallet = freeze_wallet(
            db=db,
            wallet_id=wallet_id,
            admin_id=current_admin.id,
            reason=payload.reason,
        )
        db.commit()
        return {
            "status": "success",
            "message": f"Wallet #{wallet.id} frozen successfully.",
            "wallet_id": wallet.id,
            "is_frozen": wallet.is_frozen,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error freezing wallet #{wallet_id}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to freeze wallet.",
        )


@router.post(
    "/wallets/{wallet_id}/unfreeze",
    response_model=dict,
    summary="Unfreeze a customer wallet to allow withdrawals",
)
def unfreeze_customer_wallet(
    wallet_id: int,
    payload: Optional[AdminWithdrawalReviewRequest] = None,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unfreeze a customer wallet and record audit history."""
    try:
        reason = payload.reason if payload else "Administrative unfreeze"
        wallet = unfreeze_wallet(
            db=db,
            wallet_id=wallet_id,
            admin_id=current_admin.id,
            reason=reason,
        )
        db.commit()
        return {
            "status": "success",
            "message": f"Wallet #{wallet.id} unfrozen successfully.",
            "wallet_id": wallet.id,
            "is_frozen": wallet.is_frozen,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error unfreezing wallet #{wallet_id}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unfreeze wallet.",
        )


@router.get(
    "/wallets/{wallet_id}/freeze-history",
    response_model=List[WalletFreezeHistoryResponse],
    summary="Retrieve audit trail for wallet freeze/unfreeze actions",
)
def get_wallet_freeze_history(
    wallet_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Retrieve chronologically ordered freeze/unfreeze audit logs for a wallet."""
    history = (
        db.query(WalletFreezeHistory)
        .filter(WalletFreezeHistory.wallet_id == wallet_id)
        .order_by(WalletFreezeHistory.created_at.desc(), WalletFreezeHistory.id.desc())
        .all()
    )
    return [WalletFreezeHistoryResponse.model_validate(h) for h in history]


# --------------------------------------------------------------------------
# User-Number-to-Wallet Freeze & Unfreeze Resolution (Prompt 11)
# --------------------------------------------------------------------------

def _resolve_user_by_number(db: Session, user_number: str) -> User:
    """Resolve customer or distributor User entity by raw, cleaned, 10-digit mobile number, or User ID."""
    raw = (user_number or "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User identifier (registered mobile number or User ID) cannot be empty.",
        )
    clean_digits = re.sub(r"\D", "", raw)
    if not clean_digits:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User identifier must contain numeric digits.",
        )

    conditions = [User.phone == raw, User.phone == clean_digits]
    if clean_digits.isdigit():
        conditions.append(User.id == int(clean_digits))
    if len(clean_digits) >= 10:
        last10 = clean_digits[-10:]
        conditions.append(User.phone == last10)
        conditions.append(User.phone == f"+91{last10}")
        conditions.append(User.phone.like(f"%{last10}"))

    user = db.query(User).filter(or_(*conditions)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with mobile number '{raw}' not found.",
        )
    return user


@router.get(
    "/wallets/lookup-by-user-number",
    response_model=UserWalletsLookupResponse,
    summary="Look up user identification and associated wallets by registered mobile number",
)
def lookup_wallets_by_user_number(
    user_number: str = Query(..., description="Customer or distributor registered mobile number"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Resolve a user and their associated wallets using their registered mobile number."""
    user = _resolve_user_by_number(db, user_number)
    wallets = (
        db.query(Wallet)
        .filter(Wallet.user_id == user.id)
        .order_by(Wallet.id.asc())
        .all()
    )
    return UserWalletsLookupResponse(
        user_id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        programme=user.programme.value if (user.programme and hasattr(user.programme, "value")) else (str(user.programme) if user.programme else None),
        account_status=user.account_status.value if (user.account_status and hasattr(user.account_status, "value")) else (str(user.account_status) if user.account_status else None),
        wallets=[UserWalletSummary.model_validate(w) for w in wallets],
    )


@router.post(
    "/wallets/freeze-by-user-number",
    response_model=AdminWalletFreezeByPhoneResponse,
    summary="Freeze a customer or distributor wallet identified by registered mobile number",
)
def freeze_wallet_by_user_number(
    payload: AdminWalletFreezeByPhoneRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Freeze a user's wallet with mandatory reason using their registered mobile number."""
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A reason is mandatory for freezing a wallet.",
        )

    user = _resolve_user_by_number(db, payload.user_number)
    wallets = (
        db.query(Wallet)
        .filter(Wallet.user_id == user.id)
        .order_by(Wallet.id.asc())
        .all()
    )

    if not wallets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No associated wallets found for user '{user.full_name}' ({user.phone}).",
        )

    target_wallet = None
    if payload.wallet_id is not None:
        target_wallet = next((w for w in wallets if w.id == payload.wallet_id), None)
        if not target_wallet:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Wallet #{payload.wallet_id} does not belong to user '{user.full_name}' ({user.phone}).",
            )
    else:
        if len(wallets) == 1:
            target_wallet = wallets[0]
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Multiple wallets found for user '{user.full_name}'. Please select a specific wallet to freeze.",
                headers={"X-Multiple-Wallets": "true"},
            )

    try:
        frozen_wallet = freeze_wallet(
            db=db,
            wallet_id=target_wallet.id,
            admin_id=current_admin.id,
            reason=payload.reason.strip(),
        )
        db.commit()
        return AdminWalletFreezeByPhoneResponse(
            status="success",
            message=f"Wallet #{frozen_wallet.id} ({frozen_wallet.wallet_type.value if hasattr(frozen_wallet.wallet_type, 'value') else frozen_wallet.wallet_type}) for {user.full_name} ({user.phone}) frozen successfully.",
            wallet_id=frozen_wallet.id,
            is_frozen=frozen_wallet.is_frozen,
            user={
                "id": user.id,
                "full_name": user.full_name,
                "phone": user.phone,
                "role": user.role.value if hasattr(user.role, "value") else str(user.role),
                "programme": user.programme.value if user.programme else None,
            },
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error freezing wallet by phone: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to freeze wallet.",
        )


@router.post(
    "/wallets/unfreeze-by-user-number",
    response_model=AdminWalletFreezeByPhoneResponse,
    summary="Unfreeze a customer or distributor wallet identified by registered mobile number",
)
def unfreeze_wallet_by_user_number(
    payload: AdminWalletUnfreezeByPhoneRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unfreeze a user's wallet using their registered mobile number."""
    user = _resolve_user_by_number(db, payload.user_number)
    wallets = (
        db.query(Wallet)
        .filter(Wallet.user_id == user.id)
        .order_by(Wallet.id.asc())
        .all()
    )

    if not wallets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No associated wallets found for user '{user.full_name}' ({user.phone}).",
        )

    target_wallet = None
    if payload.wallet_id is not None:
        target_wallet = next((w for w in wallets if w.id == payload.wallet_id), None)
        if not target_wallet:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Wallet #{payload.wallet_id} does not belong to user '{user.full_name}' ({user.phone}).",
            )
    else:
        if len(wallets) == 1:
            target_wallet = wallets[0]
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Multiple wallets found for user '{user.full_name}'. Please select a specific wallet to unfreeze.",
                headers={"X-Multiple-Wallets": "true"},
            )

    reason = payload.reason.strip() if payload.reason else "Administrative unfreeze"
    try:
        unfrozen_wallet = unfreeze_wallet(
            db=db,
            wallet_id=target_wallet.id,
            admin_id=current_admin.id,
            reason=reason,
        )
        db.commit()
        return AdminWalletFreezeByPhoneResponse(
            status="success",
            message=f"Wallet #{unfrozen_wallet.id} ({unfrozen_wallet.wallet_type.value if hasattr(unfrozen_wallet.wallet_type, 'value') else unfrozen_wallet.wallet_type}) for {user.full_name} ({user.phone}) unfrozen successfully.",
            wallet_id=unfrozen_wallet.id,
            is_frozen=unfrozen_wallet.is_frozen,
            user={
                "id": user.id,
                "full_name": user.full_name,
                "phone": user.phone,
                "role": user.role.value if hasattr(user.role, "value") else str(user.role),
                "programme": user.programme.value if user.programme else None,
            },
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Error unfreezing wallet by phone: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unfreeze wallet.",
        )


@router.get(
    "/wallets/freeze-history-by-user-number",
    response_model=List[WalletFreezeHistoryResponse],
    summary="Retrieve freeze/unfreeze audit logs for a user identified by registered mobile number",
)
def get_freeze_history_by_user_number(
    user_number: str = Query(..., description="Customer or distributor registered mobile number"),
    wallet_id: Optional[int] = Query(None, description="Optional wallet ID to filter audit records"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Retrieve chronologically ordered freeze/unfreeze audit logs for a user's wallet(s)."""
    user = _resolve_user_by_number(db, user_number)
    wallets = (
        db.query(Wallet)
        .filter(Wallet.user_id == user.id)
        .all()
    )

    if not wallets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No associated wallets found for user '{user.full_name}' ({user.phone}).",
        )

    wallet_ids = [w.id for w in wallets]
    if wallet_id is not None:
        if wallet_id not in wallet_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Wallet #{wallet_id} does not belong to user '{user.full_name}' ({user.phone}).",
            )
        target_ids = [wallet_id]
    else:
        target_ids = wallet_ids

    history = (
        db.query(WalletFreezeHistory)
        .filter(WalletFreezeHistory.wallet_id.in_(target_ids))
        .order_by(WalletFreezeHistory.created_at.desc(), WalletFreezeHistory.id.desc())
        .all()
    )
    return [WalletFreezeHistoryResponse.model_validate(h) for h in history]
