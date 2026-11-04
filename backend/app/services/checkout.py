from datetime import datetime
from decimal import Decimal
import logging
import secrets
from typing import List, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.cart import CartItem
from app.models.enums import OrderStatus, PaymentStatus, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User
from app.schemas.order import CheckoutRequest
from app.services.allocation import calculate_and_create_order_allocation

logger = logging.getLogger("shopeasy.checkout")


def execute_checkout(
    db: Session,
    customer: User,
    checkout_data: CheckoutRequest,
) -> Order:
    """Execute customer checkout, atomic inventory decrement, and immutable allocation snapshot.

    Workflow:
      1. Validate delivery address ownership.
      2. Fetch customer cart items (cart is the sole order source).
      3. Check idempotency constraint.
      4. Re-fetch all products with row-level locks, validate stock, and decrement atomically.
      5. Validate optional referral code (reject self-referral, admin codes, non-existent codes).
      6. Determine first successful order status and record permanent referral attribution if applicable.
      7. Simulate payment execution (PaymentStatus.COMPLETED).
      8. Persist Order and OrderItem snapshots with immutable unit prices.
      9. Generate immutable OrderAllocation snapshot across Scenarios A, B, C, D.
      10. Clear customer cart only upon successful completion.
      11. Roll back stock decrement and preserve cart if any step fails.
    """
    # 1. Idempotency Check: if this customer already completed an order with this idempotency key,
    # return the original confirmed order response directly without duplicate operations.
    existing_order = (
        db.query(Order)
        .options(
            joinedload(Order.order_items),
            joinedload(Order.order_allocation),
            joinedload(Order.address),
        )
        .filter(
            Order.user_id == customer.id,
            Order.idempotency_key == checkout_data.idempotency_key,
        )
        .first()
    )
    if existing_order:
        logger.info(
            f"Idempotent retry for customer #{customer.id} with key '{checkout_data.idempotency_key}': "
            f"returning existing confirmed order #{existing_order.id}"
        )
        return existing_order

    # 2. Validate delivery address
    address = (
        db.query(Address)
        .filter(
            Address.id == checkout_data.address_id,
            Address.user_id == customer.id,
        )
        .first()
    )
    if not address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid delivery address selected. Address does not exist or belongs to another user.",
        )

    # 3. Fetch cart items
    cart_items = (
        db.query(CartItem)
        .filter(CartItem.user_id == customer.id)
        .all()
    )
    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot checkout with an empty cart. Please add items to your cart first.",
        )

    try:
        # 4. Re-fetch products with row-level locking (SELECT ... FOR UPDATE) and atomic stock check
        items_with_products: List[Tuple[int, Product]] = []
        for cart_item in cart_items:
            product = (
                db.query(Product)
                .filter(Product.id == cart_item.product_id)
                .with_for_update()
                .first()
            )
            if not product or not product.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product #{cart_item.product_id} is inactive or no longer available.",
                )
            if product.stock < cart_item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Insufficient stock for product '{product.name}'. "
                        f"Available: {product.stock}, requested: {cart_item.quantity}."
                    ),
                )

            # Atomically decrement stock
            product.stock -= cart_item.quantity
            items_with_products.append((cart_item.quantity, product))

        # 5. Compute order total amount strictly from current database prices
        order_total_amount = sum(
            Decimal(qty) * prod.price for qty, prod in items_with_products
        )

        # 6. Referral code validation and first successful order attribution
        prior_confirmed_orders = (
            db.query(Order.id)
            .filter(
                Order.user_id == customer.id,
                Order.order_status == OrderStatus.CONFIRMED,
            )
            .count()
        )
        is_first_successful_order = (prior_confirmed_orders == 0)

        applied_referral_code = None
        code_input = checkout_data.referral_code.strip() if checkout_data.referral_code else None

        if code_input:
            # Check self-referral using customer's own referral code
            if customer.referral_code and code_input.upper() == customer.referral_code.upper():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Self-referral is strictly prohibited. You cannot use your own referral code.",
                )

            # Query referrer
            referrer = (
                db.query(User)
                .filter(func.upper(User.referral_code) == code_input.upper())
                .first()
            )
            if not referrer:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid referral code. Referrer does not exist.",
                )

            # Prohibit self-referral by user ID
            if referrer.id == customer.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Self-referral is strictly prohibited.",
                )

            # Prohibit admin referral codes
            if referrer.role != UserRole.CUSTOMER:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid referral code. Administrator referral codes cannot be used.",
                )

            # Check referrer active status
            if not referrer.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referral code owner account is inactive.",
                )

            if is_first_successful_order:
                # Permanent attribution established on first successful order
                applied_referral_code = referrer.referral_code
                if customer.referred_by_id is None:
                    customer.referred_by_id = referrer.id
            else:
                # Repeat order: referral codes cannot be altered or re-established
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referral attribution is only applicable on your first successful order and cannot be modified.",
                )
        else:
            # No referral code supplied
            applied_referral_code = None

        # 7. Simulated payment execution
        payment_status = PaymentStatus.COMPLETED
        order_status = OrderStatus.CONFIRMED
        payment_reference = f"SIM-{secrets.token_hex(8).upper()}"
        order_number = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"

        # 8. Create Order record
        order = Order(
            order_number=order_number,
            idempotency_key=checkout_data.idempotency_key,
            user_id=customer.id,
            address_id=address.id,
            total_amount=order_total_amount,
            order_status=order_status,
            payment_status=payment_status,
            payment_reference=payment_reference,
            applied_referral_code=applied_referral_code,
            is_first_successful_order=is_first_successful_order,
        )
        db.add(order)
        db.flush()

        # 9. Create OrderItem records
        for qty, prod in items_with_products:
            order_item = OrderItem(
                order_id=order.id,
                product_id=prod.id,
                product_name=prod.name,
                unit_price=prod.price,
                quantity=qty,
                line_total=Decimal(qty) * prod.price,
            )
            db.add(order_item)
        db.flush()

        # 10. Generate immutable OrderAllocation snapshot
        calculate_and_create_order_allocation(
            db=db,
            order=order,
            items_with_products=items_with_products,
            buyer_id=customer.id,
            is_first_successful_order=is_first_successful_order,
            has_valid_referral_code=(applied_referral_code is not None),
        )

        # 11. Clear customer cart only upon successful order confirmation
        db.query(CartItem).filter(CartItem.user_id == customer.id).delete()

        # 12. Commit transaction
        db.commit()
        db.refresh(order)
        # Touch relationships to ensure loaded in session
        _ = order.order_items
        _ = order.order_allocation
        _ = order.address

        logger.info(
            f"Successfully placed order #{order.id} ({order.order_number}) "
            f"for customer #{customer.id}: amount={order.total_amount}"
        )
        return order

    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        logger.error(f"Financial allocation error during checkout: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except IntegrityError as exc:
        db.rollback()
        err_msg = str(exc)
        if "uq_orders_user_idempotency" in err_msg or "idempotency_key" in err_msg:
            # Concurrent race condition: competing transaction committed an order with this key.
            # Retrieve and return that committed order!
            concurrent_order = (
                db.query(Order)
                .options(
                    joinedload(Order.order_items),
                    joinedload(Order.order_allocation),
                    joinedload(Order.address),
                )
                .filter(
                    Order.user_id == customer.id,
                    Order.idempotency_key == checkout_data.idempotency_key,
                )
                .first()
            )
            if concurrent_order:
                logger.info(
                    f"Resolved concurrent collision for customer #{customer.id} with key '{checkout_data.idempotency_key}': "
                    f"returning committed order #{concurrent_order.id}"
                )
                return concurrent_order
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A concurrent order with this idempotency key was processed. Please retry.",
            )
        logger.error(f"IntegrityError during checkout: {err_msg}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order processing conflict. Please retry.",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error during checkout: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process order checkout. Please try again.",
        )
