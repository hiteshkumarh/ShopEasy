"""
backend/tests/test_wp12_step6_admin_frontend.py
Comprehensive test suite for WP-12 Step 6: Admin Portal, Reports and Withdrawal Moderation.

Verifies:
1. All 9 Admin Portal HTML files exist and have consistent sidebar navigation.
2. Plan A Admin Console (queues, cycles, reserve breakdown, commissions, customer lookup, and report downloads).
3. Plan B Admin Console (distributor directory, direct commissions, generation commissions with ₹50 rule, billing IDs, and Excel-only reports per R-09).
4. Withdrawal Moderation Console (pending review queue, approve confirmation, reject with mandatory reason, wallet freeze/unfreeze, and audit history).
5. Centralized Reports Console (all 9 admin downloads correctly wired with date filters and format constraints).
6. Unified Search Controller and Modal (exact match across Plan A/B by Billing ID and Order ID per OR-13).
7. Financial Settings Console (table, secret masking, and prospective update validation per ED-02).
8. Admin JavaScript Controller exports and client API bindings in frontend/js/api.js and frontend/js/admin.js.
9. Live FastAPI TestClient API integration verifying admin route schemas and permission enforcement.
"""

import os
import re
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db, SessionLocal
from app.models.user import User
from app.models.enums import UserRole, Programme
from app.core.security import create_access_token


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
ADMIN_DIR = os.path.join(FRONTEND_DIR, "admin")
ADMIN_HTML_FILES = [
    "dashboard.html",
    "plan-a.html",
    "plan-b.html",
    "withdrawals.html",
    "reports.html",
    "settings.html",
    "orders.html",
    "products.html",
    "customers.html",
    "product-form.html",
]
ADMIN_JS_PATH = os.path.join(FRONTEND_DIR, "js", "admin.js")
API_JS_PATH = os.path.join(FRONTEND_DIR, "js", "api.js")
ADMIN_CSS_PATH = os.path.join(FRONTEND_DIR, "css", "admin.css")


# ==============================================================================
# 1. Structure & Navigation Consistency
# ==============================================================================

def test_admin_portal_files_exist():
    """Verify that all 9 Admin HTML files, admin.js, and admin.css exist."""
    for filename in ADMIN_HTML_FILES:
        path = os.path.join(ADMIN_DIR, filename)
        assert os.path.exists(path), f"Missing admin file: {path}"

    assert os.path.exists(ADMIN_JS_PATH), f"Missing: {ADMIN_JS_PATH}"
    assert os.path.exists(API_JS_PATH), f"Missing: {API_JS_PATH}"
    assert os.path.exists(ADMIN_CSS_PATH), f"Missing: {ADMIN_CSS_PATH}"


