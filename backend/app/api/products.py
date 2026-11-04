import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product
from app.schemas.product import ProductListResponse, ProductResponse

router = APIRouter(prefix="/products", tags=["Public Products"])


@router.get(
    "",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="List active catalog products with pagination",
)
def list_active_products(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    """Retrieve paginated list of publicly active catalog products.

    Invariants:
      - Public access: No authentication required.
      - Filters strictly by is_active == True. Inactive products are hidden.
      - Enforces validated pagination: page >= 1, 1 <= page_size <= 100.
    """
    base_query = db.query(Product).filter(Product.is_active == True)  # noqa: E712
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
    summary="Fetch public details of a single active product",
)
def get_active_product_details(
    product_id: int,
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Retrieve full public details for a single active catalog item.

    Invariants:
      - Public access: No authentication required.
      - Returns HTTP 404 if the product does not exist or is inactive.
    """
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.is_active == True)  # noqa: E712
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return ProductResponse.model_validate(product)

