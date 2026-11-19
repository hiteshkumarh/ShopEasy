"""
backend/tests/test_distributor_dashboard_ui_update.py
Test suite for Distributor Dashboard UI Updates:
1. Verify removal of Sequential Wallet summary card.
2. Verify removal of Start Date and End Date from Statement Export section.
3. Verify removal of Direct Storefront Onboarding Link while preserving Referral Code.
4. Verify removal of Distributor Notifications & System Alerts section.
5. Verify preservation of 4 KPI summary cards, My Purchases & Billing IDs, Ledger, and Withdrawals.
6. Verify backend /api/v1/distributor/reports/commission-statement returns .xlsx without date parameters.
"""

import os
import re
import pytest
from fastapi.testclient import TestClient

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
DISTRIBUTOR_HTML_PATH = os.path.join(FRONTEND_DIR, "distributor-dashboard.html")
DISTRIBUTOR_JS_PATH = os.path.join(FRONTEND_DIR, "js", "distributor-dashboard.js")


def test_sequential_wallet_card_removed():
    """Verify Sequential Wallet card is completely removed from distributor-dashboard.html."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert "Sequential Wallet" not in html
    assert "Plan A Only" not in html
    assert "Exclusive to Plan A Customer Queue" not in html


def test_statement_export_date_inputs_removed_and_download_retained():
    """Verify Start Date and End Date inputs are removed, but download button is preserved."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Removed date inputs
    assert 'id="statement-start-date"' not in html
    assert 'id="statement-end-date"' not in html
    assert 'label for="statement-start-date"' not in html
    assert 'label for="statement-end-date"' not in html

    # Retained statement elements
    assert 'id="statement-section"' in html
    assert 'id="statement-export-form"' in html
    assert 'id="download-statement-btn"' in html
    assert "Download Statement (.xlsx)" in html
    assert "Official Commission Statement Export" in html
    assert "EXCEL (.XLSX) ONLY" in html


def test_direct_storefront_onboarding_link_removed_referral_code_retained():
    """Verify Direct Storefront Onboarding Link is removed, but Referral Code and Copy Code are retained."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Removed onboarding link
    assert "Direct Storefront Onboarding Link" not in html
    assert 'id="distributor-referral-link"' not in html
    assert 'id="copy-ref-link-btn"' not in html

    # Retained referral code
    assert 'id="distributor-referral-code"' in html
    assert 'id="copy-ref-code-btn"' in html
    assert "Your Official Plan B Referral Identity" in html
    assert "Copy Code" in html


def test_notifications_and_system_alerts_section_removed():
    """Verify the entire Distributor Notifications & System Alerts section is removed."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="notifications-section"' not in html
    assert 'id="unread-notifications-count-badge"' not in html
    assert 'id="mark-all-read-btn"' not in html
    assert 'id="refresh-notifications-btn"' not in html
    assert 'id="notifications-list-container"' not in html
    assert "Distributor Notifications &amp; System Alerts" not in html
    assert "Distributor Notifications & System Alerts" not in html


def test_preserved_dashboard_sections_and_summary_cards():
    """Verify remaining 4 KPI cards and other functional sections are preserved."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    norm_html = re.sub(r"\s+", " ", html)

    # 4 Preserved KPI Cards
    assert 'id="stat-available-balance"' in html
    assert "Available Balance" in norm_html
    assert 'id="stat-direct-comm-total"' in html
    assert "Direct Bonuses Earned" in norm_html
    assert 'id="stat-gen-comm-total"' in html
    assert "Generation Commissions" in norm_html
    assert 'id="stat-withdrawn-total"' in html
    assert "Total Paid Out" in norm_html

    # Purchases & Billing IDs
    assert 'id="distributor-purchase-section"' in html
    assert 'id="distributor-purchase-container"' in html
    assert 'id="refresh-distributor-purchases-btn"' in html
    assert "My Purchases &amp; Billing IDs" in html

    # Commission Ledger
    assert 'id="commission-ledger-tbody"' in html
    assert 'id="ledger-filter-type"' in html
    assert "Plan B Commission Ledger" in html

    # Withdrawals
    assert 'id="withdraw-section"' in html
    assert 'id="distributor-withdraw-btn"' in html
    assert 'id="distributor-withdrawals-tbody"' in html
    assert 'id="distributor-modal-overlay"' in html
    assert 'id="modal-confirm-btn"' in html


from decimal import Decimal
import io
import openpyxl
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.main import app
from app.models.enums import Programme, UserRole, AccountStatus
from app.core.security import create_access_token
from app.models.user import User


def test_statement_export_endpoint_without_dates(db_session):
    """Verify backend statement export functions correctly without start_date or end_date parameters."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            # Create Plan B distributor
            distributor = User(
                phone="9019888777",
                full_name="Test Statement Distributor",
                referral_code="PBDIST01",
                programme=Programme.PLAN_B,
                role=UserRole.CUSTOMER,
                account_status=AccountStatus.ACTIVE,
                is_active=True,
            )
            db_session.add(distributor)
            db_session.commit()

            token = create_access_token(user_id=distributor.id, phone=distributor.phone, role="customer")
            headers = {"Authorization": f"Bearer {token}"}

            res = client.get(
                "/api/v1/distributor/reports/commission-statement?format=excel",
                headers=headers,
            )
            assert res.status_code == 200
            assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers["content-type"]
            assert res.content.startswith(b"PK")  # Standard ZIP / XLSX magic bytes

            wb = openpyxl.load_workbook(io.BytesIO(res.content))
            assert "Commission Statement" in wb.sheetnames
    finally:
        app.dependency_overrides.pop(get_db, None)
