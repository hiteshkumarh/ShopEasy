"""Plan B Distributor Self-Service Reporting API Router (WP-11 Step 3).

Exposes distributor's own commission statement in Excel (.xlsx) only.
Strictly prohibits PDF format per business rule R-08.
Enforces authenticated distributor ownership (zero IDOR exposure).
"""

from datetime import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_distributor
from app.core.database import get_db
from app.models.user import User
from app.services.reports.common import MIME_EXCEL, build_file_response
from app.services.reports.plan_b_reports import PlanBReportService

logger = logging.getLogger("shopeasy.distributor.reports")

router = APIRouter(
    prefix="/distributor/reports",
    tags=["Plan B Distributor Reports"],
    dependencies=[Depends(require_distributor)],
)


@router.get(
    "/commission-statement",
    summary="Download distributor's own commission statement (Excel .xlsx only)",
    response_description="Excel (.xlsx) spreadsheet download",
)
def download_distributor_statement(
    format_type: str = Query("excel", alias="format", description="Export format: 'excel' only. PDF is strictly prohibited."),
    start_date: Optional[datetime] = Query(None, description="Start date filter (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (UTC)"),
    current_distributor: User = Depends(require_distributor),
    db: Session = Depends(get_db),
):
    """Download the authenticated distributor's own commission statement in Excel (.xlsx) only.

    Business Rules:
      - R-08 / PB-16: Excel (.xlsx) only, strictly NO PDF download allowed.
      - Distributor Ownership: Strictly scoped to the authenticated caller; user-supplied ID is never accepted.
    """
    clean_format = (format_type or "excel").strip().lower()
    if clean_format == "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF format is not supported for distributor statements. Excel (.xlsx) only per business rule R-08.",
        )
    elif clean_format not in ("excel", "xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format_type}'. Distributor statements are available in Excel (.xlsx) only.",
        )

    content_bytes, filename = PlanBReportService.generate_distributor_self_statement_excel(
        db=db,
        distributor_id=current_distributor.id,
        start_date=start_date,
        end_date=end_date,
    )

    return build_file_response(content_bytes, filename, MIME_EXCEL)


@router.get(
    "/dashboard-overview",
    summary="Get 9 summary metrics, Direct Referral history, and Generation history for Plan B distributor",
)
def get_distributor_dashboard_overview(
    current_distributor: User = Depends(require_distributor),
    db: Session = Depends(get_db),
):
    """Retrieve composite Plan B distributor metrics:
    - 9 Summary cards:
      1. Available Direct Referral Wallet Balance
      2. Lifetime Direct Referral Commission Earned
      3. Generation Commission Earned
      4. Total Gross Commission
      5. Total Operational Cost Deducted
      6. Total TDS Deducted
      7. Total Net Commission Earned
      8. Total Amount Withdrawn
      9. Available Withdrawable Balance
    - Direct Referral Commission History (once per referred customer)
    - Generation Commission History (one per eligible Billing ID)
    """
    return PlanBReportService.get_distributor_dashboard_overview(
        db=db, distributor_id=current_distributor.id
    )


