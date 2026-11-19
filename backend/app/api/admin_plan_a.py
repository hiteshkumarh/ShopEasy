"""Plan A Administrative Inspection API Router (WP-11)."""

from datetime import datetime
from decimal import Decimal
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.billing import BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.commission import PlanACommission
from app.models.enums import Programme, UserRole, WalletType
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.admin_inspection import (
    AdminPlanACommissionResponse,
    AdminPlanAContributionResponse,
    AdminPlanACustomerCashbackSummaryResponse,
    AdminPlanACycleResponse,
    AdminPlanAQueueEntryResponse,
    AdminPlanAQueueResponse,
    AdminPlanAReserveEntryResponse,
    AdminPlanAReserveSummaryResponse,
)
from app.schemas.admin_search import (
    AdminPlanASearchResponse,
    AdminPlanASearchResultItem,
)
from app.services.audit_service import AuditService
from app.services.reports.common import MIME_EXCEL, MIME_PDF, build_file_response
from app.services.reports.plan_a_reports import PlanAReportService

logger = logging.getLogger("shopeasy.admin.plan_a")

router = APIRouter(
    prefix="/admin/plan-a",
    tags=["Admin Plan A Inspection"],
    dependencies=[Depends(require_admin)],
)


@router.get("/commissions", response_model=List[AdminPlanACommissionResponse], summary="List Plan A direct commissions")
def list_plan_a_commissions(
    purchaser_id: Optional[int] = Query(None, description="Filter by purchaser user ID"),
    referrer_id: Optional[int] = Query(None, description="Filter by referrer user ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by commission status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanACommissionResponse]:
    """Retrieve immutable Plan A commission records for audit inspection."""
    query = db.query(PlanACommission)
    if purchaser_id is not None:
        query = query.filter(PlanACommission.purchaser_id == purchaser_id)
    if referrer_id is not None:
        query = query.filter(PlanACommission.referrer_id == referrer_id)
    if status_filter:
        query = query.filter(PlanACommission.status == status_filter.strip())

    records = (
        query.order_by(PlanACommission.processed_at.desc(), PlanACommission.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [AdminPlanACommissionResponse.model_validate(r) for r in records]


@router.get("/queues", response_model=List[AdminPlanAQueueResponse], summary="List Plan A cashback queues")
def list_cashback_queues(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanAQueueResponse]:
    """List all global/root Plan A cashback queues with entry totals."""
    queues = db.query(PlanACashbackQueue).order_by(PlanACashbackQueue.id.asc()).all()
    results = []
    for q in queues:
        count = db.query(PlanACashbackEntry).filter(PlanACashbackEntry.queue_id == q.id).count()
        root_user = db.query(User).filter(User.id == q.root_user_id).first()
        results.append(
            AdminPlanAQueueResponse(
                id=q.id,
                root_user_id=q.root_user_id,
                root_user_name=root_user.full_name if root_user else None,
                active_cycle_id=q.active_cycle_id,
                last_allocated_position=q.last_allocated_position,
                total_entries=count,
                created_at=q.created_at,
            )
        )
    return results


@router.get("/queues/{queue_id}/entries", response_model=List[AdminPlanAQueueEntryResponse], summary="List queue entries")
def list_queue_entries(
    queue_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanAQueueEntryResponse]:
    """List sequential entries within a specific Plan A cashback queue."""
    queue = db.query(PlanACashbackQueue).filter(PlanACashbackQueue.id == queue_id).first()
    if not queue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found.")

    entries = (
        db.query(PlanACashbackEntry)
        .filter(PlanACashbackEntry.queue_id == queue_id)
        .order_by(PlanACashbackEntry.queue_position.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for e in entries:
        user = db.query(User).filter(User.id == e.user_id).first()
        items.append(
            AdminPlanAQueueEntryResponse(
                id=e.id,
                queue_id=e.queue_id,
                user_id=e.user_id,
                user_name=user.full_name if user else None,
                billing_id=e.billing_id,
                queue_position=e.queue_position,
                status=e.status,
                enrolled_at=e.enrolled_at,
                activated_at=e.activated_at,
                completed_at=e.completed_at,
            )
        )
    return items


@router.get("/cycles", response_model=List[AdminPlanACycleResponse], summary="List cashback cycles")
def list_cashback_cycles(
    recipient_user_id: Optional[int] = Query(None, description="Filter by recipient user ID"),
    queue_id: Optional[int] = Query(None, description="Filter by queue ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by cycle status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanACycleResponse]:
    """Retrieve cashback cycles with completed contribution progress and earned totals."""
    query = db.query(PlanACashbackCycle)
    if recipient_user_id is not None:
        query = query.filter(PlanACashbackCycle.recipient_user_id == recipient_user_id)
    if queue_id is not None:
        query = query.filter(PlanACashbackCycle.queue_id == queue_id)
    if status_filter:
        query = query.filter(PlanACashbackCycle.status == status_filter.strip())

    cycles = (
        query.order_by(PlanACashbackCycle.started_at.desc(), PlanACashbackCycle.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for c in cycles:
        u = db.query(User).filter(User.id == c.recipient_user_id).first()
        items.append(
            AdminPlanACycleResponse(
                id=c.id,
                queue_id=c.queue_id,
                queue_entry_id=c.queue_entry_id,
                recipient_user_id=c.recipient_user_id,
                recipient_user_name=u.full_name if u else None,
                recipient_billing_id=c.recipient_billing_id,
                cycle_number=c.cycle_number,
                completed_contributions=c.completed_contributions,
                total_earned=c.total_earned,
                status=c.status,
                started_at=c.started_at,
                completed_at=c.completed_at,
            )
        )
    return items


@router.get("/cycles/{cycle_id}/contributions", response_model=List[AdminPlanAContributionResponse], summary="List contributions for cycle")
def list_cycle_contributions(
    cycle_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanAContributionResponse]:
    """List all individual contributions allocated to a specific cashback cycle."""
    cycle = db.query(PlanACashbackCycle).filter(PlanACashbackCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found.")

    contribs = (
        db.query(PlanACashbackContribution)
        .filter(PlanACashbackContribution.cycle_id == cycle_id)
        .order_by(PlanACashbackContribution.id.asc())
        .all()
    )
    return [AdminPlanAContributionResponse.model_validate(c) for c in contribs]


@router.get("/reserve", response_model=List[AdminPlanAReserveEntryResponse], summary="List unallocated reserve entries")
def list_reserve_entries(
    queue_id: Optional[int] = Query(None, description="Filter by queue ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanAReserveEntryResponse]:
    """List company-owned unallocated cashback reserve records (BR-A4 / BR-A5)."""
    query = db.query(PlanAUnallocatedCashbackReserve)
    if queue_id is not None:
        query = query.filter(PlanAUnallocatedCashbackReserve.queue_id == queue_id)

    entries = (
        query.order_by(PlanAUnallocatedCashbackReserve.reserved_at.desc(), PlanAUnallocatedCashbackReserve.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for e in entries:
        billing_record = db.query(BillingId).filter(BillingId.id == e.billing_id).first() if e.billing_id else None
        items.append(
            AdminPlanAReserveEntryResponse(
                id=e.id,
                queue_id=e.queue_id,
                billing_id=e.billing_id,
                billing_number=billing_record.billing_number if billing_record else None,
                customer_id=e.customer_id,
                amount=e.amount,
                status="UNALLOCATED — COMPANY OWNED",
                reserved_at=e.reserved_at,
            )
        )
    return items


@router.get("/reserve/summary", response_model=AdminPlanAReserveSummaryResponse, summary="Get unallocated reserve financial summary")
def get_reserve_summary(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanAReserveSummaryResponse:
    """Retrieve financial totals and queue-wise breakdown for the company-owned unallocated reserve."""
    total_amount = (
        db.query(func.coalesce(func.sum(PlanAUnallocatedCashbackReserve.amount), Decimal("0.00")))
        .scalar()
        or Decimal("0.00")
    )
    total_entries = db.query(PlanAUnallocatedCashbackReserve).count()

    # Queue breakdown
    breakdown_rows = (
        db.query(
            PlanAUnallocatedCashbackReserve.queue_id,
            func.count(PlanAUnallocatedCashbackReserve.id).label("entry_count"),
            func.sum(PlanAUnallocatedCashbackReserve.amount).label("total_amount"),
        )
        .group_by(PlanAUnallocatedCashbackReserve.queue_id)
        .all()
    )

    queue_breakdown = [
        {
            "queue_id": r.queue_id,
            "entry_count": r.entry_count,
            "total_amount": r.total_amount or Decimal("0.00"),
        }
        for r in breakdown_rows
    ]

    # Audit log entry for inspecting financial reserve
    AuditService.record_action(
        db=db,
        action="INSPECT_PLAN_A_RESERVE",
        entity_type="PlanAUnallocatedCashbackReserve",
        entity_id="ALL",
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        new_values={
            "total_unallocated_amount": str(total_amount),
            "total_entries": total_entries,
        },
    )
    db.commit()

    return AdminPlanAReserveSummaryResponse(
        status_label="UNALLOCATED — COMPANY OWNED",
        total_unallocated_amount=total_amount,
        total_entries=total_entries,
        queue_breakdown=queue_breakdown,
    )


@router.get("/customers/{customer_id}/cashback-summary", response_model=AdminPlanACustomerCashbackSummaryResponse, summary="Get customer cashback summary")
def get_customer_cashback_summary(
    customer_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanACustomerCashbackSummaryResponse:
    """Inspect an individual customer's cashback queue position, cycle progress, and wallet metrics."""
    customer = db.query(User).filter(User.id == customer_id).first()
    if not customer or customer.programme != Programme.PLAN_A:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan A customer #{customer_id} not found.",
        )

    # Active or latest entry in queue
    entry = (
        db.query(PlanACashbackEntry)
        .filter(PlanACashbackEntry.user_id == customer_id)
        .order_by(PlanACashbackEntry.id.desc())
        .first()
    )

    # Active cycle
    cycle = (
        db.query(PlanACashbackCycle)
        .filter(
            PlanACashbackCycle.recipient_user_id == customer_id,
            PlanACashbackCycle.status == "ACTIVE",
        )
        .first()
    )
    if not cycle:
        cycle = (
            db.query(PlanACashbackCycle)
            .filter(PlanACashbackCycle.recipient_user_id == customer_id)
            .order_by(PlanACashbackCycle.id.desc())
            .first()
        )

    completed_cycles_count = (
        db.query(PlanACashbackCycle)
        .filter(
            PlanACashbackCycle.recipient_user_id == customer_id,
            PlanACashbackCycle.status == "COMPLETED",
        )
        .count()
    )

    completed_contribs = cycle.completed_contributions if cycle else 0
    total_earned = cycle.total_earned if cycle else Decimal("0.00")
    bulbs_on = completed_contribs * 3
    bulbs_off = 48 - bulbs_on

    # Wallet
    wallet = (
        db.query(Wallet)
        .filter(
            Wallet.user_id == customer_id,
            Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION,
        )
        .first()
    )
    wallet_balance = wallet.balance if wallet else Decimal("0.00")
    is_frozen = wallet.is_frozen if wallet else False
    lifetime_cashback = Decimal("4000.00") * completed_cycles_count

    # Audit log entry for inspecting customer cashback balance
    AuditService.record_action(
        db=db,
        action="INSPECT_CUSTOMER_CASHBACK",
        entity_type="CustomerCashback",
        entity_id=customer_id,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "customer_id": customer.id,
            "bulbs_on": bulbs_on,
            "total_earned": str(total_earned),
        },
    )
    db.commit()

    return AdminPlanACustomerCashbackSummaryResponse(
        customer_id=customer.id,
        customer_name=customer.full_name,
        customer_phone=customer.phone,
        programme=customer.programme,
        active_queue_id=entry.queue_id if entry else None,
        active_queue_position=entry.queue_position if entry else None,
        active_queue_status=entry.status if entry else None,
        active_cycle_id=cycle.id if cycle else None,
        completed_contributions=completed_contribs,
        total_earned=total_earned,
        target_cashback_amount=Decimal("4000.00"),
        bulbs_on=bulbs_on,
        bulbs_off=bulbs_off,
        total_completed_cycles=completed_cycles_count,
        total_lifetime_cashback=lifetime_cashback,
        wallet_balance=wallet_balance,
        is_wallet_frozen=is_frozen,
    )


# =========================================================================
# Plan A Admin Reports (WP-11 Step 3)
# =========================================================================


@router.get(
    "/reports/commissions",
    summary="Download Plan A Commission Report (Excel or PDF)",
    response_description="Financial commission report download",
)
def download_plan_a_commissions_report(
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' or 'pdf'"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    customer_id: Optional[int] = Query(None, description="Filter by customer/purchaser/referrer user ID"),
    billing_id: Optional[str] = Query(None, description="Filter by Billing ID number"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download traceable Plan A commission records in Excel (.xlsx) or PDF format."""
    clean_format = (format_type or "excel").strip().lower()
    if clean_format in ("excel", "xlsx"):
        content_bytes, filename = PlanAReportService.generate_commission_excel(
            db=db,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
            billing_id=billing_id,
        )
        media_type = MIME_EXCEL
    elif clean_format == "pdf":
        content_bytes, filename = PlanAReportService.generate_commission_pdf(
            db=db,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
            billing_id=billing_id,
        )
        media_type = MIME_PDF
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Supported formats are 'excel' and 'pdf'.",
        )

    AuditService.record_action(
        db=db,
        action="PLAN_A_REPORT_COMMISSIONS",
        entity_type="PlanACommission",
        entity_id=None,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "format": clean_format,
            "customer_id": customer_id,
            "billing_id": billing_id,
        },
    )
    db.commit()

    return build_file_response(content_bytes, filename, media_type)


@router.get(
    "/reports/cashback",
    summary="Download Plan A Cashback Report (Excel or PDF)",
    response_description="Financial cashback contribution report download",
)
def download_plan_a_cashback_report(
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' or 'pdf'"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    customer_id: Optional[int] = Query(None, description="Filter by customer user ID"),
    queue_id: Optional[int] = Query(None, description="Filter by queue ID"),
    billing_id: Optional[str] = Query(None, description="Filter by Billing ID number"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download Plan A cashback contributions and unallocated company reserves in Excel or PDF format."""
    clean_format = (format_type or "excel").strip().lower()
    if clean_format in ("excel", "xlsx"):
        content_bytes, filename = PlanAReportService.generate_cashback_excel(
            db=db,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
            queue_id=queue_id,
            billing_id=billing_id,
        )
        media_type = MIME_EXCEL
    elif clean_format == "pdf":
        content_bytes, filename = PlanAReportService.generate_cashback_pdf(
            db=db,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
            queue_id=queue_id,
            billing_id=billing_id,
        )
        media_type = MIME_PDF
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Supported formats are 'excel' and 'pdf'.",
        )

    AuditService.record_action(
        db=db,
        action="PLAN_A_REPORT_CASHBACK",
        entity_type="PlanACashbackContribution",
        entity_id=None,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "format": clean_format,
            "customer_id": customer_id,
            "queue_id": queue_id,
            "billing_id": billing_id,
        },
    )
    db.commit()

    return build_file_response(content_bytes, filename, media_type)


@router.get(
    "/reports/customers/{customer_id}/statement",
    summary="Download Individual Plan A Customer Statement (Excel or PDF) — Admin Only",
    response_description="Consolidated customer statement download",
)
def download_plan_a_customer_statement(
    customer_id: str,
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' or 'pdf'"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download consolidated Plan A financial statement for an individual customer in Excel or PDF.

    Administrative report only. Not accessible for customer self-service download (R-07).
    Accepts customer User ID (e.g. 30001) or registered phone number (e.g. 9019443501).
    """
    clean_format = (format_type or "excel").strip().lower()
    if clean_format in ("excel", "xlsx"):
        content_bytes, filename = PlanAReportService.generate_customer_statement_excel(
            db=db,
            customer_id=customer_id,
            start_date=start_date,
            end_date=end_date,
        )
        media_type = MIME_EXCEL
    elif clean_format == "pdf":
        content_bytes, filename = PlanAReportService.generate_customer_statement_pdf(
            db=db,
            customer_id=customer_id,
            start_date=start_date,
            end_date=end_date,
        )
        media_type = MIME_PDF
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Supported formats are 'excel' and 'pdf'.",
        )

    resolved_user = PlanAReportService.resolve_customer(db, customer_id)
    AuditService.record_action(
        db=db,
        action="PLAN_A_REPORT_CUSTOMER_STATEMENT",
        entity_type="User",
        entity_id=resolved_user.id,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "customer_id": resolved_user.id,
            "queried_identifier": str(customer_id),
            "format": clean_format,
        },
    )
    db.commit()

    return build_file_response(content_bytes, filename, media_type)


@router.get(
    "/search",
    response_model=AdminPlanASearchResponse,
    summary="Plan A search by customer name, mobile, customer ID, billing ID, or queue ID (Admin only)",
)
def search_plan_a(
    q: str = Query(..., description="Query for customer name, mobile, customer ID, billing ID, or queue ID"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanASearchResponse:
    """Search Plan A records (Customers, Billing IDs, and Queues).
    
    Supports:
    - Customer Name (case-insensitive substring)
    - Registered Mobile Number
    - Customer ID (numeric)
    - Billing ID / Number (Plan A)
    - Queue ID (Plan A Cashback Queue)
    """
    clean_q = q.strip()
    if not clean_q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan A search query cannot be empty or whitespace only.",
        )
    if len(clean_q) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query exceeds maximum permitted length of 64 characters.",
        )

    results: List[AdminPlanASearchResultItem] = []
    clean_numeric = clean_q.lstrip("#").strip()
    is_numeric = clean_q.isdigit() or clean_numeric.isdigit()
    num_val = int(clean_numeric) if is_numeric else None

    # 1. Search Plan A Customers (by name, phone, or ID)
    cust_filters = [
        User.full_name.ilike(f"%{clean_q}%"),
        User.phone.like(f"%{clean_q}%"),
    ]
    if num_val is not None:
        cust_filters.append(User.id == num_val)

    cust_query = db.query(User).filter(
        User.role == UserRole.CUSTOMER,
        or_(*cust_filters),
    ).limit(20)

    for u in cust_query.all():
        q_rec = db.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == u.id).first()
        b_count = db.query(BillingId).filter(BillingId.user_id == u.id, BillingId.programme == Programme.PLAN_A).count()
        results.append(
            AdminPlanASearchResultItem(
                record_type="CUSTOMER",
                entity_id=u.id,
                customer_id=u.id,
                customer_name=u.full_name,
                phone=u.phone,
                identifier=f"{u.full_name} ({u.phone})",
                status=u.account_status.value if hasattr(u.account_status, "value") else str(u.account_status),
                created_at=u.created_at,
                details={
                    "customer_id": u.id,
                    "phone": u.phone,
                    "has_queue": q_rec is not None,
                    "queue_id": q_rec.id if q_rec else None,
                    "billing_ids_count": b_count,
                    "referral_code": u.referral_code,
                },
            )
        )

    # 2. Search Plan A Billing IDs
    b_filters = [
        BillingId.billing_number.ilike(f"%{clean_q}%"),
        BillingId.billing_number.ilike(f"%{clean_numeric}%"),
    ]
    if num_val is not None:
        b_filters.extend([BillingId.id == num_val, BillingId.sequence_number == num_val])

    billing_query = db.query(BillingId).filter(
        BillingId.programme == Programme.PLAN_A,
        or_(*b_filters),
    ).limit(20)

    for b in billing_query.all():
        u = db.query(User).filter(User.id == b.user_id).first() if b.user_id else None
        results.append(
            AdminPlanASearchResultItem(
                record_type="BILLING_ID",
                entity_id=b.id,
                customer_id=b.user_id,
                customer_name=u.full_name if u else None,
                phone=u.phone if u else None,
                identifier=b.billing_number,
                status=b.status,
                created_at=b.created_at,
                details={
                    "billing_number": b.billing_number,
                    "sequence_number": b.sequence_number,
                    "unit_index": b.unit_index,
                    "order_id": b.order_id,
                },
            )
        )

    # 3. Search Plan A Queues (by Queue ID)
    if num_val is not None:
        queues = db.query(PlanACashbackQueue).filter(
            or_(
                PlanACashbackQueue.id == num_val,
                PlanACashbackQueue.root_user_id == num_val,
            )
        ).limit(10).all()

        for q_obj in queues:
            u = db.query(User).filter(User.id == q_obj.root_user_id).first() if q_obj.root_user_id else None
            results.append(
                AdminPlanASearchResultItem(
                    record_type="QUEUE",
                    entity_id=q_obj.id,
                    customer_id=q_obj.root_user_id,
                    customer_name=u.full_name if u else None,
                    phone=u.phone if u else None,
                    identifier=f"Queue #{q_obj.id}",
                    status="ACTIVE",
                    created_at=q_obj.created_at,
                    details={
                        "queue_id": q_obj.id,
                        "root_user_id": q_obj.root_user_id,
                        "active_cycle_id": q_obj.active_cycle_id,
                        "last_allocated_position": q_obj.last_allocated_position,
                    },
                )
            )

    # Audit logging
    AuditService.record_action(
        db=db,
        action="ADMIN_PLAN_A_SEARCH",
        entity_type="AdminPlanASearch",
        entity_id=clean_q,
        actor_id=current_admin.id,
        actor_role="admin",
        metadata={"query": clean_q, "match_count": len(results)},
    )
    db.commit()

    return AdminPlanASearchResponse(
        query=clean_q,
        total=len(results),
        results=results,
    )


