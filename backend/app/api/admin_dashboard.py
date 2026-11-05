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
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User

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

    return AdminDashboardStatsResponse(
        total_products=total_products,
        total_orders=total_orders,
        total_customers=total_customers,
        total_revenue=total_revenue or Decimal("0.00"),
    )


@router.get(
    "/orders",
    response_model=AdminOrderListResponse,
    summary="List all customer orders for admin inspection",
)
def get_admin_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminOrderListResponse:
    """Retrieve all customer orders with buyer details and snapshot items."""
    query = (
        db.query(Order)
        .options(
            joinedload(Order.user),
            joinedload(Order.order_items),
        )
        .order_by(Order.created_at.desc())
    )

    total = query.count()
    orders = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for o in orders:
        items.append(
            AdminOrderDTO(
                id=o.id,
                order_number=o.order_number,
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
