"""
backend/tests/test_distributor_dashboard_overview_api_and_contract.py
Test suite for Plan B Distributor Dashboard Overview API and Frontend Contract:
1. Verify ShopEasyDistributorReports.getDashboardOverview is defined in api.js.
2. Verify 'once per customer' is corrected to 'once per distributor lifetime' in distributor-dashboard.html.
3. Verify computeGranularCommissions excludes non-PB-DIRECT (e.g. PA-COMM:) in distributor-dashboard.js.
4. Verify backend /api/v1/distributor/reports/dashboard-overview endpoint security & role gating.
5. Verify live composite metrics, direct list, and generation list from the overview endpoint.
"""

from decimal import Decimal
import os
import re
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.models.billing import BillingCounter
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator
from app.services.commission.plan_b import PlanBCommissionService
from app.services.reports.plan_b_reports import PlanBReportService


from tests.test_plan_b_permanent_engine import create_order, ensure_counter


FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
DISTRIBUTOR_HTML_PATH = os.path.join(FRONTEND_DIR, "distributor-dashboard.html")
DISTRIBUTOR_JS_PATH = os.path.join(FRONTEND_DIR, "js", "distributor-dashboard.js")
API_JS_PATH = os.path.join(FRONTEND_DIR, "js", "api.js")


# ---------------------------------------------------------------------------
# 1. Frontend Contract & Static Assertions
# ---------------------------------------------------------------------------

def test_api_js_defines_distributor_reports_get_dashboard_overview():
    """Verify frontend/js/api.js implements getDashboardOverview on ShopEasyDistributorReports."""
    with open(API_JS_PATH, "r", encoding="utf-8") as f:
        api_js = f.read()

    assert "getDashboardOverview" in api_js
    assert "/distributor/reports/dashboard-overview" in api_js


