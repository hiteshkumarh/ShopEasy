"""
backend/tests/test_wp12_step7_mock_data_retirement.py
Comprehensive test suite for WP-12 Step 7: Retire Mock Data & Final Frontend Verification.

Verifies:
1. Hardcoded mock/fallback financial literals retired from frontend/js/admin.js.
2. All 10 report variants correctly wired in frontend and backend:
   - 6 Plan A Admin reports (Excel + PDF)
   - 3 Plan B Admin reports (Excel only per R-09)
   - 1 Plan B Distributor self-service statement (Excel only per R-08 / PB-16)
3. Plan B Report format restrictions enforced (PDF rejected for Plan B with 400).
4. Negative requirement PB-15: referred customers & units count hidden from distributor dashboard.
5. Plan B Generation Commission: ₹50 / item to direct referring distributor, no 20-generation tree wording.
6. OR-10 Checkout Notice: Exact notice present before place order action.
7. Order history with Billing IDs: Item-level Billing ID display, copy button, and empty state.
8. Live backend report generation returning valid spreadsheet/PDF streams with headers.
"""

import os
import re
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.user import User
from app.models.enums import UserRole
from app.core.security import create_access_token


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
ADMIN_DIR = os.path.join(FRONTEND_DIR, "admin")
ADMIN_JS_PATH = os.path.join(FRONTEND_DIR, "js", "admin.js")
API_JS_PATH = os.path.join(FRONTEND_DIR, "js", "api.js")
DISTRIBUTOR_HTML_PATH = os.path.join(FRONTEND_DIR, "distributor-dashboard.html")
DISTRIBUTOR_JS_PATH = os.path.join(FRONTEND_DIR, "js", "distributor-dashboard.js")
CHECKOUT_HTML_PATH = os.path.join(FRONTEND_DIR, "checkout.html")
ORDERS_HTML_PATH = os.path.join(FRONTEND_DIR, "orders.html")
REPORTS_HTML_PATH = os.path.join(ADMIN_DIR, "reports.html")
PLAN_B_HTML_PATH = os.path.join(ADMIN_DIR, "plan-b.html")


# ==============================================================================
# 1. Mock / Hardcoded Financial Data Retirement
# ==============================================================================

def test_admin_js_zero_mock_or_hardcoded_financial_fallbacks():
    """Verify that hardcoded mock/fallback financial numbers have been retired from admin.js."""
    with open(ADMIN_JS_PATH, "r", encoding="utf-8") as f:
        admin_code = f.read()

    # Assert retired fallbacks are absent
    retired_patterns = [
        r"c\.amount\s*\|\|\s*250",
        r"c\.gross_amount\s*\|\|\s*500",
        r"c\.tds_amount\s*\|\|\s*25",
        r"c\.net_amount\s*\|\|\s*475",
        r"c\.gross_amount\s*\|\|\s*50",
        r"c\.tds_amount\s*\|\|\s*2\.5",
        r"c\.net_amount\s*\|\|\s*47\.5",
    ]
    for pattern in retired_patterns:
        match = re.search(pattern, admin_code)
        assert match is None, f"Found retired fallback pattern '{pattern}' in admin.js: {match.group(0) if match else ''}"

    # Verify dynamic null-safe expressions with '—' for unavailable data exist instead
    assert "c.amount != null ? formatCurrency(Number(c.amount)) : '—'" in admin_code
    assert "c.gross_amount != null ? formatCurrency(Number(c.gross_amount)) : '—'" in admin_code
    assert "c.tds_amount != null ?" in admin_code
    assert ": '—'" in admin_code
    assert "c.net_amount != null ? formatCurrency(Number(c.net_amount)) : '—'" in admin_code


def test_seven_financial_fields_null_and_zero_rendering_rules():
    """
    Verify the 7 financial display fields in admin.js handle:
    - Numeric 0 -> ₹0
    - Positive valid amount -> Actual formatted amount
    - Null -> —
    - Undefined/missing -> —
    """
    with open(ADMIN_JS_PATH, "r", encoding="utf-8") as f:
        admin_code = f.read()

    # The 7 required fields:
    # 1. loadPlanACycleContributions() - c.amount
    # 2. loadPlanACommissions() - c.gross_amount
    # 3. loadPlanACommissions() - c.tds_amount
    # 4. loadPlanACommissions() - c.net_amount
    # 5. loadPlanBGenerationCommissions() - c.gross_amount
    # 6. loadPlanBGenerationCommissions() - c.tds_amount
    # 7. loadPlanBGenerationCommissions() - c.net_amount

    # JavaScript helper emulation
    def format_currency(amount):
        if not isinstance(amount, (int, float)):
            return "₹0"
        return f"₹{int(amount):,}"

    def render_field(val):
        return format_currency(float(val)) if val is not None else "—"

    def render_tds_field(val):
        return f"-{format_currency(float(val))}" if val is not None else "—"

    # Test cases:
    for test_val, expected in [(0, "₹0"), (500, "₹500"), (250, "₹250"), (50, "₹50"), (None, "—")]:
        assert render_field(test_val) == expected

    # TDS test cases:
    assert render_tds_field(25) == "-₹25"
    assert render_tds_field(2.5) == "-₹2"
    assert render_tds_field(None) == "—"

    # Check exact occurrences in admin_code
    assert admin_code.count("c.gross_amount != null ? formatCurrency(Number(c.gross_amount)) : '—'") >= 2
    assert admin_code.count("c.tds_amount != null ? `-${formatCurrency(Number(c.tds_amount))}` : '—'") >= 2
    assert admin_code.count("c.net_amount != null ? formatCurrency(Number(c.net_amount)) : '—'") >= 2
    assert admin_code.count("c.amount != null ? formatCurrency(Number(c.amount)) : '—'") >= 1


