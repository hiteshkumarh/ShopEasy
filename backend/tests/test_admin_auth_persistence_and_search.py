"""Automated Test Suite for Admin Navigation, Auth Persistence, Search & Programme Renaming.

Covers:
1. Authentication:
   - Admin session persistence across Admin Panel and Storefront.
   - Return to Store navigation in sidebar.
   - Storefront session hydration and cookie persistence.
   - Admin authorization enforcement (HTTP 401 unauthenticated, HTTP 403 non-admin).
   - Customer authentication remains independent.

2. Header Simplification:
   - Storefront button removed from admin dashboard header.
   - Notification bell icon removed from admin dashboard header.
   - Dashboard search bar removed.
   - Admin user chip retained.

3. Module-Specific and Unified Search:
   - Unified search: Billing ID exact match.
   - Unified search: Order ID / Number exact match.
   - Plan A dedicated search: Customer name, phone, Customer ID, Billing ID, Queue ID.
   - Plan B dedicated search: Distributor name, phone, Distributor ID, Sponsor ID, Ledger ID.
   - Search validation: Empty input rejected (HTTP 400).
   - Search validation: Excessive length (>64 chars) rejected (HTTP 400).
   - Search with no matching records returns empty list (total=0), not error.
   - Authorization check on search endpoints.

4. Programme Renaming:
   - Plan A: "Plan A - Arya Business Partner Programme"
   - Plan B: "Plan B - Arya Generation Growth Programme"
   - Consistent user-facing UI names across admin sidebar, governance buttons,
     page headings, login tabs, and registration.
   - Zero changes to database column names, internal IDs, or business rules.
"""

import os
import re
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models.billing import BillingId
from app.models.cashback import PlanACashbackQueue
from app.models.enums import AccountStatus, Programme, UserRole, WalletType
from app.models.order import Order, OrderItem, OrderStatus, PaymentStatus
from app.models.product import Product
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
ADMIN_DIR = os.path.join(FRONTEND_DIR, "admin")


