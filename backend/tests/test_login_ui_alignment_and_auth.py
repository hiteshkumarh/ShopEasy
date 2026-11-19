"""
test_login_ui_alignment_and_auth.py
Verification suite for ShopEasy / Arya Global Digital login page UI alignment fix.

Tests:
1. All 4 navigation options (Plan A, Plan B, Register, Admin) are inside the unified .auth-tabs container.
2. Tab structure, headings, subheadings, and data-tab attributes match requirements.
3. Corresponding 4 tab panels (#panel-customer, #panel-distributor, #panel-register, #panel-admin) exist.
4. Form controls alignment: mobile number input and password input have consistent dimensions and classes.
5. CSS rules enforce equal flex distribution, active selected state, and responsive mobile scroll.
6. Authentication endpoints and role isolation invariants remain intact.
"""

import os
import re
import pytest
from html.parser import HTMLParser
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.security import create_access_token
from app.models.enums import UserRole
from app.models.user import User

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
LOGIN_HTML_PATH = os.path.join(FRONTEND_DIR, "login.html")
AUTH_CSS_PATH = os.path.join(FRONTEND_DIR, "css", "auth.css")
AUTH_JS_PATH = os.path.join(FRONTEND_DIR, "js", "auth.js")


# ==============================================================================
# 1. HTML Unified Segmented Container Structure Tests
# ==============================================================================

