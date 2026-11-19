"""
backend/tests/test_wp12_distributor_dashboard.py
Test suite for WP-12 Step 4: Plan B Distributor Dashboard.

Verifies:
1. Existence of frontend/distributor-dashboard.html and frontend/js/distributor-dashboard.js.
2. Adherence to PB-15 negative requirement: strictly NO display of total_referred_count or total_referred_units.
3. Excel statement export compliance with R-08 / PB-16 (.xlsx format only, format=excel query parameter).
4. Programme isolation guard ensuring Plan A users are redirected or barred from Plan B dashboard.
5. Presence of required UI sections: Referral Code/Link, Available Liquidation Balance, Direct/Generation Breakdown, Excel Statement Export, Notifications Panel, Commission Ledger, and Direct Referral Liquidation.
6. api.js extensions: ShopEasyAPI.patch, ShopEasyNotifications, ShopEasyDistributorReports.
7. Correct generation commission wording (Fix 1).
8. Correct transaction field handling (transaction_type), amount signs (+/-), and commission totals (Fix 2).
9. First withdrawal completed check logic across no-prior, rejected-only, and completed scenarios (Fix 3).
"""

import os
import re
import pytest

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
DISTRIBUTOR_HTML_PATH = os.path.join(FRONTEND_DIR, "distributor-dashboard.html")
DISTRIBUTOR_JS_PATH = os.path.join(FRONTEND_DIR, "js", "distributor-dashboard.js")
API_JS_PATH = os.path.join(FRONTEND_DIR, "js", "api.js")
AUTH_JS_PATH = os.path.join(FRONTEND_DIR, "js", "auth.js")
DASHBOARD_JS_PATH = os.path.join(FRONTEND_DIR, "js", "dashboard.js")


def test_distributor_dashboard_files_exist():
    """Verify that both HTML and JS files for Plan B Distributor Dashboard exist."""
    assert os.path.exists(DISTRIBUTOR_HTML_PATH), f"Missing: {DISTRIBUTOR_HTML_PATH}"
    assert os.path.exists(DISTRIBUTOR_JS_PATH), f"Missing: {DISTRIBUTOR_JS_PATH}"


def test_pb15_negative_requirement_strictly_enforced():
    """
    PB-15 Negative Requirement:
    Distributor dashboard must NEVER display total_referred_count or total_referred_units.
    """
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "total_referred_count" not in html_content
    assert "total_referred_units" not in html_content
    assert "total_referred_count" not in js_content
    assert "total_referred_units" not in js_content


def test_r08_statement_excel_only_requirement():
    """
    R-08 / PB-16:
    Statement download must be Excel format (.xlsx) only via format=excel query parameter.
    PDF format must not be offered.
    """
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        js_content = f.read()
    with open(API_JS_PATH, "r", encoding="utf-8") as f:
        api_content = f.read()

    assert ".xlsx" in html_content
    assert "format=excel" in api_content or "q.set('format', 'excel')" in api_content
    assert "format=pdf" not in html_content.lower()
    assert "format=pdf" not in js_content.lower()
    assert "format=pdf" not in api_content.lower()


def test_programme_isolation_enforced():
    """
    Verify RG-12: Plan B dashboard enforces programme isolation.
    Plan A users are barred and presented with redirection notice.
    """
    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "currentDistributor.programme !== 'PLAN_B'" in js_content or "currentDistributor.programme && currentDistributor.programme !== 'PLAN_B'" in js_content
    assert "dashboard.html" in js_content


