import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.order import Order
from app.models.user import User
from app.schemas.order import (
    CheckoutRequest,
    OrderListResponse,
    OrderResponse,
)
from app.services.checkout import execute_checkout

logger = logging.getLogger("shopeasy.orders")

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "/checkout",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def checkout(
    payload: CheckoutRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Execute customer checkout, payment simulation, and immutable allocation snapshot."""
    order = execute_checkout(
        db=db,
        customer=current_user,
        checkout_data=payload,
    )
    return order


@router.get("", response_model=OrderListResponse)
def list_orders(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve all confirmed orders placed by the authenticated customer."""
    orders = (
        db.query(Order)
        .options(
            joinedload(Order.order_items),
            joinedload(Order.order_allocation),
            joinedload(Order.address),
        )
        .filter(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return OrderListResponse(items=orders, total=len(orders))


@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(
    order_id: int,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve detailed order information for a specific order belonging to the customer."""
    order = (
        db.query(Order)
        .options(
            joinedload(Order.order_items),
            joinedload(Order.order_allocation),
            joinedload(Order.address),
        )
        .filter(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
        .first()
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )
    return order