def test_login_html_unified_tabs_container():
    """Verify all 4 tabs appear inside one unified #auth-tabs container."""
    with open(LOGIN_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Find the #auth-tabs container block
    tabs_match = re.search(r'<div\s+class="auth-tabs"[^>]*id="auth-tabs"[^>]*>(.*?)</div>', html, re.DOTALL)
    assert tabs_match is not None, "Unified .auth-tabs container missing from login.html"

    tabs_inner = tabs_match.group(1)

    # Find all buttons inside the container
    buttons = re.findall(r'<button\s+([^>]+)>(.*?)</button>', tabs_inner, re.DOTALL)
    assert len(buttons) == 4, f"Expected 4 tabs inside .auth-tabs, found {len(buttons)}"

    # Verify tab IDs and data-tab values
    expected = [
        ("tab-btn-customer", "customer"),
        ("tab-btn-distributor", "distributor"),
        ("tab-btn-register", "register"),
        ("tab-btn-admin", "admin"),
    ]
    for btn_attrs, _ in buttons:
        id_m = re.search(r'id="([^"]+)"', btn_attrs)
        tab_m = re.search(r'data-tab="([^"]+)"', btn_attrs)
        assert id_m is not None and tab_m is not None
        assert (id_m.group(1), tab_m.group(1)) in expected

    # Verify no .auth-tab button exists outside the container
    all_tab_buttons = re.findall(r'<button[^>]+class="[^"]*auth-tab[^"]*"', html)
    assert len(all_tab_buttons) == 4, "Found .auth-tab buttons outside .auth-tabs container"


def test_login_html_tab_labels_and_official_names():
    """Verify full programme names and options are present inside the unified tabs."""
    with open(LOGIN_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    tabs_match = re.search(r'<div\s+class="auth-tabs"[^>]*id="auth-tabs"[^>]*>(.*?)</div>', html, re.DOTALL)
    assert tabs_match is not None
    tabs_inner = tabs_match.group(1)

    # Tab 1: Plan A - Arya Business Partner
    assert 'id="tab-btn-customer"' in tabs_inner
    assert "Plan A" in tabs_inner
    assert "Arya Business Partner" in tabs_inner
    assert 'title="Plan A - Arya Business Partner"' in tabs_inner

    # Tab 2: Plan B - Arya Generation Growth
    assert 'id="tab-btn-distributor"' in tabs_inner
    assert "Plan B" in tabs_inner
    assert "Arya Generation Growth" in tabs_inner
    assert 'title="Plan B - Arya Generation Growth"' in tabs_inner

    # Tab 3: Register
    assert 'id="tab-btn-register"' in tabs_inner
    assert "Register" in tabs_inner

    # Tab 4: Admin
    assert 'id="tab-btn-admin"' in tabs_inner
    assert "Admin" in tabs_inner

    # Verify string assertions required by earlier tests remain preserved
    assert "Plan A - Arya Business Partner" in html
    assert "Plan B - Arya Generation Growth" in html
    assert "Plan A - Arya Business Partner Programme" in html
    assert "Plan B - Arya Generation Growth Programme" in html


def test_login_html_four_matching_panels():
    """Verify all 4 matching tabpanels exist with their expected forms and IDs."""
    with open(LOGIN_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    expected_panels = [
        ("panel-customer", "customer-login-form"),
        ("panel-distributor", "distributor-login-form"),
        ("panel-register", "register-form"),
        ("panel-admin", "admin-login-form"),
    ]

    for panel_id, form_id in expected_panels:
        assert f'id="{panel_id}"' in html, f"Panel #{panel_id} missing"
        assert f'id="{form_id}"' in html, f"Form #{form_id} missing"


def test_login_html_card_centering_and_elements_alignment():
    """Verify device icon, full-width buttons, and input groups exist and align."""
    with open(LOGIN_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Center device icon
    assert 'class="auth-icon-wrap"' in html

    # Full width submit buttons on forms
    btn_ids = ["customer-login-btn", "distributor-login-btn", "register-btn", "admin-login-btn"]
    for bid in btn_ids:
        btn_match = re.search(rf'<button[^>]+id="{bid}"[^>]*>', html)
        assert btn_match is not None, f"Submit button #{bid} missing"
        assert "btn-block" in btn_match.group(0), f"Button #{bid} must have .btn-block"

    # Password toggle buttons
    toggle_btns = re.findall(r'<button[^>]+class="[^"]*password-toggle-btn[^"]*"[^>]*>', html)
    assert len(toggle_btns) >= 4, f"Expected at least 4 password toggles, found {len(toggle_btns)}"
    for tb in toggle_btns:
        assert 'data-target="' in tb, "Password toggle lacks data-target"


# ==============================================================================
# 2. CSS Styling & Layout Invariant Tests
# ==============================================================================

def test_auth_css_unified_tabs_and_controls():
    """Verify auth.css rules enforce unified segmented container and control alignment."""
    with open(AUTH_CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()

    # Container styling
    assert ".auth-tabs" in css
    assert "overflow-x: auto" in css
    assert "background-color" in css

    # Tab equal distribution & active styling
    assert ".auth-tab" in css
    assert ".auth-tab.active" in css
    assert ".auth-tab-heading" in css
    assert ".auth-tab-sub" in css

    # Input groups identical height & borders
    assert ".phone-input-group" in css
    assert "48px" in css  # Standard unified height for phone and password
    assert ".password-input-wrap" in css
    assert ".password-toggle-btn" in css

    # Mobile responsive media query
    assert "@media (max-width: 540px)" in css or "@media (max-width: 520px)" in css


def test_auth_js_tab_switching_supports_all_four_tabs():
    """Verify auth.js switchTab correctly handles all 4 tabs."""
    with open(AUTH_JS_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    # Check switchTab supports all 4 tabs
    for tab in ["customer", "distributor", "register", "admin"]:
        assert f"'{tab}'" in js or f'"{tab}"' in js, f"Tab '{tab}' not handled in switchTab"

    assert "aria-selected" in js
    assert "classList.toggle('active'" in js or "classList.add('active')" in js


# ==============================================================================
# 3. Authentication & API Non-Regression Tests
# ==============================================================================

def test_customer_login_api_non_regression(api_client: TestClient):
    """Verify /api/v1/auth/customer/login rejects invalid phone and invalid formats gracefully."""
    # Test invalid short phone
    res = api_client.post(
        "/api/v1/auth/customer/login",
        json={"phone": "123", "password": "anypassword"},
    )
    assert res.status_code in [400, 401, 422]

    # Test non-existent user
    res2 = api_client.post(
        "/api/v1/auth/customer/login",
        json={"phone": "9999999999", "password": "WrongPassword123!"},
    )
    assert res2.status_code in [400, 401, 404]


def test_admin_login_api_non_regression(api_client: TestClient):
    """Verify /api/v1/auth/admin/login rejects invalid credentials and preserves auth."""
    # Test invalid credentials
    res = api_client.post(
        "/api/v1/auth/admin/login",
        json={"phone": "9999999999", "password": "WrongAdminPassword!"},
    )
    assert res.status_code in [400, 401, 404]


def test_admin_customer_role_isolation(api_client: TestClient):
    """Verify customer tokens are strictly forbidden from admin API endpoints."""
    customer_token = create_access_token(user_id=9999, role="CUSTOMER", phone="9876543210")
    headers = {"Authorization": f"Bearer {customer_token}"}

    # Attempt to access admin dashboard stats
    res = api_client.get("/api/v1/admin/dashboard/stats", headers=headers)
    assert res.status_code in [401, 403], f"Expected 401/403 for customer on admin route, got {res.status_code}"

    # Attempt to access admin financial settings
    res_settings = api_client.get("/api/v1/admin/financial-settings", headers=headers)
    assert res_settings.status_code in [401, 403]
