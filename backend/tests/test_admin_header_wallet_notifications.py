"""
Test suite for ShopEasy Admin UI Corrections (Prompt 11):
1. Top-Right Global Search Bar Removal across all admin pages.
2. Notification Button in Sidebar Footer immediately above Return to Store.
3. Wallet Freeze/Unfreeze input converted from Wallet ID to User Number.
4. Backend user-number-to-wallet resolution, freeze/unfreeze, audit history, multi-wallet handling, auth guards.
"""

from decimal import Decimal
import os
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db, require_admin
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models.enums import AccountStatus, Programme, UserRole, WalletType
from app.models.user import User
from app.models.wallet import Wallet, WalletFreezeHistory

ADMIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "admin"))
JS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "js"))

ADMIN_PAGES = [
    "dashboard.html",
    "plan-a.html",
    "plan-b.html",
    "withdrawals.html",
    "reports.html",
    "settings.html",
    "orders.html",
    "products.html",
    "product-form.html",
    "customers.html",
]


# ==============================================================================
# 1. Frontend Topbar Header Search Bar Removal Tests
# ==============================================================================

def test_global_header_search_bar_removed_across_all_pages():
    """Verify global search input, icon, and container are completely removed from topbar across all admin pages."""
    for filename in ADMIN_PAGES:
        filepath = os.path.join(ADMIN_DIR, filename)
        assert os.path.exists(filepath), f"{filename} does not exist"
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        topbar_match = re.search(r'<header class=["\']admin-topbar["\']>(.*?)</header>', content, re.DOTALL)
        assert topbar_match is not None, f"{filename} must contain <header class='admin-topbar'>"
        topbar_html = topbar_match.group(1)

        # Global search input and container must NOT exist in topbar
        assert "admin-search-container" not in topbar_html, f"{filename} topbar must not have .admin-search-container"
        assert "topbar-search-input" not in topbar_html, f"{filename} topbar must not have #topbar-search-input"
        assert "Search Billing ID or Order" not in topbar_html, f"{filename} topbar must not have global search placeholder"

        # Admin user chip must remain in topbar
        assert "admin-user-chip" in topbar_html, f"{filename} topbar must retain .admin-user-chip"


def test_dedicated_module_search_bars_preserved():
    """Verify dedicated search bars inside individual modules (Plan A, Plan B, Products, Orders) are preserved."""
    # 1. Plan A dedicated search bar
    with open(os.path.join(ADMIN_DIR, "plan-a.html"), "r", encoding="utf-8") as f:
        plan_a_content = f.read()
    assert 'id="plan-a-search-input"' in plan_a_content
    assert "executePlanASearch" in plan_a_content
    assert "admin-search-bar-section" in plan_a_content

    # 2. Plan B dedicated search bar
    with open(os.path.join(ADMIN_DIR, "plan-b.html"), "r", encoding="utf-8") as f:
        plan_b_content = f.read()
    assert 'id="plan-b-search-input"' in plan_b_content
    assert "executePlanBSearch" in plan_b_content
    assert "admin-search-bar-section" in plan_b_content

    # 3. Products catalog search toolbar
    with open(os.path.join(ADMIN_DIR, "products.html"), "r", encoding="utf-8") as f:
        prod_content = f.read()
    assert 'id="admin-product-search"' in prod_content
    assert "admin-search-wrap" in prod_content

    # 4. Orders fulfillment search
    with open(os.path.join(ADMIN_DIR, "orders.html"), "r", encoding="utf-8") as f:
        orders_content = f.read()
    assert 'id="admin-orders-search-input"' in orders_content
    assert "executeUnifiedSearch" in orders_content


# ==============================================================================
# 2. Notification Button in Sidebar Footer Tests
# ==============================================================================