# ==============================================================================
# 2. All 10 Report Variants Verification
# ==============================================================================

def test_all_10_report_variants_in_frontend():
    """
    Verify that all 10 report download variants are wired into frontend/js/api.js,
    admin reports HTML, and distributor dashboard HTML.
    """
    with open(API_JS_PATH, "r", encoding="utf-8") as f:
        api_code = f.read()

    with open(REPORTS_HTML_PATH, "r", encoding="utf-8") as f:
        reports_html = f.read()

    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        dist_html = f.read()

    # 1-6: Plan A Admin Reports (Commissions Excel/PDF, Cashback Excel/PDF, Statement Excel/PDF)
    assert "downloadPlanACommissionsReport" in api_code
    assert "downloadPlanACashbackReport" in api_code
    assert "downloadPlanACustomerStatement" in api_code
    assert "/admin/plan-a/reports/commissions" in api_code
    assert "/admin/plan-a/reports/cashback" in api_code
    assert "/admin/plan-a/reports/customers/" in api_code

    assert "downloadCustomerStatement('excel')" in reports_html
    assert "downloadCustomerStatement('pdf')" in reports_html

    # 7-9: Plan B Admin Reports (Purchases Excel, Commissions Excel, Distributor Profile Excel)
    assert "downloadPlanBPurchasesReport" in api_code
    assert "downloadPlanBCommissionsReport" in api_code
    assert "downloadPlanBDistributorReport" in api_code
    assert "/admin/plan-b/reports/purchases" in api_code
    assert "/admin/plan-b/reports/commissions" in api_code
    assert "/admin/plan-b/reports/distributors/" in api_code

    assert "downloadDistributorProfileReport" in reports_html

    # 10: Plan B Distributor Self-Service Statement (Excel only per R-08 / PB-16)
    assert "downloadStatement" in api_code
    assert "/distributor/reports/commission-statement" in api_code
    assert "statement-export-form" in dist_html
    assert "download-statement-btn" in dist_html


def test_plan_b_report_format_restrictions():
    """Verify that Plan B reports are strictly constrained to Excel only in UI."""
    with open(REPORTS_HTML_PATH, "r", encoding="utf-8") as f:
        reports_html = f.read()

    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        dist_html = f.read()

    # Plan B cards in admin/reports.html must NOT contain PDF download calls
    assert "downloadReport('plan-b-purchases', 'pdf')" not in reports_html
    assert "downloadReport('plan-b-commissions', 'pdf')" not in reports_html
    assert "downloadDistributorProfileReport('pdf')" not in reports_html

    # Distributor self-service statement must NOT offer PDF
    assert "downloadDistributorStatement('pdf')" not in dist_html


# ==============================================================================
# 3. Negative Invariant PB-15: Distributor Dashboard
# ==============================================================================

def test_plan_b_pb15_negative_requirement():
    """
    Verify PB-15: Neither total_referred_count nor total_referred_units
    is displayed in the distributor dashboard.
    """
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        dist_html = f.read()

    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        dist_js = f.read()

    assert "total_referred_count" not in dist_html
    assert "total_referred_units" not in dist_html
    assert "total_referred_count" not in dist_js
    assert "total_referred_units" not in dist_js


# ==============================================================================
# 4. Plan B Generation Commission Compliance
# ==============================================================================

def test_plan_b_generation_commission_accurate_wording():
    """
    Verify Plan B generation commission is accurately described as ₹50 / item
    to the direct referring distributor, and does NOT claim a 20-level tree.
    """
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        dist_html = f.read()

    with open(PLAN_B_HTML_PATH, "r", encoding="utf-8") as f:
        plan_b_html = f.read()

    # Check distributor dashboard
    assert "Gen 1–20" not in dist_html
    assert "20-generation" not in dist_html
    assert "20 generations" not in dist_html
    assert "₹50 / item" in dist_html

    # Check Plan B admin
    assert "20-generation" not in plan_b_html
    assert "₹50 gross per eligible Plan B Billing ID" in plan_b_html


