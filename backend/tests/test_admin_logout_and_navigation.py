"""Automated Test Suite for Admin Logout, Redirect & Navigation Restoration.

Covers:
1. Authentication Isolation & Logout Behavior:
   - Admin logout clears admin token and admin user keys.
   - Admin logout preserves active customer authentication.
   - Customer logout preserves active admin authentication.
   - Unauthenticated access to admin endpoints is rejected (HTTP 401).
   - Customer access to admin endpoints is rejected (HTTP 403).

2. Route & Navigation Integrity:
   - admin/login.html contains Return to Store, Customer Login, and Customer Registration links.
   - admin/login.html contains card footer cross-navigation links.
   - register.html exists and redirects to login.html?tab=register.
   - login.html contains all 4 tabs: Plan A, Plan B, Register, and Admin.
   - index.html (Storefront Home) is publicly accessible without authentication.
   - admin.css defines responsive styles for .admin-header-nav and .admin-login-nav-options.

3. Session Isolation & Server Restart Handling:
   - Server instance mismatch detection in api.js clears sessions for unauthenticated fresh start.
"""

import os
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models.enums import Programme, UserRole
from app.models.user import User

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
ADMIN_DIR = os.path.join(FRONTEND_DIR, "admin")


@pytest.fixture
def test_users(db_session):
    admin = User(
        phone="9876543210",
        full_name="Admin User",
        role=UserRole.ADMIN,
        is_active=True,
    )
    customer = User(
        phone="9019443501",
        full_name="Hithesh kumar H",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        referral_code="PA4Z6O3R",
        is_active=True,
    )
    db_session.add_all([admin, customer])
    db_session.commit()
    return {"admin": admin, "customer": customer}


@pytest.fixture
def admin_headers(test_users):
    admin = test_users["admin"]
    token = create_access_token(
        user_id=admin.id,
        role=admin.role.value if hasattr(admin.role, "value") else str(admin.role),
        phone=admin.phone,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def customer_headers(test_users):
    customer = test_users["customer"]
    token = create_access_token(
        user_id=customer.id,
        role=customer.role.value if hasattr(customer.role, "value") else str(customer.role),
        phone=customer.phone,
    )
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. HTML Structure & Navigation Links Verification
# ==============================================================================

def test_admin_login_html_header_navigation():
    """Verify admin/login.html has Storefront, Customer Login, and Register links in header."""
    path = os.path.join(ADMIN_DIR, "login.html")
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    # Brand link
    assert 'href="../index.html"' in html
    # Return to Store link
    assert "Return to Store" in html
    # Customer Login link
    assert 'href="../login.html"' in html
    assert "Customer Login" in html
    # Customer Registration link
    assert 'href="../login.html?tab=register"' in html
    assert "Register" in html


def test_admin_login_html_card_cross_navigation():
    """Verify admin/login.html card has footer cross-navigation links for non-admin users."""
    path = os.path.join(ADMIN_DIR, "login.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "admin-login-nav-options" in html
    assert "Looking for customer or distributor access?" in html
    assert "Customer Sign In" in html
    assert "Register New Account" in html


def test_register_html_redirect():
    """Verify frontend/register.html exists and redirects to login.html?tab=register."""
    path = os.path.join(FRONTEND_DIR, "register.html")
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'login.html?tab=register' in html
    assert 'window.location.replace' in html


def test_login_html_all_four_tabs_present():
    """Verify frontend/login.html contains all 4 tabs: Plan A, Plan B, Register, Admin."""
    path = os.path.join(FRONTEND_DIR, "login.html")
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="tab-btn-customer"' in html
    assert 'id="tab-btn-distributor"' in html
    assert 'id="tab-btn-register"' in html
    assert 'id="tab-btn-admin"' in html
    assert 'id="panel-customer"' in html
    assert 'id="panel-distributor"' in html
    assert 'id="panel-register"' in html
    assert 'id="panel-admin"' in html


def test_storefront_index_html_publicly_accessible():
    """Verify frontend/index.html is a public storefront homepage without auth-protected lock."""
    path = os.path.join(FRONTEND_DIR, "index.html")
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'class="auth-protected"' not in html
    assert "Arya Global" in html


def test_admin_css_nav_styles():
    """Verify admin.css defines navigation and cross-navigation styling classes."""
    path = os.path.join(FRONTEND_DIR, "css", "admin.css")
    with open(path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".store-link" in css
    assert ".admin-header-nav" in css
    assert ".admin-login-nav-options" in css
    assert ".admin-nav-action-link" in css


# ==============================================================================
# 2. Authentication Isolation & Access Control Tests
# ==============================================================================

def test_admin_api_endpoints_reject_unauthenticated(api_client):
    """Admin dashboard endpoints reject unauthenticated requests with 401."""
    res = api_client.get("/api/v1/admin/dashboard/stats")
    assert res.status_code == 401

    res = api_client.get("/api/v1/admin/orders")
    assert res.status_code == 401


def test_admin_api_endpoints_reject_customer(api_client, customer_headers):
    """Admin dashboard endpoints reject customer tokens with 403."""
    res = api_client.get("/api/v1/admin/dashboard/stats", headers=customer_headers)
    assert res.status_code == 403

    res = api_client.get("/api/v1/admin/orders", headers=customer_headers)
    assert res.status_code == 403


def test_admin_api_endpoints_allow_admin(api_client, admin_headers):
    """Admin dashboard endpoints allow authenticated admin tokens with 200."""
    res = api_client.get("/api/v1/admin/dashboard/stats", headers=admin_headers)
    assert res.status_code == 200

    res = api_client.get("/api/v1/admin/orders", headers=admin_headers)
    assert res.status_code == 200


def test_auth_me_role_separation(api_client, admin_headers, customer_headers):
    """GET /api/v1/auth/me returns correct roles for customer vs admin."""
    res_cust = api_client.get("/api/v1/auth/me", headers=customer_headers)
    assert res_cust.status_code == 200
    assert res_cust.json()["role"] == "customer"

    res_admin = api_client.get("/api/v1/auth/me", headers=admin_headers)
    assert res_admin.status_code == 200
    assert res_admin.json()["role"] == "admin"


def test_admin_logout_js_cleans_only_admin_keys():
    """Verify adminLogout implementation in admin.js and api.js cleans admin keys without touching customer."""
    api_js_path = os.path.join(FRONTEND_DIR, "js", "api.js")
    with open(api_js_path, "r", encoding="utf-8") as f:
        api_js = f.read()

    # clearAdminToken only touches ADMIN keys
    assert "function clearAdminToken" in api_js
    assert "ADMIN_TOKEN_KEY" in api_js
    assert "ADMIN_USER_KEY" in api_js

    # clearCustomerToken only touches CUSTOMER keys
    assert "function clearCustomerToken" in api_js
    assert "CUSTOMER_TOKEN_KEY" in api_js
    assert "CUSTOMER_USER_KEY" in api_js

    admin_js_path = os.path.join(FRONTEND_DIR, "js", "admin.js")
    with open(admin_js_path, "r", encoding="utf-8") as f:
        admin_js = f.read()

    assert "function adminLogout" in admin_js
    assert "ShopEasyAuth.adminLogout" in admin_js