def test_distributor_dashboard_html_lifetime_rule_copy():
    """Verify distributor-dashboard.html does NOT contain '₹500 ONCE PER CUSTOMER' and contains lifetime rule."""
    with open(DISTRIBUTOR_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    assert "₹500 ONCE PER CUSTOMER" not in html
    assert "₹500 ONCE PER DISTRIBUTOR LIFETIME" in html
    assert "awarded strictly once per distributor lifetime" in html

    # Verify no raw unescaped CSS attribute text is leaked into card labels
    assert '</span> style="font-size' not in html
    assert '</span>\n              style="font-size' not in html


def test_distributor_dashboard_js_no_misclassification_of_plan_a():
    """Verify distributor-dashboard.js strictly excludes PA-COMM or unknown credits from Plan B direct bonus."""
    with open(DISTRIBUTOR_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    assert "overviewLoaded" in js
    # Confirm that 'else: directTotal += amt' fallback has been eliminated
    assert "else {\n            directTotal += amt;\n          }" not in js
    assert "directTotal += amt;" not in js.split("else")[0]  # only under PB-DIRECT


# ---------------------------------------------------------------------------
# 2. Backend API Endpoint & RBAC Verification (Isolated SQLite)
# ---------------------------------------------------------------------------

def test_dashboard_overview_rbac_and_data(db_session: Session):
    """Verify /api/v1/distributor/reports/dashboard-overview enforces authentication, Plan B role, and returns composite data."""
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with TestClient(app) as client:
            # 1. Anonymous access -> 401
            res_anon = client.get("/api/v1/distributor/reports/dashboard-overview")
            assert res_anon.status_code == 401

            # 2. Plan A customer access -> 403 Forbidden
            plan_a_user = User(
                phone="9811001100",
                full_name="Plan A Customer",
                referral_code="PACUST01",
                programme=Programme.PLAN_A,
                role=UserRole.CUSTOMER,
                account_status=AccountStatus.ACTIVE,
                is_active=True,
            )
            db_session.add(plan_a_user)
            db_session.commit()

            token_a = create_access_token(user_id=plan_a_user.id, phone=plan_a_user.phone, role="customer")
            res_a = client.get(
                "/api/v1/distributor/reports/dashboard-overview",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert res_a.status_code == 403
            assert "Plan B distributor privileges required" in res_a.json()["detail"]

            # 3. Plan B distributor with 0 commissions initially
            dist = User(
                phone="9822002200",
                full_name="Plan B Distributor Overview",
                referral_code="PBOVER99",
                programme=Programme.PLAN_B,
                role=UserRole.CUSTOMER,
                account_status=AccountStatus.ACTIVE,
                is_active=True,
            )
            db_session.add(dist)
            db_session.commit()

            token_b = create_access_token(user_id=dist.id, phone=dist.phone, role="customer")
            res_b_empty = client.get(
                "/api/v1/distributor/reports/dashboard-overview",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert res_b_empty.status_code == 200
            data_empty = res_b_empty.json()
            assert data_empty["distributor"]["id"] == dist.id
            assert data_empty["summary_metrics"]["lifetime_direct_earned"] == 0.0
            assert data_empty["summary_metrics"]["generation_commission_earned"] == 0.0
            assert data_empty["summary_metrics"]["total_gross_commission"] == 0.0
            assert data_empty["summary_metrics"]["total_net_commission_earned"] == 0.0
            assert data_empty["direct_commissions"] == []
            assert data_empty["generation_commissions"] == []

            # 4. Now process a qualifying purchase for referred customer
            ensure_counter(db_session)
            prod = Product(
                name="Solar Power Bank",
                price=Decimal("3999.00"),
                stock=100,
                is_active=True,
                is_power_bank=True,
            )
            db_session.add(prod)
            db_session.commit()

            # Distributor qualification order
            dist_order = create_order(db_session, dist, prod, quantity=1)
            FulfilmentOrchestrator.fulfil_order(dist_order.id, db=db_session)

            # Referred Customer 1 buys 2 units
            c1 = User(
                phone="9833003300",
                full_name="Referred Customer One",
                referral_code="PBCUST01",
                referred_by_id=dist.id,
                programme=Programme.PLAN_B,
                role=UserRole.CUSTOMER,
                account_status=AccountStatus.ACTIVE,
                is_active=True,
            )
            db_session.add(c1)
            db_session.commit()

            c1_order = create_order(db_session, c1, prod, quantity=2, referral_code=dist.referral_code)
            FulfilmentOrchestrator.fulfil_order(c1_order.id, db=db_session)
            comm_res = PlanBCommissionService.process_order_commissions(c1_order.id, db=db_session)
            assert comm_res.status == "COMPLETED"

            # 5. Call overview endpoint again
            res_b_earned = client.get(
                "/api/v1/distributor/reports/dashboard-overview",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert res_b_earned.status_code == 200
            data_earned = res_b_earned.json()
            metrics = data_earned["summary_metrics"]

            # Verify all 9 metrics
            assert Decimal(str(metrics["available_wallet_balance"])) == Decimal("559.99")
            assert Decimal(str(metrics["lifetime_direct_earned"])) == Decimal("466.66")
            assert metrics["has_received_direct_bonus"] is True
            assert Decimal(str(metrics["generation_commission_earned"])) == Decimal("93.33")
            assert metrics["eligible_generation_billing_ids_count"] == 2
            assert Decimal(str(metrics["total_gross_commission"])) == Decimal("600.00")
            assert Decimal(str(metrics["total_operational_cost"])) == Decimal("28.01")
            assert Decimal(str(metrics["total_tds"])) == Decimal("12.00")
            assert Decimal(str(metrics["total_net_commission_earned"])) == Decimal("559.99")
            assert Decimal(str(metrics["total_withdrawn"])) == Decimal("0.00")

            # Verify Direct Commission list
            assert len(data_earned["direct_commissions"]) == 1
            d_item = data_earned["direct_commissions"][0]
            assert d_item["customer_name"] == "Referred Customer One"
            assert Decimal(str(d_item["gross_amount"])) == Decimal("500.00")
            assert Decimal(str(d_item["net_amount"])) == Decimal("466.66")

            # Verify Generation Commission list
            assert len(data_earned["generation_commissions"]) == 2
            g_items = data_earned["generation_commissions"]
            assert sorted([Decimal(str(g["net_amount"])) for g in g_items]) == [Decimal("46.66"), Decimal("46.67")]

    finally:
        app.dependency_overrides.pop(get_db, None)
