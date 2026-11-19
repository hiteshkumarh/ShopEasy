"""Report generation services for ShopEasy / Arya Global Digital (WP-11 Step 3).

Exposes reporting engines for:
- Plan A Admin Reports (Commission, Cashback, Customer Statement) in Excel and PDF
- Plan B Admin Reports (Purchases, Commission, Distributor Profile) in Excel
- Plan B Distributor Self-Service Commission Statement in Excel
"""

from app.services.reports.plan_a_reports import PlanAReportService
from app.services.reports.plan_b_reports import PlanBReportService

__all__ = [
    "PlanAReportService",
    "PlanBReportService",
]

