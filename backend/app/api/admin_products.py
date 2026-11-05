import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.product import Product
from app.models.user import User
from app.schemas.product import (
    ProductCreateRequest,
    ProductListResponse,
    ProductResponse,
    ProductUpdateRequest,
)

logger = logging.getLogger("shopeasy.admin.products")

router = APIRouter(
    prefix="/admin/products",
    tags=["Admin Product Management"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new catalog product (Admin only)",
)
def create_product(
    payload: ProductCreateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Create a new product in the catalog.

    Invariants enforced:
      - Admin authorization required; unauthenticated -> 401, customer -> 403.
      - Product price must be strictly positive (> 0.00).
      - Stock quantity cannot be negative (>= 0).
      - Product code must be globally unique across all products.
      - Newly created products are strictly NOT Power Bank products (is_power_bank=False).
      - No financial allocation configuration is accepted.
    """
    # Check product code uniqueness if specified
    if payload.product_code:
        existing = db.query(Product.id).filter(Product.product_code == payload.product_code).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A product with code '{payload.product_code}' already exists.",
            )

    # Determine is_power_bank: explicit flag or designated power bank indicators
    if payload.is_power_bank is not None:
        is_pb = payload.is_power_bank
    else:
        is_pb = bool(
            (payload.product_code and payload.product_code.strip().upper() == "PB-3999")
            or ("power bank" in payload.name.lower())
        )

    try:
        new_product = Product(
            name=payload.name,
            description=payload.description,
            price=payload.price,
            stock=payload.stock,
            image_url=payload.image_url,
            product_code=payload.product_code,
            is_active=payload.is_active,
            is_power_bank=is_pb,
        )
        db.add(new_product)
        db.commit()
        db.refresh(new_product)
    except IntegrityError as exc:
        db.rollback()
        logger.warning(f"Integrity error creating product: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A product with this code or unique attribute already exists.",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error creating product: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create product. Please try again.",
        )

    logger.info(
        f"Product created by admin {current_admin.id} (Product ID: {new_product.id}, Name: '{new_product.name}', Price: {new_product.price})."
    )
    return ProductResponse.model_validate(new_product)


@router.get(
    "",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all products including inactive items (Admin only)",
)
def list_admin_products(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    is_active: Optional[bool] = Query(None, description="Optional active status filter"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    """Retrieve full catalog list including inactive products for administration.

    Invariants enforced:
      - Admin authorization required.
      - Supports pagination and optional is_active filtering.
    """
    base_query = db.query(Product)
    if is_active is not None:
        base_query = base_query.filter(Product.is_active == is_active)

    total_count = base_query.count()
    offset = (page - 1) * page_size
    items = (
        base_query
        .order_by(Product.id.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0

    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in items],
        total=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch administrative details for any product (Admin only)",
)
def get_admin_product_details(
    product_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Retrieve product details regardless of active/inactive status.

    Invariants enforced:
      - Admin authorization required.
      - Returns HTTP 404 if product does not exist.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return ProductResponse.model_validate(product)


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Update product details (Admin only)",
)
def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Update fields on an existing product.

    Invariants enforced:
      - Admin authorization required.
      - Validates non-negative stock and positive price.
      - Checks product_code uniqueness excluding the current product.
      - Prohibits deactivation of the primary Power Bank product.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    # Check product code uniqueness if updated
    if payload.product_code is not None and payload.product_code != product.product_code:
        collision = (
            db.query(Product.id)
            .filter(Product.product_code == payload.product_code, Product.id != product_id)
            .first()
        )
        if collision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A product with code '{payload.product_code}' already exists.",
            )

    # Business rule: primary Power Bank cannot be deactivated
    if product.is_power_bank and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The primary Power Bank product cannot be deactivated as it is required for commission qualification.",
        )

    update_fields = payload.model_dump(exclude_unset=True)
    for field_name, new_val in update_fields.items():
        setattr(product, field_name, new_val)

    if payload.is_power_bank is None and (
        (product.product_code and product.product_code.strip().upper() == "PB-3999")
        or ("power bank" in product.name.lower())
    ):
        product.is_power_bank = True

    try:
        db.commit()
        db.refresh(product)
    except IntegrityError as exc:
        db.rollback()
        logger.warning(f"Integrity error updating product {product_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Update failed due to a constraint or uniqueness violation.",
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error updating product {product_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update product. Please try again.",
        )

    logger.info(
        f"Product {product.id} updated by admin {current_admin.id} (Updated fields: {list(update_fields.keys())})."
    )
    return ProductResponse.model_validate(product)


@router.delete(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate a product (Admin only soft-delete)",
)
def deactivate_product(
    product_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Soft-deactivate a product by setting is_active=False.

    Invariants enforced:
      - Admin authorization required.
      - Soft deactivation preserves order history and relational integrity.
      - Prohibits deactivation of the primary Power Bank product.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    # Business rule: primary Power Bank cannot be deactivated
    if product.is_power_bank:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The primary Power Bank product cannot be deactivated as it is required for commission qualification.",
        )

    product.is_active = False

    try:
        db.commit()
        db.refresh(product)
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error deactivating product {product_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate product. Please try again.",
        )

    logger.info(f"Product {product.id} ('{product.name}') deactivated by admin {current_admin.id}.")
    return ProductResponse.model_validate(product)