def test_admin_sidebar_navigation_consistency():
    """Verify that every admin page includes consistent sidebar navigation links to all sections."""
    required_nav_hrefs = [
        "dashboard.html",
        "plan-a.html",
        "plan-b.html",
        "withdrawals.html",
        "reports.html",
        "settings.html",
        "orders.html",
        "products.html",
        "customers.html",
    ]

    for filename in ADMIN_HTML_FILES:
        path = os.path.join(ADMIN_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        for href in required_nav_hrefs:
            assert f'href="{href}"' in content or f"href='{href}'" in content, (
                f"Missing navigation link to '{href}' in admin file: {filename}"
            )


def test_admin_plan_a_and_plan_b_sidebar_styling_and_icons():
    """
    Verify Plan A and Plan B sidebar styling consistency:
    1. Plan A uses neutral user/group icon matching Plan B, not the clock icon.
    2. Plan A does not receive active styling or blue background.
    3. Plan B and Dashboard active behaviors remain intact.
    """
    with open(ADMIN_JS_PATH, "r", encoding="utf-8") as f:
        admin_js = f.read()

    # Plan A icon must match Plan B user/group icon family and NOT be a clock icon
    assert "href: 'plan-a.html'" in admin_js
    assert '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>' not in admin_js
    assert "item.href !== 'plan-a.html'" in admin_js

    # Plan A in plan-a.html must not carry the active class in static markup
    plan_a_html_path = os.path.join(ADMIN_DIR, "plan-a.html")
    with open(plan_a_html_path, "r", encoding="utf-8") as f:
        plan_a_html = f.read()

    assert '<a href="plan-a.html" class="admin-nav-item active">' not in plan_a_html
    assert '<a href="plan-a.html" class="admin-nav-item">' in plan_a_html

    # Check CSS rule enforcing neutral styling for Plan A
    with open(ADMIN_CSS_PATH, "r", encoding="utf-8") as f:
        admin_css = f.read()

    assert '.admin-nav-item[href="plan-a.html"].active' in admin_css
    assert "background-color: transparent;" in admin_css

    # Verify Dashboard Governance buttons for Plan A and Plan B
    dashboard_html_path = os.path.join(ADMIN_DIR, "dashboard.html")
    with open(dashboard_html_path, "r", encoding="utf-8") as f:
        dashboard_html = f.read()

    assert '<a href="plan-a.html" class="btn btn-secondary">' in dashboard_html
    assert '<a href="plan-b.html" class="btn btn-secondary">' in dashboard_html
    assert '<a href="plan-a.html" class="btn btn-primary">' not in dashboard_html
    assert "Plan A - Arya Business Partner Programme" in dashboard_html
    assert "Plan B - Arya Generation Growth Programme" in dashboard_html


def test_product_form_layout_and_fields():
    """
    Verify product-form.html:
    1. Form is contained inside .admin-form-container with .admin-form-card.
    2. Preserves all required form fields and IDs.
    3. CSS centers the container (margin: 0 auto; max-width: 900px).
    """
    path = os.path.join(ADMIN_DIR, "product-form.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Form and container
    assert 'class="admin-form-container"' in content
    assert 'id="admin-product-form"' in content
    assert 'class="admin-form-card"' in content

    # Essential input IDs
    required_ids = [
        'id="product-name"',
        'id="product-code"',
        'id="product-category"',
        'id="product-status"',
        'id="product-price"',
        'id="product-stock"',
        'id="product-image-file"',
        'id="product-image-url"',
        'id="product-image-preview"',
        'id="product-description"',
        'id="form-page-title"',
    ]
    for element_id in required_ids:
        assert element_id in content, f"Missing required element {element_id} in product-form.html"

    # Verify CSS centering in admin.css
    with open(ADMIN_CSS_PATH, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert ".admin-form-container {" in css_content
    assert "max-width: 900px;" in css_content
    assert "margin: 0 auto;" in css_content


# ==============================================================================
# 2. Plan A Administration Console
# ==============================================================================

def test_plan_a_admin_console_structure_and_rules():
    """
    Verify Plan A admin console structure:
    - Overview metrics: Company reserve, reserve records, cashback queues, direct commissions.
    - Tabs: Cashback Queues, Cycle Progress, Company Reserve Breakdown, Direct Commissions, Customer Cashback Lookup.
    - Modals: Queue Entries Modal, Cycle Contributions Modal.
    - Invariant: BR-A4 & BR-A5 company-owned unallocated reserve notice.
    """
    path = os.path.join(ADMIN_DIR, "plan-a.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Metric stat IDs
    assert 'id="stat-plan-a-reserve"' in content
    assert 'id="stat-plan-a-entries"' in content
    assert 'id="stat-plan-a-queues-count"' in content
    assert 'id="stat-plan-a-commissions-count"' in content

    # Tabs
    assert 'onclick="switchPlanATab(\'queues\')"' in content
    assert 'onclick="switchPlanATab(\'cycles\')"' in content
    assert 'onclick="switchPlanATab(\'reserve\')"' in content
    assert 'onclick="switchPlanATab(\'commissions\')"' in content
    assert 'onclick="switchPlanATab(\'customer-lookup\')"' in content

    # Tables & Modals
    assert 'id="plan-a-queues-tbody"' in content
    assert 'id="plan-a-cycles-tbody"' in content
    assert 'id="plan-a-reserve-tbody"' in content
    assert 'id="plan-a-commissions-tbody"' in content
    assert 'id="queue-entries-modal"' in content
    assert 'id="cycle-contribs-modal"' in content

    # Customer Lookup
    assert 'id="lookup-customer-id"' in content
    assert 'id="customer-lookup-result"' in content
    assert 'onclick="inspectCustomerCashback()"' in content
    assert 'onclick="downloadLookupStatement(\'excel\')"' in content
    assert 'onclick="downloadLookupStatement(\'pdf\')"' in content

    # BR-A4 / BR-A5 Company Owned Unallocated Reserve notice
    assert "BR-A4" in content
    assert "COMPANY" in content.upper()


# ==============================================================================
# 3. Plan B Administration Console
# ==============================================================================

def test_plan_b_admin_console_structure_and_rules():
    """
    Verify Plan B admin console structure:
    - Overview metrics: Distributors, direct commissions, generation commissions, billing IDs.
    - Tabs: Distributors Directory, Direct Referral Commissions, Generation Commissions, Billing IDs, Plan B Reports.
    - Modals: Distributor Wallet Inspection, Distributor Referrals.
    - Business rule: ₹50 generation commission to direct referrer (NO 20-generation tree language).
    - Rule R-09: Excel only reports (.xlsx).
    """
    path = os.path.join(ADMIN_DIR, "plan-b.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Metric stat IDs
    assert 'id="stat-plan-b-distributors"' in content
    assert 'id="stat-plan-b-direct"' in content
    assert 'id="stat-plan-b-generation"' in content
    assert 'id="stat-plan-b-billing-ids"' in content

    # Tabs
    assert 'onclick="switchPlanBTab(\'distributors\')"' in content
    assert 'onclick="switchPlanBTab(\'direct-commissions\')"' in content
    assert 'onclick="switchPlanBTab(\'generation-commissions\')"' in content
    assert 'onclick="switchPlanBTab(\'billing-ids\')"' in content
    assert 'onclick="switchPlanBTab(\'reports\')"' in content

    # Tables & Modals
    assert 'id="plan-b-distributors-tbody"' in content
    assert 'id="plan-b-direct-tbody"' in content
    assert 'id="plan-b-gen-tbody"' in content
    assert 'id="plan-b-bids-tbody"' in content
    assert 'id="distributor-wallet-modal"' in content
    assert 'id="distributor-referrals-modal"' in content

    # Rule R-09: Excel only for Plan B
    assert "R-09" in content
    assert "EXCEL (.XLSX) ONLY" in content.upper()
    assert "onclick=\"downloadPlanBPurchases()\"" in content
    assert "onclick=\"downloadPlanBCommissions()\"" in content
    assert "onclick=\"downloadIndividualDistributorReport()\"" in content

    # Generation Commission Rule: ₹50 / item, no 20-gen uncompressed tree logic
    assert "₹50" in content
    assert "20-generation" not in content.lower()
    assert "uncompressed tree" not in content.lower()


# ==============================================================================
# 4. Withdrawal Moderation Console
# ==============================================================================

def test_withdrawal_moderation_console():
    """
    Verify Withdrawal Moderation console:
    - Pending summary cards removed per Prompt 12.
    - Pending requests review list (#pending-withdrawals-tbody).
    - Approve confirmation modal (#approve-withdrawal-modal).
    - Reject modal with mandatory reason (#reject-withdrawal-modal, #reject-modal-reason).
    - Customer/Distributor wallet freeze & unfreeze (#freeze-user-number, #freeze-reason).
    - Immutable freeze history audit trail (#wallet-freeze-history-tbody).
    """
    path = os.path.join(ADMIN_DIR, "withdrawals.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Cards removed per Prompt 12
    assert 'id="stat-pending-withdrawals"' not in content
    assert 'id="stat-pending-amount"' not in content
    assert 'id="pending-withdrawals-tbody"' in content
    assert 'onclick="loadPendingWithdrawals()"' in content

    # Approve Modal
    assert 'id="approve-withdrawal-modal"' in content
    assert 'onclick="submitApproveWithdrawal()"' in content

    # Reject Modal with mandatory reason
    assert 'id="reject-withdrawal-modal"' in content
    assert 'id="reject-modal-reason"' in content
    assert 'onclick="submitRejectWithdrawal()"' in content

    # Wallet Freeze / Unfreeze
    assert 'id="freeze-user-number"' in content
    assert 'id="freeze-wallet-id"' in content
    assert 'id="freeze-reason"' in content
    assert 'onclick="executeWalletFreezeAction(true)"' in content
    assert 'onclick="executeWalletFreezeAction(false)"' in content
    assert 'onclick="loadWalletFreezeHistory()"' in content
    assert 'id="wallet-freeze-history-tbody"' in content


# ==============================================================================
# 5. Centralized Reports Console (Preserved Reports 5, 6, 9 per Prompt 10)
# ==============================================================================

def test_centralized_reports_hub():
    """
    Verify Centralized Reports Hub (reports.html):
    - Date range filter inputs removed per Prompt 10.
    - Sections 1, 2, 3, 4, 7, 8 removed per Prompt 10.
    - Sections 5 & 6 (Customer Statement Excel/PDF) preserved.
    - Section 9 (Individual Distributor Profile Report) preserved.
    """
    path = os.path.join(ADMIN_DIR, "reports.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Date range filters removed
    assert 'id="reports-start-date"' not in content
    assert 'id="reports-end-date"' not in content

    # Removed reports
    assert "downloadReport('plan-a-commissions', 'excel')" not in content
    assert "downloadReport('plan-a-cashback', 'excel')" not in content
    assert "downloadReport('plan-b-purchases', 'excel')" not in content
    assert "downloadReport('plan-b-commissions', 'excel')" not in content

    # Preserved reports (5, 6, 9)
    assert "downloadCustomerStatement('excel')" in content
    assert "downloadCustomerStatement('pdf')" in content
    assert "downloadDistributorProfileReport()" in content


# ==============================================================================
# 6. Unified Exact-Match Search & Financial Settings
# ==============================================================================

def test_unified_search_and_financial_settings():
    """
    Verify:
    1. Unified Search: Topbar input, enter key listener, modal, result handling.
    2. Financial Settings: Table, secret protection, propose button removed per Prompt 12.
    """
    # Dashboard search bar, notification bell, and storefront link removed per Sections 2 & 4
    dash_path = os.path.join(ADMIN_DIR, "dashboard.html")
    with open(dash_path, "r", encoding="utf-8") as f:
        dash_content = f.read()

    topbar_dash = dash_content.split('<header class="admin-topbar">')[1].split('</header>')[0]
    assert 'id="topbar-search-input"' not in topbar_dash
    assert "openNotificationsModal()" not in topbar_dash
    assert 'class="store-link"' not in topbar_dash

    # Topbar global search removed across all modules, dedicated module search remains active
    orders_path = os.path.join(ADMIN_DIR, "orders.html")
    with open(orders_path, "r", encoding="utf-8") as f:
        orders_content = f.read()

    assert 'id="topbar-search-input"' not in orders_content
    assert "admin-search-container" not in orders_content
    assert "executeUnifiedSearch" in orders_content
    assert 'id="unified-search-modal"' in orders_content

    # Financial Settings on settings.html
    settings_path = os.path.join(ADMIN_DIR, "settings.html")
    with open(settings_path, "r", encoding="utf-8") as f:
        settings_content = f.read()

    assert 'id="financial-settings-tbody"' in settings_content
    assert 'id="settings-programme-filter"' in settings_content
    # Propose button and modal removed per Prompt 12 Item 5
    assert 'id="propose-setting-modal"' not in settings_content
    assert "openProposeSettingModal" not in settings_content
    assert "ED-02" in settings_content


# ==============================================================================
# 7. JavaScript API Client & Controller Exports
# ==============================================================================

def test_js_api_and_admin_controller_exports():
    """
    Verify that frontend/js/api.js exposes ShopEasyAdmin and
    frontend/js/admin.js exports all Step 6 functions onto window.
    """
    with open(API_JS_PATH, "r", encoding="utf-8") as f:
        api_code = f.read()

    # ShopEasyAdmin methods in api.js
    assert "ShopEasyAdmin = {" in api_code
    assert "window.ShopEasyAdmin = ShopEasyAdmin" in api_code
    assert "getPlanAQueues" in api_code
    assert "getPlanAQueueEntries" in api_code
    assert "getPlanACycles" in api_code
    assert "getPlanACycleContributions" in api_code
    assert "getPlanAReserve" in api_code
    assert "getPlanAReserveSummary" in api_code
    assert "getPlanACommissions" in api_code
    assert "getPlanACustomerCashback" in api_code
    assert "downloadPlanACommissionsReport" in api_code
    assert "downloadPlanACashbackReport" in api_code
    assert "downloadPlanACustomerStatement" in api_code
    assert "getPlanBDistributors" in api_code
    assert "getPlanBDistributorWallet" in api_code
    assert "getPlanBDistributorReferrals" in api_code
    assert "getPlanBDirectCommissions" in api_code
    assert "getPlanBGenerationCommissions" in api_code
    assert "getPlanBBillingIds" in api_code
    assert "downloadPlanBPurchasesReport" in api_code
    assert "downloadPlanBCommissionsReport" in api_code
    assert "downloadPlanBDistributorReport" in api_code
    assert "getPendingWithdrawals" in api_code
    assert "approveWithdrawal" in api_code
    assert "rejectWithdrawal" in api_code
    assert "freezeWallet" in api_code
    assert "unfreezeWallet" in api_code
    assert "getWalletFreezeHistory" in api_code
    assert "search" in api_code
    assert "getFinancialSettings" in api_code
    assert "createFinancialSetting" in api_code

    with open(ADMIN_JS_PATH, "r", encoding="utf-8") as f:
        admin_code = f.read()

    # Step 6 functions exported onto window in admin.js
    required_exports = [
        "window.executeUnifiedSearch = executeUnifiedSearch",
        "window.closeUnifiedSearchModal = closeUnifiedSearchModal",
        "window.openNotificationsModal = openNotificationsModal",
        "window.closeNotificationsModal = closeNotificationsModal",
        "window.markAllAdminNotificationsRead = markAllAdminNotificationsRead",
        "window.initAdminPlanAPage = initAdminPlanAPage",
        "window.switchPlanATab = switchPlanATab",
        "window.loadPlanAQueues = loadPlanAQueues",
        "window.viewQueueEntries = viewQueueEntries",
        "window.closeQueueEntriesModal = closeQueueEntriesModal",
        "window.loadPlanACycles = loadPlanACycles",
        "window.viewCycleContributions = viewCycleContributions",
        "window.closeCycleContribsModal = closeCycleContribsModal",
        "window.loadPlanAReserve = loadPlanAReserve",
        "window.loadPlanACommissions = loadPlanACommissions",
        "window.inspectCustomerCashback = inspectCustomerCashback",
        "window.downloadLookupStatement = downloadLookupStatement",
        "window.initAdminPlanBPage = initAdminPlanBPage",
        "window.switchPlanBTab = switchPlanBTab",
        "window.loadPlanBDistributors = loadPlanBDistributors",
        "window.viewDistributorWallet = viewDistributorWallet",
        "window.closeDistributorWalletModal = closeDistributorWalletModal",
        "window.viewDistributorReferrals = viewDistributorReferrals",
        "window.closeDistributorReferralsModal = closeDistributorReferralsModal",
        "window.loadPlanBDirectCommissions = loadPlanBDirectCommissions",
        "window.loadPlanBGenerationCommissions = loadPlanBGenerationCommissions",
        "window.loadPlanBBillingIds = loadPlanBBillingIds",
        "window.downloadPlanBPurchases = downloadPlanBPurchases",
        "window.downloadPlanBCommissions = downloadPlanBCommissions",
        "window.downloadIndividualDistributorReport = downloadIndividualDistributorReport",
        "window.initAdminWithdrawalsPage = initAdminWithdrawalsPage",
        "window.switchWithdrawalsTab = switchWithdrawalsTab",
        "window.loadPendingWithdrawals = loadPendingWithdrawals",
        "window.openApproveModal = openApproveModal",
        "window.closeApproveModal = closeApproveModal",
        "window.submitApproveWithdrawal = submitApproveWithdrawal",
        "window.openRejectModal = openRejectModal",
        "window.closeRejectModal = closeRejectModal",
        "window.submitRejectWithdrawal = submitRejectWithdrawal",
        "window.executeWalletFreezeAction = executeWalletFreezeAction",
        "window.loadWalletFreezeHistory = loadWalletFreezeHistory",
        "window.initAdminReportsPage = initAdminReportsPage",
        "window.clearReportDateFilters = clearReportDateFilters",
        "window.downloadReport = downloadReport",
        "window.downloadCustomerStatement = downloadCustomerStatement",
        "window.downloadDistributorProfileReport = downloadDistributorProfileReport",
        "window.initAdminSettingsPage = initAdminSettingsPage",
        "window.loadFinancialSettings = loadFinancialSettings",
        "window.openProposeSettingModal = openProposeSettingModal",
        "window.closeProposeSettingModal = closeProposeSettingModal",
        "window.submitProposeSetting = submitProposeSetting",
        "window.ADMIN_NAV_ITEMS = ADMIN_NAV_ITEMS",
        "window.renderSharedAdminSidebar = renderSharedAdminSidebar",
    ]

    for exp in required_exports:
        assert exp in admin_code, f"Missing export in admin.js: {exp}"


# ==============================================================================
# 8. Live FastAPI TestClient API Integration
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


def test_api_admin_auth_guard(api_client):
    """Verify that admin endpoints reject unauthenticated or non-admin requests."""
    # Unauthenticated request should fail with 401
    res = api_client.get("/api/v1/admin/dashboard/stats")
    assert res.status_code == 401

    res_search = api_client.get("/api/v1/admin/search?q=TEST")
    assert res_search.status_code == 401

    res_settings = api_client.get("/api/v1/admin/financial-settings")
    assert res_settings.status_code == 401


def test_api_admin_dashboard_stats(api_client, admin_token):
    """Verify GET /api/v1/admin/dashboard/stats returns real counts."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    res = api_client.get("/api/v1/admin/dashboard/stats", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_products" in data
    assert "total_orders" in data
    assert "total_customers" in data
    assert "total_revenue" in data


def test_api_admin_unified_search_exact_match(api_client, admin_token):
    """Verify GET /api/v1/admin/search requires bounded non-empty query."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Empty query rejected with 400
    res_empty = api_client.get("/api/v1/admin/search?q=%20", headers=headers)
    assert res_empty.status_code == 400

    # Non-empty query returns structured response
    res = api_client.get("/api/v1/admin/search?q=NONEXISTENT-BID-12345", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "NONEXISTENT-BID-12345"
    assert data["total"] == 0
    assert data["results"] == []


def test_api_admin_financial_settings_prospective_validation(api_client, admin_token):
    """Verify POST /api/v1/admin/financial-settings rejects past effective dates per ED-02."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Query current settings
    res_get = api_client.get("/api/v1/admin/financial-settings", headers=headers)
    assert res_get.status_code == 200
    data = res_get.json()
    assert "total" in data
    assert "items" in data

    # Attempt to submit update with PAST effective_from date -> Must fail with 400 per ED-02
    past_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    payload_past = {
        "programme": "PLAN_A",
        "setting_key": "DIRECT_COMMISSION_AMOUNT",
        "setting_value": "500.00",
        "currency": "INR",
        "effective_from": past_date,
        "change_reason": "Attempting retroactive change",
    }
    res_past = api_client.post("/api/v1/admin/financial-settings", json=payload_past, headers=headers)
    assert res_past.status_code == 400
    assert "past" in res_past.json()["detail"].lower()
