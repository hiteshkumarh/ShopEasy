"""Admin API router for Unified Search (WP-11 Step 4 / OR-13).

Exposes:
- GET /admin/search?q={query}: Exact-match search across Plan A and Plan B by Billing ID or Order ID/Number.

Security & Invariants:
- Strictly requires administrator privileges (require_admin).
- Exact match only: substring, fuzzy, or wildcards produce zero false positive matches.
- Queries are bounded to max 64 characters; empty/whitespace queries are rejected with HTTP 400.
- Operations are strictly read-only; no financial, order, or distributor mutations.
- Every search records an audit log entry via AuditService.
- Does not expose passwords, password hashes, tokens, OTPs, secrets, or internal user data.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.billing import BillingId
from app.models.enums import Programme
from app.models.order import Order
from app.models.user import User
from app.schemas.admin_search import AdminSearchResponse, AdminSearchResultItem
from app.services.audit_service import AuditService

logger = logging.getLogger("shopeasy.admin.search")

router = APIRouter(
    prefix="/admin/search",
    tags=["Admin Unified Search"],
    dependencies=[Depends(require_admin)],
)

MAX_QUERY_LENGTH = 64


@router.get(
    "",
    response_model=AdminSearchResponse,
    summary="Unified exact-match search by Billing ID or Order ID across Plan A and Plan B (Admin only)",
)
def unified_admin_search(
    q: str = Query(..., description="Exact Billing ID or Order ID/Number to search"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminSearchResponse:
    """Perform exact-match lookup across Plan A and Plan B by Billing ID or Order ID.

    Invariants enforced:
      - Admin authorization required (HTTP 401 unauthenticated, HTTP 403 non-admin).
      - Bounded query: length between 1 and 64 characters (HTTP 400 on empty or excessive length).
      - Exact match only (no fuzzy/partial search).
      - Clearly programme-labelled results (PLAN_A or PLAN_B).
      - Immutable audit logging of search query.
      - Read-only: zero mutations to financial or business records.
    """
    query_clean = q.strip()
    if not query_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query cannot be empty or whitespace only.",
        )

    if len(query_clean) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Search query exceeds maximum permitted length of {MAX_QUERY_LENGTH} characters.",
        )

    results: List[AdminSearchResultItem] = []
    query_stripped = query_clean.lstrip("#").strip()
    is_numeric = query_clean.isdigit() or query_stripped.isdigit()
    numeric_val = int(query_stripped) if is_numeric else None

    # --------------------------------------------------------------------------
    # 1. Exact Match on Billing IDs (across Plan A & Plan B)
    # --------------------------------------------------------------------------
    billing_query = (
        db.query(BillingId)
        .options(
            joinedload(BillingId.order),
            joinedload(BillingId.user),
            joinedload(BillingId.product),
        )
    )

    billing_conds = [
        func.upper(BillingId.billing_number) == query_clean.upper(),
        func.upper(BillingId.billing_number) == query_stripped.upper(),
    ]
    if numeric_val is not None:
        billing_conds.extend([
            BillingId.id == numeric_val,
            BillingId.sequence_number == numeric_val,
        ])
    billing_query = billing_query.filter(or_(*billing_conds))

    matched_billing_ids = billing_query.all()

    for b in matched_billing_ids:
        results.append(
            AdminSearchResultItem(
                record_type="BILLING_ID",
                programme=b.programme,
                entity_id=b.id,
                identifier=b.billing_number,
                order_id=b.order_id,
                order_number=b.order.order_number if b.order else None,
                billing_number=b.billing_number,
                customer_id=b.user_id,
                customer_name=b.user.full_name if b.user else None,
                status=b.status,
                product_name=b.product.name if b.product else None,
                created_at=b.created_at,
                metadata={
                    "sequence_number": b.sequence_number,
                    "unit_index": b.unit_index,
                },
            )
        )

    # --------------------------------------------------------------------------
    # 2. Exact Match on Orders (across Plan A & Plan B)
    # --------------------------------------------------------------------------
    order_query = (
        db.query(Order)
        .options(
            joinedload(Order.user),
            joinedload(Order.billing_ids),
        )
    )

    order_conds = [
        func.upper(Order.order_number) == query_clean.upper(),
        func.upper(Order.order_number) == query_stripped.upper(),
    ]
    if numeric_val is not None:
        order_conds.append(Order.id == numeric_val)
    order_query = order_query.filter(or_(*order_conds))

    matched_orders = order_query.all()

    for o in matched_orders:
        # Determine programme from user or associated billing IDs
        order_programme = (
            o.user.programme
            if o.user and o.user.programme
            else (o.billing_ids[0].programme if o.billing_ids else Programme.PLAN_A)
        )

        results.append(
            AdminSearchResultItem(
                record_type="ORDER",
                programme=order_programme,
                entity_id=o.id,
                identifier=o.order_number,
                order_id=o.id,
                order_number=o.order_number,
                customer_id=o.user_id,
                customer_name=o.user.full_name if o.user else None,
                status=o.order_status.value if hasattr(o.order_status, "value") else str(o.order_status),
                total_amount=o.total_amount,
                created_at=o.created_at,
                metadata={
                    "payment_status": o.payment_status.value if hasattr(o.payment_status, "value") else str(o.payment_status),
                    "is_fulfilled": o.is_fulfilled,
                    "applied_referral_code": o.applied_referral_code,
                    "billing_ids": [b.billing_number for b in o.billing_ids] if o.billing_ids else [],
                },
            )
        )

    # --------------------------------------------------------------------------
    # 3. Immutable Administrative Audit Logging
    # --------------------------------------------------------------------------
    AuditService.record_action(
        db=db,
        action="ADMIN_UNIFIED_SEARCH",
        entity_type="AdminSearch",
        entity_id=query_clean,
        actor_id=current_admin.id,
        actor_role="admin",
        metadata={
            "query": query_clean,
            "match_count": len(results),
            "record_types": [r.record_type for r in results],
        },
    )
    db.commit()

    return AdminSearchResponse(
        query=query_clean,
        total=len(results),
        results=results,
    )

