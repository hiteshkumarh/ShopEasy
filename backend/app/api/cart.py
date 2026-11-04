from decimal import Decimal
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.cart import CartItem
from app.models.product import Product
from app.models.user import User
from app.schemas.cart import (
    CartItemAddRequest,
    CartItemResponse,
    CartItemUpdateRequest,
    CartResponse,
)

logger = logging.getLogger("shopeasy.cart")

router = APIRouter(prefix="/cart", tags=["Cart"])


def _build_cart_response(db: Session, user_id: int) -> CartResponse:
    """Build cart presentation recalculating line totals strictly from current database prices."""
    items = (
        db.query(CartItem)
        .filter(CartItem.user_id == user_id)
        .order_by(CartItem.id.asc())
        .all()
    )

    cart_item_responses: List[CartItemResponse] = []
    subtotal = Decimal("0.00")
    total_items = 0

    for item in items:
        prod = item.product
        line_total = prod.price * Decimal(item.quantity)
        subtotal += line_total
        total_items += item.quantity
        cart_item_responses.append(
            CartItemResponse(
                id=item.id,
                product_id=prod.id,
                product_name=prod.name,
                product_code=prod.product_code,
                unit_price=prod.price,
                quantity=item.quantity,
                line_total=line_total,
                stock=prod.stock,
                is_active=prod.is_active,
                is_power_bank=prod.is_power_bank,
                image_url=prod.image_url,
            )
        )

    return CartResponse(
        items=cart_item_responses,
        total_items=total_items,
        subtotal=subtotal,
    )


@router.get("", response_model=CartResponse)
def get_cart(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve the authenticated customer's shopping cart with database-calculated prices."""
    return _build_cart_response(db, current_user.id)


@router.post("", response_model=CartResponse, status_code=status.HTTP_200_OK)
def add_to_cart(
    payload: CartItemAddRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Add a product to the authenticated customer's persistent cart, or increment quantity."""
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )
    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This product is currently inactive and cannot be added to cart.",
        )

    # Check existing cart item for this user and product
    existing_item = (
        db.query(CartItem)
        .filter(
            CartItem.user_id == current_user.id,
            CartItem.product_id == payload.product_id,
        )
        .first()
    )

    new_quantity = payload.quantity
    if existing_item:
        new_quantity += existing_item.quantity

    if new_quantity > product.stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Requested total quantity ({new_quantity}) exceeds available stock ({product.stock})."
            ),
        )

    if existing_item:
        existing_item.quantity = new_quantity
    else:
        new_item = CartItem(
            user_id=current_user.id,
            product_id=product.id,
            quantity=payload.quantity,
        )
        db.add(new_item)

    db.commit()
    logger.info(
        f"User #{current_user.id} added product #{product.id} to cart (qty: {new_quantity})"
    )
    return _build_cart_response(db, current_user.id)


@router.put("/{item_id}", response_model=CartResponse)
def update_cart_item(
    item_id: int,
    payload: CartItemUpdateRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Update quantity of an existing cart item for the authenticated customer."""
    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.id == item_id,
            CartItem.user_id == current_user.id,
        )
        .first()
    )
    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found.",
        )

    product = cart_item.product
    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This product is currently inactive and cannot be retained in cart.",
        )

    if payload.quantity > product.stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Requested quantity ({payload.quantity}) exceeds available stock ({product.stock})."
            ),
        )

    cart_item.quantity = payload.quantity
    db.commit()

    logger.info(
        f"User #{current_user.id} updated cart item #{item_id} to quantity {payload.quantity}"
    )
    return _build_cart_response(db, current_user.id)


@router.delete("/{item_id}", response_model=CartResponse)
def remove_cart_item(
    item_id: int,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Remove a single item from the authenticated customer's shopping cart."""
    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.id == item_id,
            CartItem.user_id == current_user.id,
        )
        .first()
    )
    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found.",
        )

    db.delete(cart_item)
    db.commit()

    logger.info(f"User #{current_user.id} removed cart item #{item_id}")
    return _build_cart_response(db, current_user.id)


@router.delete("", status_code=status.HTTP_200_OK)
def clear_cart(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Clear all items from the authenticated customer's shopping cart."""
    deleted_count = (
        db.query(CartItem)
        .filter(CartItem.user_id == current_user.id)
        .delete()
    )
    db.commit()

    logger.info(f"User #{current_user.id} cleared {deleted_count} cart items")
    return {"message": "Cart cleared successfully."}