def test_notification_button_in_sidebar_footer_across_all_pages():
    """Verify Notification button has been removed from sidebar footer across all admin pages and admin.js."""
    for filename in ADMIN_PAGES:
        filepath = os.path.join(ADMIN_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Notification button and count badge must be absent from sidebar
        assert 'id="admin-sidebar-notif-btn"' not in content, f"{filename} should not have #admin-sidebar-notif-btn"
        assert 'id="admin-notif-count"' not in content, f"{filename} should not have #admin-notif-count badge container"

        # Sidebar footer must retain Return to Store and Logout in order
        store_idx = content.find("Return to Store")
        logout_idx = content.find("Logout")

        assert store_idx != -1 and logout_idx != -1, f"{filename} missing footer items (Return to Store / Logout)"
        assert store_idx < logout_idx, f"{filename} sidebar footer order must be: 1. Return to Store, 2. Logout"

    # Also verify shared JavaScript sidebar template in admin.js
    with open(os.path.join(JS_DIR, "admin.js"), "r", encoding="utf-8") as f:
        admin_js = f.read()

    sidebar_func = admin_js.split("renderSharedAdminSidebar")[1].split("function initAdminShell")[0]
    assert 'id="admin-sidebar-notif-btn"' not in sidebar_func
    assert 'id="admin-notif-count"' not in sidebar_func


def test_notification_modal_dynamic_creation_and_api():
    """Verify openNotificationsModal dynamically creates modal if absent and checks unread counts."""
    with open(os.path.join(JS_DIR, "admin.js"), "r", encoding="utf-8") as f:
        admin_js = f.read()

    assert "admin-notifications-modal" in admin_js
    assert "markAllAdminNotificationsRead" in admin_js
    assert "ShopEasyAdmin.getNotifications" in admin_js

    with open(os.path.join(JS_DIR, "api.js"), "r", encoding="utf-8") as f:
        api_js = f.read()
    assert "getNotifications" in api_js
    assert "/notifications" in api_js


# ==============================================================================
# 3. Wallet Freeze Input by User Number Frontend Verification
# ==============================================================================

def test_wallet_freeze_ui_uses_user_number():
    """Verify withdrawals.html uses User Number input instead of manual Wallet ID input."""
    with open(os.path.join(ADMIN_DIR, "withdrawals.html"), "r", encoding="utf-8") as f:
        content = f.read()

    # User Number input present
    assert 'id="freeze-user-number"' in content

    # Mandatory reason and action buttons
    assert 'id="freeze-reason"' in content
    assert 'placeholder="Mandatory Reason for action..."' in content
    assert 'onclick="executeWalletFreezeAction(true)"' in content
    assert 'onclick="executeWalletFreezeAction(false)"' in content
    assert 'onclick="loadWalletFreezeHistory()"' in content

    # User and multi-wallet selection container
    assert 'id="wallet-user-info-box"' in content
    assert 'id="wallet-multi-selector"' in content


# ==============================================================================
# 4. Backend Database Fixtures & API Integration Tests
# ==============================================================================

@pytest.fixture(scope="module")
def wallet_test_env():
    """Set up an in-memory SQLite database for user-number-to-wallet tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestingSession()
    # Create test admin
    admin = User(
        full_name="System Admin",
        phone="9800000000",
        role=UserRole.ADMIN,
        programme=Programme.LEGACY,
        account_status=AccountStatus.ACTIVE,
        password_hash="hashed_admin_pass",
    )
    db.add(admin)

    # Create Plan A customer with 1 wallet
    cust_a = User(
        full_name="Ramesh Kumar",
        phone="9811122233",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="CUSTA001",
        password_hash="hashed_cust_pass",
    )
    db.add(cust_a)
    db.flush()

    wallet_a = Wallet(
        user_id=cust_a.id,
        wallet_type=WalletType.DIRECT_REFERRAL,
        balance=Decimal("1500.00"),
        total_withdrawn=Decimal("0.00"),
        is_frozen=False,
    )
    db.add(wallet_a)

    # Create Plan B distributor with 2 wallets
    dist_b = User(
        full_name="Priya Sharma",
        phone="9822233344",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_B,
        account_status=AccountStatus.ACTIVE,
        referral_code="DISTB001",
        password_hash="hashed_dist_pass",
    )
    db.add(dist_b)
    db.flush()

    wallet_b1 = Wallet(
        user_id=dist_b.id,
        wallet_type=WalletType.DIRECT_REFERRAL,
        balance=Decimal("2500.00"),
        total_withdrawn=Decimal("0.00"),
        is_frozen=False,
    )
    wallet_b2 = Wallet(
        user_id=dist_b.id,
        wallet_type=WalletType.SEQUENTIAL_COMMISSION,
        balance=Decimal("800.00"),
        total_withdrawn=Decimal("0.00"),
        is_frozen=False,
    )
    db.add_all([wallet_b1, wallet_b2])

    # Create user with NO wallets
    user_no_wallet = User(
        full_name="Sunil Verma",
        phone="9833344455",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="CUSTNOWALLET",
        password_hash="hashed_pass",
    )
    db.add(user_no_wallet)
    db.commit()

    admin_token = create_access_token(user_id=admin.id, role="admin", phone=admin.phone)

    client = TestClient(app)

    yield {
        "client": client,
        "admin_token": admin_token,
        "admin_id": admin.id,
        "cust_a": cust_a,
        "wallet_a": wallet_a,
        "dist_b": dist_b,
        "wallet_b1": wallet_b1,
        "wallet_b2": wallet_b2,
        "user_no_wallet": user_no_wallet,
        "db": db,
    }

    app.dependency_overrides.clear()
    db.close()


def test_api_wallet_lookup_by_user_number(wallet_test_env):
    """Verify GET /api/v1/admin/wallets/lookup-by-user-number endpoint."""
    client = wallet_test_env["client"]
    token = wallet_test_env["admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Lookup single-wallet customer
    resp = client.get("/api/v1/admin/wallets/lookup-by-user-number?user_number=9811122233", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["full_name"] == "Ramesh Kumar"
    assert data["phone"] == "9811122233"
    assert len(data["wallets"]) == 1
    assert data["wallets"][0]["wallet_type"] == "direct_referral"
    assert data["wallets"][0]["is_frozen"] is False

    # 2. Lookup with clean digits (+91 9811122233)
    resp_formatted = client.get("/api/v1/admin/wallets/lookup-by-user-number?user_number=+919811122233", headers=headers)
    assert resp_formatted.status_code == 200
    assert resp_formatted.json()["phone"] == "9811122233"

    # 3. Lookup user with no wallets
    resp_no_wallet = client.get("/api/v1/admin/wallets/lookup-by-user-number?user_number=9833344455", headers=headers)
    assert resp_no_wallet.status_code == 200
    assert len(resp_no_wallet.json()["wallets"]) == 0

    # 4. Lookup non-existent user -> 404
    resp_404 = client.get("/api/v1/admin/wallets/lookup-by-user-number?user_number=9999999999", headers=headers)
    assert resp_404.status_code == 404
    assert "User with mobile number '9999999999' not found." in resp_404.json()["detail"]


def test_api_wallet_freeze_and_unfreeze_by_user_number(wallet_test_env):
    """Verify freezing and unfreezing customer wallet by registered mobile number."""
    client = wallet_test_env["client"]
    token = wallet_test_env["admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Mandatory reason validation
    resp_bad = client.post(
        "/api/v1/admin/wallets/freeze-by-user-number",
        json={"user_number": "9811122233", "reason": ""},
        headers=headers,
    )
    assert resp_bad.status_code in [400, 422]

    # 2. Freeze single wallet successfully
    resp_freeze = client.post(
        "/api/v1/admin/wallets/freeze-by-user-number",
        json={"user_number": "9811122233", "reason": "Suspicious referral activity"},
        headers=headers,
    )
    assert resp_freeze.status_code == 200, resp_freeze.text
    data = resp_freeze.json()
    assert data["status"] == "success"
    assert data["is_frozen"] is True
    assert "Ramesh Kumar" in data["message"]

    # 3. Unfreeze wallet successfully
    resp_unfreeze = client.post(
        "/api/v1/admin/wallets/unfreeze-by-user-number",
        json={"user_number": "9811122233", "reason": "Identity cleared"},
        headers=headers,
    )
    assert resp_unfreeze.status_code == 200, resp_unfreeze.text
    data_unfreeze = resp_unfreeze.json()
    assert data_unfreeze["status"] == "success"
    assert data_unfreeze["is_frozen"] is False

    # 4. View History by user number
    resp_hist = client.get(
        "/api/v1/admin/wallets/freeze-history-by-user-number?user_number=9811122233",
        headers=headers,
    )
    assert resp_hist.status_code == 200
    history = resp_hist.json()
    assert len(history) == 2
    assert history[0]["action"] == "UNFREEZE"
    assert history[0]["reason"] == "Identity cleared"
    assert history[1]["action"] == "FREEZE"
    assert history[1]["reason"] == "Suspicious referral activity"


def test_api_wallet_freeze_user_without_wallets(wallet_test_env):
    """Verify freezing a user who has no associated wallets returns clean error."""
    client = wallet_test_env["client"]
    token = wallet_test_env["admin_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/api/v1/admin/wallets/freeze-by-user-number",
        json={"user_number": "9833344455", "reason": "Test freeze"},
        headers=headers,
    )
    assert resp.status_code == 404
    assert "No associated wallets found" in resp.json()["detail"]


def test_api_wallet_freeze_multiple_wallets_handling(wallet_test_env):
    """Verify safe handling of users with multiple wallets (selection required)."""
    client = wallet_test_env["client"]
    token = wallet_test_env["admin_token"]
    headers = {"Authorization": f"Bearer {token}"}
    dist_phone = "9822233344"

    # 1. Without specifying wallet_id -> 409 Conflict
    resp_conflict = client.post(
        "/api/v1/admin/wallets/freeze-by-user-number",
        json={"user_number": dist_phone, "reason": "Audit review"},
        headers=headers,
    )
    assert resp_conflict.status_code == 409
    assert "Multiple wallets found" in resp_conflict.json()["detail"]

    # 2. Specifying target wallet_id (e.g. wallet_b1)
    target_wallet_id = wallet_test_env["wallet_b1"].id
    resp_success = client.post(
        "/api/v1/admin/wallets/freeze-by-user-number",
        json={"user_number": dist_phone, "wallet_id": target_wallet_id, "reason": "Specific wallet audit"},
        headers=headers,
    )
    assert resp_success.status_code == 200
    assert resp_success.json()["wallet_id"] == target_wallet_id
    assert resp_success.json()["is_frozen"] is True

    # Confirm other wallet (wallet_b2) is NOT frozen
    other_wallet = wallet_test_env["wallet_b2"]
    wallet_test_env["db"].refresh(other_wallet)
    assert other_wallet.is_frozen is False

    # 3. Unfreeze specific wallet
    resp_unfreeze = client.post(
        "/api/v1/admin/wallets/unfreeze-by-user-number",
        json={"user_number": dist_phone, "wallet_id": target_wallet_id, "reason": "Audit passed"},
        headers=headers,
    )
    assert resp_unfreeze.status_code == 200
    assert resp_unfreeze.json()["is_frozen"] is False


def test_auth_guard_on_new_endpoints(wallet_test_env):
    """Verify that unauthenticated requests to the new admin endpoints are rejected."""
    client = wallet_test_env["client"]

    # No auth header -> 401
    assert client.get("/api/v1/admin/wallets/lookup-by-user-number?user_number=9811122233").status_code == 401
    assert client.post("/api/v1/admin/wallets/freeze-by-user-number", json={"user_number": "9811122233", "reason": "test"}).status_code == 401
    assert client.post("/api/v1/admin/wallets/unfreeze-by-user-number", json={"user_number": "9811122233"}).status_code == 401
    assert client.get("/api/v1/admin/wallets/freeze-history-by-user-number?user_number=9811122233").status_code == 401