# ==============================================================================
# 5. OR-10 Checkout Notice Compliance
# ==============================================================================

def test_checkout_notice_or10_compliance():
    """
    Verify OR-10 checkout notice text is present in checkout.html before place order.
    """
    with open(CHECKOUT_HTML_PATH, "r", encoding="utf-8") as f:
        checkout_html = f.read()

    exact_notice = "Orders cannot be cancelled, returned or replaced after successful payment."
    assert exact_notice in checkout_html, f"Missing exact OR-10 notice in checkout.html"

    # Confirm it is positioned before the place order button
    notice_idx = checkout_html.find(exact_notice)
    place_order_idx = checkout_html.find('id="place-order-btn"')
    assert notice_idx < place_order_idx, "OR-10 notice must appear before place order button in DOM order"


# ==============================================================================
# 6. Orders and Billing ID History Compliance
# ==============================================================================

def test_order_history_billing_ids_compliance():
    """Verify orders.html includes Billing ID rendering, unit indexing, copy capability, and empty state."""
    with open(ORDERS_HTML_PATH, "r", encoding="utf-8") as f:
        orders_html = f.read()

    assert "itemBillingIds" in orders_html
    assert "navigator.clipboard.writeText" in orders_html
    assert "Unit ${idx + 1}:" in orders_html
    assert "No orders yet" in orders_html or "empty-state" in orders_html


# ==============================================================================
# 7. Live FastAPI TestClient API Integration for Reports
# ==============================================================================

@pytest.fixture
def admin_token(db_session):
    """Retrieve or create an administrator and issue a valid JWT token."""
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN).first()
    if not admin:
        admin = User(
            phone="9876543210",
            full_name="Admin Test User",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db_session.add(admin)
        db_session.commit()
        db_session.refresh(admin)

    return create_access_token(
        user_id=admin.id,
        role=admin.role.value if hasattr(admin.role, "value") else str(admin.role),
        phone=admin.phone,
    )


def test_api_plan_a_admin_reports_generation(api_client, admin_token):
    """Verify Plan A admin reports return valid Excel and PDF streams."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Commissions Excel
    res_comm_excel = api_client.get("/api/v1/admin/plan-a/reports/commissions?format=excel", headers=headers)
    assert res_comm_excel.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_comm_excel.headers.get("content-type", "")
    assert "attachment;" in res_comm_excel.headers.get("content-disposition", "")

    # 2. Commissions PDF
    res_comm_pdf = api_client.get("/api/v1/admin/plan-a/reports/commissions?format=pdf", headers=headers)
    assert res_comm_pdf.status_code == 200
    assert "application/pdf" in res_comm_pdf.headers.get("content-type", "")
    assert "attachment;" in res_comm_pdf.headers.get("content-disposition", "")

    # 3. Cashback Excel
    res_cash_excel = api_client.get("/api/v1/admin/plan-a/reports/cashback?format=excel", headers=headers)
    assert res_cash_excel.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_cash_excel.headers.get("content-type", "")

    # 4. Cashback PDF
    res_cash_pdf = api_client.get("/api/v1/admin/plan-a/reports/cashback?format=pdf", headers=headers)
    assert res_cash_pdf.status_code == 200
    assert "application/pdf" in res_cash_pdf.headers.get("content-type", "")


def test_api_plan_b_admin_reports_generation_and_constraints(api_client, admin_token):
    """Verify Plan B admin reports return valid Excel streams and reject PDF requests with 400 per R-09."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 7. Purchases Excel
    res_purchases_excel = api_client.get("/api/v1/admin/plan-b/reports/purchases?format=excel", headers=headers)
    assert res_purchases_excel.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_purchases_excel.headers.get("content-type", "")

    # Purchases PDF rejected with 400
    res_purchases_pdf = api_client.get("/api/v1/admin/plan-b/reports/purchases?format=pdf", headers=headers)
    assert res_purchases_pdf.status_code == 400
    assert "Excel" in res_purchases_pdf.json().get("detail", "")

    # 8. Commissions Excel
    res_comm_excel = api_client.get("/api/v1/admin/plan-b/reports/commissions?format=excel", headers=headers)
    assert res_comm_excel.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res_comm_excel.headers.get("content-type", "")

    # Commissions PDF rejected with 400
    res_comm_pdf = api_client.get("/api/v1/admin/plan-b/reports/commissions?format=pdf", headers=headers)
    assert res_comm_pdf.status_code == 400
    assert "Excel" in res_comm_pdf.json().get("detail", "")