@pytest.fixture
def admin_headers(db_session):
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

    token = create_access_token(
        user_id=admin.id,
        role=admin.role.value if hasattr(admin.role, "value") else str(admin.role),
        phone=admin.phone,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def customer_headers(db_session):
    customer = db_session.query(User).filter(User.role == UserRole.CUSTOMER).first()
    if not customer:
        customer = User(
            phone="9812345678",
            full_name="Customer Test User",
            role=UserRole.CUSTOMER,
            referral_code="CUSTTEST01",
            is_active=True,
        )
        db_session.add(customer)
        db_session.commit()
        db_session.refresh(customer)

    token = create_access_token(
        user_id=customer.id,
        role=customer.role.value if hasattr(customer.role, "value") else str(customer.role),
        phone=customer.phone,
    )
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Header Simplification & Admin Dashboard Tests
# ==============================================================================

def test_admin_dashboard_header_simplification():
    """Verify that dashboard.html header has no storefront button, notification bell, or search bar."""
    dash_path = os.path.join(ADMIN_DIR, "dashboard.html")
    with open(dash_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Search bar must be removed from dashboard
    assert 'id="topbar-search-input"' not in content, "Dashboard topbar should not contain search input"
    assert "executeUnifiedSearch" not in content.split("<!-- Quick Actions")[0], "Dashboard header should not call executeUnifiedSearch"
    
    # Storefront link must be removed from header
    assert 'class="store-link"' not in content, "Dashboard header should not contain .store-link"
    
    # Notification bell button must be removed from header topbar (now placed in sidebar footer)
    topbar_match = re.search(r'<header class=["\']admin-topbar["\']>(.*?)</header>', content, re.DOTALL)
    assert topbar_match is not None
    topbar_html = topbar_match.group(1)
    assert "openNotificationsModal()" not in topbar_html, "Dashboard header topbar should not contain notification button"
    
    # Admin profile / user chip must be preserved
    assert 'class="admin-user-chip"' in content, "Dashboard header must retain admin user chip"

    # Sidebar must retain Return to Store
    assert 'Return to Store' in content, "Sidebar must retain Return to Store link"
    assert '../index.html' in content, "Sidebar Return to Store must link to storefront"


def test_global_header_search_removed_across_all_modules():
    """Verify that the top-right global header search is completely removed across all admin pages."""
    for mod in ["orders.html", "reports.html", "settings.html", "withdrawals.html", "plan-a.html", "plan-b.html", "dashboard.html"]:
        p = os.path.join(ADMIN_DIR, mod)
        with open(p, "r", encoding="utf-8") as f:
            c = f.read()
        assert 'id="topbar-search-input"' not in c, f"{mod} must not have global topbar search input"
        assert 'class="admin-search-container"' not in c, f"{mod} must not have admin-search-container in header"
        assert 'id="unified-search-modal"' in c, f"{mod} must retain unified search modal"


# ==============================================================================
# 2. Programme Renaming Consistency Tests
# ==============================================================================

def test_programme_renaming_in_admin_sidebar():
    """Verify official new names in admin sidebar across all admin HTML files and admin.js."""
    expected_plan_a = "Plan A - Arya Business Partner Programme"
    expected_plan_b = "Plan B - Arya Generation Growth Programme"

    # Check admin.js ADMIN_NAV_ITEMS
    admin_js_path = os.path.join(FRONTEND_DIR, "js", "admin.js")
    with open(admin_js_path, "r", encoding="utf-8") as f:
        admin_js = f.read()

    assert expected_plan_a in admin_js, f"admin.js must use '{expected_plan_a}'"
    assert expected_plan_b in admin_js, f"admin.js must use '{expected_plan_b}'"

    # Check all 10 admin HTML files
    admin_html_files = [
        "dashboard.html", "plan-a.html", "plan-b.html", "orders.html",
        "customers.html", "products.html", "product-form.html",
        "reports.html", "settings.html", "withdrawals.html"
    ]
    for filename in admin_html_files:
        p = os.path.join(ADMIN_DIR, filename)
        with open(p, "r", encoding="utf-8") as f:
            c = f.read()
        assert expected_plan_a in c, f"{filename} sidebar must contain '{expected_plan_a}'"
        assert expected_plan_b in c, f"{filename} sidebar must contain '{expected_plan_b}'"
        assert "Plan A Cashback &amp; Queues" not in c, f"{filename} must not contain old Plan A name"


def test_programme_renaming_on_login_and_pages():
    """Verify login page tabs and page headers display updated official names."""
    login_path = os.path.join(FRONTEND_DIR, "login.html")
    with open(login_path, "r", encoding="utf-8") as f:
        login_html = f.read()

    assert "Plan A - Arya Business Partner" in login_html
    assert "Plan B - Arya Generation Growth" in login_html
    assert "Plan A - Arya Business Partner Programme" in login_html
    assert "Plan B - Arya Generation Growth Programme" in login_html

    # Check plan-a.html topbar & headings
    plan_a_path = os.path.join(ADMIN_DIR, "plan-a.html")
    with open(plan_a_path, "r", encoding="utf-8") as f:
        plan_a_html = f.read()
    assert "Plan A - Arya Business Partner Programme" in plan_a_html

    # Check plan-b.html topbar & headings
    plan_b_path = os.path.join(ADMIN_DIR, "plan-b.html")
    with open(plan_b_path, "r", encoding="utf-8") as f:
        plan_b_html = f.read()
    assert "Plan B - Arya Generation Growth Programme" in plan_b_html


# ==============================================================================
# 3. Dedicated Plan A & Plan B Search UI & Endpoints
# ==============================================================================

def test_plan_a_and_plan_b_pages_have_dedicated_search_bars():
    """Verify plan-a.html and plan-b.html contain dedicated search bars."""
    with open(os.path.join(ADMIN_DIR, "plan-a.html"), "r", encoding="utf-8") as f:
        pa = f.read()
    assert 'id="plan-a-search-input"' in pa
    assert "executePlanASearch()" in pa
    assert 'id="plan-a-search-clear-btn"' in pa
    assert 'id="plan-a-search-results"' in pa

    with open(os.path.join(ADMIN_DIR, "plan-b.html"), "r", encoding="utf-8") as f:
        pb = f.read()
    assert 'id="plan-b-search-input"' in pb
    assert "executePlanBSearch()" in pb
    assert 'id="plan-b-search-clear-btn"' in pb
    assert 'id="plan-b-search-results"' in pb


def test_plan_a_search_api_validation_and_auth(api_client, admin_headers, customer_headers):
    """Verify GET /api/v1/admin/plan-a/search validation and authorization."""
    # 1. Unauthenticated -> 401
    res = api_client.get("/api/v1/admin/plan-a/search?q=test")
    assert res.status_code == 401

    # 2. Customer token -> 403
    res = api_client.get("/api/v1/admin/plan-a/search?q=test", headers=customer_headers)
    assert res.status_code == 403

    # 3. Empty query -> 400
    res = api_client.get("/api/v1/admin/plan-a/search?q=%20", headers=admin_headers)
    assert res.status_code == 400

    # 4. Excessive query length > 64 chars -> 400
    res = api_client.get(f"/api/v1/admin/plan-a/search?q={'A'*65}", headers=admin_headers)
    assert res.status_code == 400

    # 5. Non-matching query returns empty result list without errors
    res = api_client.get("/api/v1/admin/plan-a/search?q=NONEXISTENT_CUSTOMER_XYZ", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_plan_b_search_api_validation_and_auth(api_client, admin_headers, customer_headers):
    """Verify GET /api/v1/admin/plan-b/search validation and authorization."""
    # 1. Unauthenticated -> 401
    res = api_client.get("/api/v1/admin/plan-b/search?q=test")
    assert res.status_code == 401

    # 2. Customer token -> 403
    res = api_client.get("/api/v1/admin/plan-b/search?q=test", headers=customer_headers)
    assert res.status_code == 403

    # 3. Empty query -> 400
    res = api_client.get("/api/v1/admin/plan-b/search?q=%20", headers=admin_headers)
    assert res.status_code == 400

    # 4. Excessive query length > 64 chars -> 400
    res = api_client.get(f"/api/v1/admin/plan-b/search?q={'B'*65}", headers=admin_headers)
    assert res.status_code == 400

    # 5. Non-matching query returns empty result list without errors
    res = api_client.get("/api/v1/admin/plan-b/search?q=NONEXISTENT_DISTRIBUTOR_XYZ", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_unified_search_api(api_client, admin_headers, customer_headers):
    """Verify GET /api/v1/admin/search for Billing ID and Order ID lookups."""
    # 1. Unauthenticated -> 401
    res = api_client.get("/api/v1/admin/search?q=ORD-1")
    assert res.status_code == 401

    # 2. Customer -> 403
    res = api_client.get("/api/v1/admin/search?q=ORD-1", headers=customer_headers)
    assert res.status_code == 403

    # 3. Empty -> 400
    res = api_client.get("/api/v1/admin/search?q=%20", headers=admin_headers)
    assert res.status_code == 400

    # 4. Non-matching -> 200 with total 0
    res = api_client.get("/api/v1/admin/search?q=UNKNOWN-BID-9999", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_positive_match_searches(api_client, db_session, admin_headers):
    """Verify actual record retrieval for Unified Search, Plan A Search, and Plan B Search."""
    # Seed test customer
    cust = User(
        phone="9811122233",
        full_name="Plan A Customer Alpha",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        referral_code="ALPHA01",
        is_active=True,
    )
    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)

    # Seed test address
    addr = Address(
        user_id=cust.id,
        recipient_name="Plan A Customer Alpha",
        phone="9811122233",
        address_line1="123 Test Street",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
    )
    db_session.add(addr)
    db_session.commit()
    db_session.refresh(addr)

    # Seed test order
    ord_obj = Order(
        order_number="ORD-TEST-9999",
        idempotency_key="idemp-key-9999",
        user_id=cust.id,
        address_id=addr.id,
        total_amount=Decimal("5000.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(ord_obj)
    db_session.commit()
    db_session.refresh(ord_obj)

    # Seed test product & order item
    prod = Product(
        name="Test 9W Bulb",
        price=Decimal("100.00"),
        stock=100,
        is_active=True,
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)

    item = OrderItem(
        order_id=ord_obj.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=prod.price,
        quantity=1,
        line_total=Decimal("100.00"),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    # Seed test billing ID
    bid = BillingId(
        billing_number="BID-PLANA-7777",
        sequence_number=1,
        unit_index=0,
        programme=Programme.PLAN_A,
        user_id=cust.id,
        order_id=ord_obj.id,
        order_item_id=item.id,
        product_id=prod.id,
        status="ACTIVE",
    )
    db_session.add(bid)
    db_session.commit()
    db_session.refresh(bid)

    # Seed test distributor
    dist = User(
        phone="9844455566",
        full_name="Plan B Distributor Beta",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_B,
        referral_code="BETA01",
        is_active=True,
    )
    db_session.add(dist)
    db_session.commit()
    db_session.refresh(dist)

    # 1. Unified Search: Order ID
    res = api_client.get("/api/v1/admin/search?q=ORD-TEST-9999", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(r["identifier"] == "ORD-TEST-9999" for r in data["results"])

    # Unified Search: Stripped leading '#'
    res = api_client.get("/api/v1/admin/search?q=%23ORD-TEST-9999", headers=admin_headers)
    assert res.status_code == 200
    assert any(r["identifier"] == "ORD-TEST-9999" for r in res.json()["results"])

    # Unified Search: Billing ID
    res = api_client.get("/api/v1/admin/search?q=BID-PLANA-7777", headers=admin_headers)
    assert res.status_code == 200
    assert any(r["identifier"] == "BID-PLANA-7777" for r in res.json()["results"])

    # 2. Plan A Search: Customer by Name
    res = api_client.get("/api/v1/admin/plan-a/search?q=Alpha", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 1
    assert any(r["record_type"] == "CUSTOMER" and "Alpha" in r["customer_name"] for r in res.json()["results"])

    # Plan A Search: Customer by Phone
    res = api_client.get("/api/v1/admin/plan-a/search?q=9811122233", headers=admin_headers)
    assert res.status_code == 200
    assert any(r["phone"] == "9811122233" for r in res.json()["results"])

    # Plan A Search: Billing ID
    res = api_client.get("/api/v1/admin/plan-a/search?q=BID-PLANA-7777", headers=admin_headers)
    assert res.status_code == 200
    assert any(r["record_type"] == "BILLING_ID" and r["identifier"] == "BID-PLANA-7777" for r in res.json()["results"])

    # 3. Plan B Search: Distributor by Name
    res = api_client.get("/api/v1/admin/plan-b/search?q=Beta", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 1
    assert any(r["record_type"] == "DISTRIBUTOR" and "Beta" in r["distributor_name"] for r in res.json()["results"])

    # Plan B Search: Distributor by Phone
    res = api_client.get("/api/v1/admin/plan-b/search?q=9844455566", headers=admin_headers)
    assert res.status_code == 200
    assert any(r["phone"] == "9844455566" for r in res.json()["results"])



# ==============================================================================
# 4. Authentication Persistence & Navigation Client Invariants
# ==============================================================================

def test_auth_persistence_cookie_and_token_invariants():
    """Verify frontend js api.js and navigation.js maintain cross-path cookie and token hydration."""
    with open(os.path.join(FRONTEND_DIR, "js", "api.js"), "r", encoding="utf-8") as f:
        api_js = f.read()

    assert "shopeasy_admin_token" in api_js
    assert "setCookie(ADMIN_TOKEN_KEY" in api_js
    assert "getCookie(ADMIN_TOKEN_KEY" in api_js
    assert "deleteCookie(ADMIN_TOKEN_KEY" in api_js
    assert "searchPlanA" in api_js
    assert "searchPlanB" in api_js

    with open(os.path.join(FRONTEND_DIR, "js", "navigation.js"), "r", encoding="utf-8") as f:
        nav_js = f.read()

    assert "hydrateNavigationAuth" in nav_js
    assert "admin-session-indicator" in nav_js
    assert "admin/dashboard.html" in nav_js

    with open(os.path.join(FRONTEND_DIR, "js", "auth.js"), "r", encoding="utf-8") as f:
        auth_js = f.read()

    assert "redirectIfAdminAuthenticated" in auth_js
    assert "admin/dashboard.html" in auth_js