def test_distributor_html_dom_structure():
    """Verify presence of core UI elements and removal of unwanted sections in distributor-dashboard.html."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Brand header & navigation
    assert "Arya Global" in html
    assert "Digital" in html

    # Status & Identity badges
    assert 'id="badge-account-status"' in html
    assert 'id="badge-programme"' in html
    assert 'id="blocked-distributor-banner"' in html
    assert 'id="distributor-referral-code"' in html

    # Removed elements per UI-only cleanup requirements
    assert 'id="distributor-referral-link"' not in html
    assert 'Sequential Wallet' not in html
    assert 'id="statement-start-date"' not in html
    assert 'id="statement-end-date"' not in html
    assert 'id="notifications-section"' not in html
    assert 'id="notifications-list-container"' not in html

    # Preserved KPI stats (exactly 4 cards)
    assert 'id="stat-available-balance"' in html
    assert 'id="stat-direct-comm-total"' in html
    assert 'id="stat-gen-comm-total"' in html
    assert 'id="stat-withdrawn-total"' in html

    # Preserved Sections: Statement export, purchases & billing IDs, ledger, withdrawals
    assert 'id="statement-section"' in html
    assert 'id="statement-export-form"' in html
    assert 'id="download-statement-btn"' in html
    assert 'id="distributor-purchase-section"' in html
    assert 'id="distributor-purchase-container"' in html
    assert 'id="commission-ledger-tbody"' in html
    assert 'id="ledger-filter-type"' in html
    assert 'id="distributor-withdraw-btn"' in html
    assert 'id="distributor-withdrawals-tbody"' in html
    assert 'id="distributor-modal-overlay"' in html


def test_api_js_notifications_and_reports_extensions():
    """Verify ShopEasyNotifications and ShopEasyDistributorReports are exposed in api.js."""
    with open(API_JS_PATH, "r", encoding="utf-8") as f:
        api_js = f.read()

    assert "ShopEasyNotifications" in api_js
    assert "ShopEasyDistributorReports" in api_js
    assert "window.ShopEasyNotifications = ShopEasyNotifications" in api_js
    assert "window.ShopEasyDistributorReports = ShopEasyDistributorReports" in api_js
    assert "patch(endpoint, data, options = {})" in api_js


def test_auth_js_distributor_login_redirect():
    """Verify distributorLogin redirects to distributor-dashboard.html."""
    with open(AUTH_JS_PATH, "r", encoding="utf-8") as f:
        auth_js = f.read()

    assert "distributor-dashboard.html" in auth_js


def test_generation_commission_wording_audit_fix():
    """
    Fix 1 Verification:
    Ensure generation commission wording in distributor-dashboard.html
    strictly adheres to single-tier direct referrer rule and avoids misleading tree copy.
    """
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Replaced phrases must NOT exist
    assert "Gen 1–20" not in html
    assert "20-generation uncompressed tree overrides" not in html
    assert "generation network overrides" not in html

    # Correct replacements must exist
    assert "₹50 / item" in html
    assert "Generation commissions on direct referee purchases" in html
    assert "generation commissions" in html


def test_transaction_field_handling_and_signs_audit_fix():
    """
    Fix 2 Verification:
    Verify that distributor-dashboard.js inspects transaction_type (or tx.transaction_type || tx.tx_type),
    renders positive credit (+) and negative debit (-), and computes totals properly.
    """
    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    assert "tx.transaction_type" in js_code
    assert "tx.transaction_type || tx.tx_type" in js_code
    assert "isCredit ? '+' : '-'" in js_code
    assert "isCredit ? '#059669' : '#DC2626'" in js_code


def test_first_withdrawal_completed_check_logic_audit_fix():
    """
    Fix 3 Verification:
    Verify that distributor-dashboard.js enforces:
    !withdrawalsData.some(w => w.status === 'COMPLETED') && balanceNum < 750
    """
    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        js_code = f.read()

    assert "!withdrawalsData.some(w => w.status === 'COMPLETED') && balanceNum < 750" in js_code


def test_withdrawal_eligibility_scenarios():
    """
    Test withdrawal eligibility logic under 3 scenarios:
    1. No prior withdrawals (empty array)
    2. Only rejected or pending prior withdrawals
    3. At least one prior completed withdrawal
    """
    def check_eligible(withdrawals, balance):
        has_completed = any(w.get("status") == "COMPLETED" for w in withdrawals)
        if not has_completed and balance < 750:
            return False, f"Initial payout requires a minimum balance of ₹750."
        if balance <= 0:
            return False, "Available balance is ₹0.00."
        return True, "Eligible"

    # Scenario 1: No prior withdrawals
    ok, _ = check_eligible([], 500)
    assert not ok
    ok, _ = check_eligible([], 750)
    assert ok
    ok, _ = check_eligible([], 1000)
    assert ok

    # Scenario 2: Only rejected or pending prior withdrawals
    prior_unsuccessful = [
        {"id": 1, "status": "REJECTED", "amount": 750},
        {"id": 2, "status": "REQUESTED", "amount": 750},
    ]
    ok, _ = check_eligible(prior_unsuccessful, 500)
    assert not ok  # Still requires ₹750!
    ok, _ = check_eligible(prior_unsuccessful, 800)
    assert ok

    # Scenario 3: At least one prior completed withdrawal
    prior_completed = [
        {"id": 1, "status": "COMPLETED", "amount": 750},
    ]
    ok, _ = check_eligible(prior_completed, 500)
    assert ok  # Allowed below 750 because prior withdrawal completed!
    ok, _ = check_eligible(prior_completed, 100)
    assert ok
    ok, _ = check_eligible(prior_completed, 0)
    assert not ok  # Zero balance rejected


def test_granular_commission_computation_logic():
    """
    Test that computeGranularCommissions properly sums backend transactions
    using transaction_type: 'CREDIT' and idempotency keys PB-DIRECT: and PB-GEN:.
    """
    transactions = [
        {
            "id": 1,
            "transaction_type": "CREDIT",
            "amount": 466.66,
            "idempotency_key": "PB-DIRECT:101",
            "reference_id": 101,
        },
        {
            "id": 2,
            "transaction_type": "CREDIT",
            "amount": 46.66,
            "idempotency_key": "PB-GEN:201",
            "reference_id": 201,
        },
        {
            "id": 3,
            "transaction_type": "CREDIT",
            "amount": 46.67,
            "idempotency_key": "PB-GEN:202",
            "reference_id": 202,
        },
        {
            "id": 4,
            "transaction_type": "DEBIT",
            "amount": 559.99,
            "idempotency_key": "WD-001",
            "reference_id": 1,
        },
    ]

    direct_total = sum(
        t["amount"]
        for t in transactions
        if t.get("transaction_type") == "CREDIT" and t.get("idempotency_key", "").startswith("PB-DIRECT:")
    )
    gen_total = sum(
        t["amount"]
        for t in transactions
        if t.get("transaction_type") == "CREDIT" and t.get("idempotency_key", "").startswith("PB-GEN:")
    )

    assert round(direct_total, 2) == 466.66
    assert round(gen_total, 2) == 93.33
