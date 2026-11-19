"""Plan B Administrative Inspection API Router (WP-11).

Provides read-only administrative inspection endpoints for Plan B distributors,
referral hierarchies, direct/generation commissions, distributor wallets, and billing IDs.
"""

from datetime import datetime
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.billing import BillingId
from app.models.commission import PlanBCommission
from app.models.enums import AccountStatus, Programme, UserRole, WalletTransactionType, WalletType
from app.models.referral import ReferralRelationship
from app.models.user import User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal
from app.schemas.admin_inspection import (
    AdminPlanBBillingIdResponse,
    AdminPlanBCommissionResponse,
    AdminPlanBDistributorResponse,
    AdminPlanBDistributorWalletResponse,
    AdminPlanBOverviewSummaryResponse,
    AdminPlanBReferralRelationResponse,
)
from app.schemas.admin_search import (
    AdminPlanBSearchResponse,
    AdminPlanBSearchResultItem,
)
from app.services.audit_service import AuditService
from app.services.reports.common import MIME_EXCEL, build_file_response
from app.services.reports.plan_b_reports import PlanBReportService

logger = logging.getLogger("shopeasy.admin.plan_b")

router = APIRouter(
    prefix="/admin/plan-b",
    tags=["Admin Plan B Inspection"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "/summary",
    response_model=AdminPlanBOverviewSummaryResponse,
    summary="Get aggregated counts for Plan B dashboard metrics",
)
def get_plan_b_overview_summary(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanBOverviewSummaryResponse:
    """Return live counts for Plan B distributors, direct commissions, generation commissions, and billing IDs."""
    total_distributors = db.query(User).filter(User.programme == Programme.PLAN_B).count()
    total_direct = db.query(PlanBCommission).filter(PlanBCommission.commission_type == "DIRECT").count()
    total_generation = db.query(PlanBCommission).filter(PlanBCommission.commission_type == "GENERATION").count()
    total_billing_ids = db.query(BillingId).filter(BillingId.programme == Programme.PLAN_B).count()

    return AdminPlanBOverviewSummaryResponse(
        total_distributors=total_distributors,
        total_direct_commissions=total_direct,
        total_generation_commissions=total_generation,
        total_billing_ids=total_billing_ids,
    )


@router.get(
    "/distributors",
    response_model=List[AdminPlanBDistributorResponse],
    summary="Search and list Plan B distributors",
)
def list_distributors(
    search: Optional[str] = Query(None, description="Search by name, phone, or referral code"),
    account_status: Optional[str] = Query(None, alias="status", description="Filter by account status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanBDistributorResponse]:
    """Retrieve paginated Plan B distributors with active direct referee counts."""
    query = db.query(User).filter(User.programme == Programme.PLAN_B)

    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.full_name.ilike(search_term),
                User.phone.ilike(search_term),
                User.referral_code.ilike(search_term),
            )
        )

    if account_status:
        try:
            status_enum = AccountStatus(account_status.strip().upper())
            query = query.filter(User.account_status == status_enum)
        except ValueError:
            query = query.filter(User.account_status == account_status.strip())

    users = (
        query.order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    results: List[AdminPlanBDistributorResponse] = []
    for u in users:
        direct_count = (
            db.query(ReferralRelationship)
            .filter(
                ReferralRelationship.referrer_id == u.id,
                ReferralRelationship.is_active == True,  # noqa: E712
            )
            .count()
        )
        results.append(
            AdminPlanBDistributorResponse(
                id=u.id,
                full_name=u.full_name,
                phone=u.phone,
                referral_code=u.referral_code,
                account_status=u.account_status,
                is_active=u.is_active,
                referred_by_id=u.referred_by_id,
                direct_referees_count=direct_count,
                created_at=u.created_at,
            )
        )

    return results


@router.get(
    "/distributors/{distributor_id}",
    response_model=AdminPlanBDistributorResponse,
    summary="Get Plan B distributor details",
)
def get_distributor(
    distributor_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanBDistributorResponse:
    """Retrieve details for a specific Plan B distributor."""
    user = (
        db.query(User)
        .filter(User.id == distributor_id, User.programme == Programme.PLAN_B)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan B distributor with ID {distributor_id} not found.",
        )

    direct_count = (
        db.query(ReferralRelationship)
        .filter(
            ReferralRelationship.referrer_id == user.id,
            ReferralRelationship.is_active == True,  # noqa: E712
        )
        .count()
    )

    return AdminPlanBDistributorResponse(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        referral_code=user.referral_code,
        account_status=user.account_status,
        is_active=user.is_active,
        referred_by_id=user.referred_by_id,
        direct_referees_count=direct_count,
        created_at=user.created_at,
    )


@router.get(
    "/distributors/{distributor_id}/referrals",
    response_model=List[AdminPlanBReferralRelationResponse],
    summary="List direct referrals of a Plan B distributor",
)
def list_distributor_referrals(
    distributor_id: int,
    is_active_only: bool = Query(True, description="Filter for active relationships only"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanBReferralRelationResponse]:
    """Retrieve direct referral relationships for a Plan B distributor."""
    user = (
        db.query(User)
        .filter(User.id == distributor_id, User.programme == Programme.PLAN_B)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan B distributor with ID {distributor_id} not found.",
        )

    query = db.query(ReferralRelationship).filter(
        ReferralRelationship.referrer_id == distributor_id
    )
    if is_active_only:
        query = query.filter(ReferralRelationship.is_active == True)  # noqa: E712

    relations = (
        query.order_by(ReferralRelationship.created_at.desc(), ReferralRelationship.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    results: List[AdminPlanBReferralRelationResponse] = []
    for rel in relations:
        referee = db.query(User).filter(User.id == rel.referee_id).first()
        results.append(
            AdminPlanBReferralRelationResponse(
                id=rel.id,
                referee_id=rel.referee_id,
                referee_name=referee.full_name if referee else None,
                referee_phone=referee.phone if referee else None,
                referrer_id=rel.referrer_id,
                referral_code_used=rel.referral_code_used,
                binding_channel=rel.binding_channel,
                is_active=rel.is_active,
                created_at=rel.created_at,
            )
        )

    return results


@router.get(
    "/commissions/direct",
    response_model=List[AdminPlanBCommissionResponse],
    summary="List Plan B direct commissions",
)
def list_direct_commissions(
    distributor_id: Optional[int] = Query(None, description="Filter by distributor ID"),
    referee_id: Optional[int] = Query(None, description="Filter by purchaser/referee ID"),
    order_id: Optional[int] = Query(None, description="Filter by order ID"),
    billing_id: Optional[int] = Query(None, description="Filter by billing ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanBCommissionResponse]:
    """Retrieve immutable Plan B direct referral commission records."""
    query = db.query(PlanBCommission).filter(PlanBCommission.commission_type == "DIRECT")

    if distributor_id is not None:
        query = query.filter(PlanBCommission.distributor_id == distributor_id)
    if referee_id is not None:
        query = query.filter(PlanBCommission.referee_id == referee_id)
    if order_id is not None:
        query = query.filter(PlanBCommission.order_id == order_id)
    if billing_id is not None:
        query = query.filter(PlanBCommission.billing_id == billing_id)
    if status_filter:
        query = query.filter(PlanBCommission.status == status_filter.strip())

    records = (
        query.order_by(PlanBCommission.processed_at.desc(), PlanBCommission.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for r in records:
        b_num = None
        if r.billing_id:
            bid_rec = db.query(BillingId).filter(BillingId.id == r.billing_id).first()
            if bid_rec:
                b_num = bid_rec.billing_number
        dto = AdminPlanBCommissionResponse.model_validate(r)
        dto.billing_number = b_num
        items.append(dto)
    return items


@router.get(
    "/commissions/generation",
    response_model=List[AdminPlanBCommissionResponse],
    summary="List Plan B generation commissions",
)
def list_generation_commissions(
    distributor_id: Optional[int] = Query(None, description="Filter by distributor ID"),
    referee_id: Optional[int] = Query(None, description="Filter by purchaser/referee ID"),
    order_id: Optional[int] = Query(None, description="Filter by order ID"),
    billing_id: Optional[int] = Query(None, description="Filter by billing ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanBCommissionResponse]:
    """Retrieve immutable Plan B generation (Level 1-20) commission records."""
    query = db.query(PlanBCommission).filter(PlanBCommission.commission_type == "GENERATION")

    if distributor_id is not None:
        query = query.filter(PlanBCommission.distributor_id == distributor_id)
    if referee_id is not None:
        query = query.filter(PlanBCommission.referee_id == referee_id)
    if order_id is not None:
        query = query.filter(PlanBCommission.order_id == order_id)
    if billing_id is not None:
        query = query.filter(PlanBCommission.billing_id == billing_id)
    if status_filter:
        query = query.filter(PlanBCommission.status == status_filter.strip())

    records = (
        query.order_by(PlanBCommission.processed_at.desc(), PlanBCommission.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for r in records:
        b_num = None
        if r.billing_id:
            bid_rec = db.query(BillingId).filter(BillingId.id == r.billing_id).first()
            if bid_rec:
                b_num = bid_rec.billing_number
        dto = AdminPlanBCommissionResponse.model_validate(r)
        dto.billing_number = b_num
        items.append(dto)
    return items


@router.get(
    "/distributors/{distributor_id}/wallet",
    response_model=AdminPlanBDistributorWalletResponse,
    summary="Inspect Plan B distributor wallet and withdrawal history",
)
def get_distributor_wallet_overview(
    distributor_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanBDistributorWalletResponse:
    """Inspect Plan B direct referral wallet balance, transaction ledger, and withdrawals."""
    user = (
        db.query(User)
        .filter(User.id == distributor_id, User.programme == Programme.PLAN_B)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan B distributor with ID {distributor_id} not found.",
        )

    wallet = (
        db.query(Wallet)
        .filter(
            Wallet.user_id == distributor_id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        )
        .first()
    )

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DIRECT_REFERRAL wallet not found for distributor ID {distributor_id}.",
        )

    # Compute total earned from CREDIT transactions
    total_earned = (
        db.query(func.coalesce(func.sum(WalletTransaction.amount), Decimal("0.00")))
        .filter(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.transaction_type == WalletTransactionType.CREDIT,
        )
        .scalar()
    )

    # Recent transactions (latest 20)
    tx_records = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.wallet_id == wallet.id)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .limit(20)
        .all()
    )
    recent_transactions: List[Dict[str, Any]] = [
        {
            "id": tx.id,
            "transaction_type": tx.transaction_type.value if hasattr(tx.transaction_type, "value") else str(tx.transaction_type),
            "amount": tx.amount,
            "balance_after": tx.balance_after,
            "reference_type": tx.reference_type.value if hasattr(tx.reference_type, "value") else str(tx.reference_type),
            "reference_id": tx.reference_id,
            "created_at": tx.created_at,
        }
        for tx in tx_records
    ]

    # Recent withdrawals (latest 20)
    w_records = (
        db.query(Withdrawal)
        .filter(Withdrawal.wallet_id == wallet.id)
        .order_by(Withdrawal.requested_at.desc(), Withdrawal.id.desc())
        .limit(20)
        .all()
    )
    recent_withdrawals: List[Dict[str, Any]] = [
        {
            "id": w.id,
            "amount": w.amount,
            "status": w.status.value if hasattr(w.status, "value") else str(w.status),
            "requested_at": w.requested_at,
            "completed_at": w.completed_at,
            "receipt_reference": w.receipt_reference,
            "rejection_reason": w.rejection_reason,
        }
        for w in w_records
    ]

    # Record sensitive inspection action in audit log
    AuditService.record_action(
        db=db,
        action="INSPECT_DISTRIBUTOR_WALLET",
        entity_type="Wallet",
        entity_id=wallet.id,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "distributor_id": distributor_id,
            "wallet_type": wallet.wallet_type.value if hasattr(wallet.wallet_type, "value") else str(wallet.wallet_type),
            "balance": str(wallet.balance),
            "is_frozen": wallet.is_frozen,
        },
    )
    db.commit()

    return AdminPlanBDistributorWalletResponse(
        distributor_id=distributor_id,
        wallet_id=wallet.id,
        wallet_type=wallet.wallet_type,
        balance=wallet.balance,
        total_earned=Decimal(str(total_earned)),
        total_withdrawn=wallet.total_withdrawn,
        is_frozen=wallet.is_frozen,
        recent_transactions=recent_transactions,
        recent_withdrawals=recent_withdrawals,
    )


@router.get(
    "/billing-ids",
    response_model=List[AdminPlanBBillingIdResponse],
    summary="List Plan B Billing IDs",
)
def list_billing_ids(
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    order_id: Optional[int] = Query(None, description="Filter by order ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AdminPlanBBillingIdResponse]:
    """Retrieve immutable Plan B billing unit identifiers."""
    query = db.query(BillingId).filter(BillingId.programme == Programme.PLAN_B)

    if user_id is not None:
        query = query.filter(BillingId.user_id == user_id)
    if order_id is not None:
        query = query.filter(BillingId.order_id == order_id)
    if status_filter:
        query = query.filter(BillingId.status == status_filter.strip())

    records = (
        query.order_by(BillingId.created_at.desc(), BillingId.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return [AdminPlanBBillingIdResponse.model_validate(r) for r in records]


# =========================================================================
# Plan B Admin Reports (WP-11 Step 3) — Excel (.xlsx) Only
# =========================================================================


@router.get(
    "/reports/purchases",
    summary="Download Complete Plan B Purchase Report (Excel .xlsx only)",
    response_description="Excel (.xlsx) sales and purchase report",
)
def download_plan_b_purchases_report(
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' only per rule R-09"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    customer_name: Optional[str] = Query(None, description="Filter by customer name"),
    distributor_name: Optional[str] = Query(None, description="Filter by referring distributor name"),
    mobile: Optional[str] = Query(None, description="Filter by customer mobile phone"),
    billing_id: Optional[str] = Query(None, description="Filter by Billing ID number"),
    order_id: Optional[int] = Query(None, description="Filter by order ID"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download complete Plan B purchase and sales records in Excel (.xlsx) format only."""
    clean_format = (format_type or "excel").strip().lower()
    if clean_format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan B admin reports support Excel (.xlsx) only per business rule R-09.",
        )
    elif clean_format not in ("excel", "xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Plan B reports are available in Excel (.xlsx) only.",
        )

    content_bytes, filename = PlanBReportService.generate_purchase_excel(
        db=db,
        start_date=start_date,
        end_date=end_date,
        customer_name=customer_name,
        distributor_name=distributor_name,
        mobile=mobile,
        billing_id=billing_id,
        order_id=order_id,
    )

    AuditService.record_action(
        db=db,
        action="PLAN_B_REPORT_PURCHASES",
        entity_type="BillingId",
        entity_id=None,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "format": clean_format,
            "order_id": order_id,
            "billing_id": billing_id,
        },
    )
    db.commit()

    return build_file_response(content_bytes, filename, MIME_EXCEL)


@router.get(
    "/reports/commissions",
    summary="Download Plan B Commission Report (Excel .xlsx only)",
    response_description="Excel (.xlsx) commission ledger report",
)
def download_plan_b_commissions_report(
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' only per rule R-09"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    distributor_name: Optional[str] = Query(None, description="Filter by distributor name"),
    customer_name: Optional[str] = Query(None, description="Filter by customer name"),
    billing_id: Optional[str] = Query(None, description="Filter by Billing ID number"),
    order_id: Optional[int] = Query(None, description="Filter by order ID"),
    commission_type: Optional[str] = Query(None, description="Filter by commission type: 'DIRECT' or 'GENERATION'"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download Plan B direct and generation commission records in Excel (.xlsx) format only."""
    clean_format = (format_type or "excel").strip().lower()
    if clean_format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan B admin reports support Excel (.xlsx) only per business rule R-09.",
        )
    elif clean_format not in ("excel", "xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Plan B reports are available in Excel (.xlsx) only.",
        )

    content_bytes, filename = PlanBReportService.generate_commission_excel(
        db=db,
        start_date=start_date,
        end_date=end_date,
        distributor_name=distributor_name,
        customer_name=customer_name,
        billing_id=billing_id,
        order_id=order_id,
        commission_type=commission_type,
    )

    AuditService.record_action(
        db=db,
        action="PLAN_B_REPORT_COMMISSIONS",
        entity_type="PlanBCommission",
        entity_id=None,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "format": clean_format,
            "commission_type": commission_type,
            "order_id": order_id,
            "billing_id": billing_id,
        },
    )
    db.commit()

    return build_file_response(content_bytes, filename, MIME_EXCEL)


@router.get(
    "/reports/distributors/{distributor_id}",
    summary="Download Individual Plan B Distributor Report (Excel .xlsx only)",
    response_description="Excel (.xlsx) comprehensive distributor profile report",
)
def download_plan_b_distributor_report(
    distributor_id: str,
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' only per rule R-09"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download comprehensive individual Plan B distributor report in Excel (.xlsx) format only.
    
    Accepts distributor User ID (e.g. 101) or registered phone number (e.g. 9812345679).
    """
    clean_format = (format_type or "excel").strip().lower()
    if clean_format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan B admin reports support Excel (.xlsx) only per business rule R-09.",
        )
    elif clean_format not in ("excel", "xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Plan B reports are available in Excel (.xlsx) only.",
        )

    content_bytes, filename = PlanBReportService.generate_distributor_report_excel(
        db=db,
        distributor_id=distributor_id,
        start_date=start_date,
        end_date=end_date,
    )

    resolved_user = PlanBReportService.resolve_distributor(db, distributor_id)
    AuditService.record_action(
        db=db,
        action="PLAN_B_REPORT_DISTRIBUTOR",
        entity_type="User",
        entity_id=resolved_user.id,
        actor_id=current_admin.id,
        actor_role=current_admin.role.value if hasattr(current_admin.role, "value") else str(current_admin.role),
        metadata={
            "distributor_id": resolved_user.id,
            "queried_identifier": str(distributor_id),
            "format": clean_format,
        },
    )
    db.commit()

    return build_file_response(content_bytes, filename, MIME_EXCEL)


@router.get(
    "/search",
    response_model=AdminPlanBSearchResponse,
    summary="Plan B search by distributor name, mobile, distributor ID, sponsor ID, or ledger ID (Admin only)",
)
def search_plan_b(
    q: str = Query(..., description="Query for distributor name, mobile, distributor ID, sponsor ID, or ledger ID"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlanBSearchResponse:
    """Search Plan B records (Distributors, Ledgers, Commissions).
    
    Supports:
    - Distributor Name (case-insensitive substring)
    - Registered Mobile Number
    - Distributor ID (numeric)
    - Sponsor ID (numeric)
    - Ledger ID (WalletTransaction.id or PlanBCommission.id)
    """
    clean_q = q.strip()
    if not clean_q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan B search query cannot be empty or whitespace only.",
        )
    if len(clean_q) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query exceeds maximum permitted length of 64 characters.",
        )

    results: List[AdminPlanBSearchResultItem] = []
    clean_numeric = clean_q.lstrip("#").strip()
    is_numeric = clean_q.isdigit() or clean_numeric.isdigit()
    num_val = int(clean_numeric) if is_numeric else None

    # 1. Search Plan B Distributors (by name, phone, distributor ID, or sponsor ID)
    dist_filters = [
        User.full_name.ilike(f"%{clean_q}%"),
        User.phone.like(f"%{clean_q}%"),
        User.referral_code.ilike(f"%{clean_q}%"),
    ]
    if num_val is not None:
        dist_filters.extend([User.id == num_val, User.referred_by_id == num_val])

    dist_query = db.query(User).filter(
        User.programme == Programme.PLAN_B,
        or_(*dist_filters),
    ).limit(25)

    for d in dist_query.all():
        w = db.query(Wallet).filter(Wallet.user_id == d.id).first()
        ref_count = db.query(User).filter(User.referred_by_id == d.id).count()
        results.append(
            AdminPlanBSearchResultItem(
                record_type="DISTRIBUTOR",
                entity_id=d.id,
                distributor_id=d.id,
                distributor_name=d.full_name,
                phone=d.phone,
                sponsor_id=d.referred_by_id,
                identifier=f"{d.full_name} ({d.phone})",
                status=d.account_status.value if hasattr(d.account_status, "value") else str(d.account_status),
                created_at=d.created_at,
                details={
                    "distributor_id": d.id,
                    "referral_code": d.referral_code,
                    "sponsor_id": d.referred_by_id,
                    "direct_referees_count": ref_count,
                    "wallet_balance": float(w.balance) if w else 0.0,
                },
            )
        )

    # 2. Search Plan B Ledger Transactions (by Ledger ID)
    if num_val is not None:
        txs = db.query(WalletTransaction).join(Wallet).join(User, Wallet.user_id == User.id).filter(
            User.programme == Programme.PLAN_B,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
            WalletTransaction.id == num_val,
        ).limit(10).all()

        for t in txs:
            w = db.query(Wallet).filter(Wallet.id == t.wallet_id).first()
            d = db.query(User).filter(User.id == w.user_id).first() if w else None
            results.append(
                AdminPlanBSearchResultItem(
                    record_type="LEDGER",
                    entity_id=t.id,
                    distributor_id=d.id if d else None,
                    distributor_name=d.full_name if d else None,
                    phone=d.phone if d else None,
                    identifier=f"Ledger TX #{t.id}",
                    status="COMPLETED",
                    amount=t.amount,
                    created_at=t.created_at,
                    details={
                        "transaction_id": t.id,
                        "transaction_type": t.transaction_type.value if hasattr(t.transaction_type, "value") else str(t.transaction_type),
                        "reference_id": t.reference_id,
                        "description": t.description,
                    },
                )
            )

        # 3. Search Plan B Commissions (by Commission ID)
        comms = db.query(PlanBCommission).filter(
            PlanBCommission.id == num_val
        ).limit(10).all()

        for c in comms:
            d = db.query(User).filter(User.id == c.distributor_id).first() if c.distributor_id else None
            results.append(
                AdminPlanBSearchResultItem(
                    record_type="COMMISSION",
                    entity_id=c.id,
                    distributor_id=c.distributor_id,
                    distributor_name=d.full_name if d else None,
                    phone=d.phone if d else None,
                    identifier=f"Plan B Commission #{c.id}",
                    status="CREDITED",
                    amount=c.net_amount,
                    created_at=c.created_at,
                    details={
                        "commission_id": c.id,
                        "commission_type": c.commission_type,
                        "gross_amount": float(c.gross_amount) if c.gross_amount else 0.0,
                        "tds_amount": float(c.tds_amount) if c.tds_amount else 0.0,
                        "order_id": c.order_id,
                    },
                )
            )

    # Audit logging
    AuditService.record_action(
        db=db,
        action="ADMIN_PLAN_B_SEARCH",
        entity_type="AdminPlanBSearch",
        entity_id=clean_q,
        actor_id=current_admin.id,
        actor_role="admin",
        metadata={"query": clean_q, "match_count": len(results)},
    )
    db.commit()

    return AdminPlanBSearchResponse(
        query=clean_q,
        total=len(results),
        results=results,
    )


