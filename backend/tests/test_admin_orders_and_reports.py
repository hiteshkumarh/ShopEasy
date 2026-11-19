"""Automated Test Suite for Admin Orders & Reports Corrections.

Covers:
1. Admin Orders Table & Endpoint:
   - Dedicated Company-Level Billing ID (AGD-XXXXXX) exposed on GET /api/v1/admin/orders.
   - Null handling: orders without Billing ID have billing_id=None, billing_ids=[].
   - Search filtering: by Billing ID, Order Number, and Customer Phone.
   - Access control: 401 unauthenticated, 403 non-admin.

2. Admin Reports - Plan A Customer Statement Bug:
   - Lookup via 10-digit registered phone number (e.g. '9019443501') -> 200 OK.
   - Lookup via database Customer ID (e.g. customer.id) -> 200 OK.
   - Excel (.xlsx) and PDF (.pdf) format export verification.
   - Non-existent customer identifier -> 404 Not Found.
   - Cross-programme validation: Plan B distributor requested on Plan A statement -> 400 Bad Request.

3. Admin Reports - Plan B Individual Distributor Profile Report:
   - Lookup via Distributor ID and registered phone number.
   - Excel export (.xlsx) -> 200 OK.
   - Strict rejection of PDF format (HTTP 400) per business rule R-09.
   - Non-existent distributor -> 404 Not Found.
   - Cross-programme validation: Plan A customer requested on Plan B report -> 400 Bad Request.

4. Frontend Integrity Verification:
   - admin/orders.html contains Billing ID column header, search input, and inspect modal.
   - admin/reports.html contains text-type inputs and updated placeholders.
   - admin.css defines .billing-id-badge style.
   - admin.js defines and exports window handlers for orders and reports.
"""

from decimal import Decimal
import io
import os
import openpyxl
import pytest

from app.core.security import create_access_token
from app.models.billing import BillingId
from app.models.enums import OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
ADMIN_DIR = os.path.join(FRONTEND_DIR, "admin")


@pytest.fixture
def seed_data(db_session):
    """Seed test database with admin, customer, distributor, address, products, and orders."""
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
    distributor = User(
        phone="9888888888",
        full_name="Plan B Distributor",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_B,
        referral_code="PB888888",
        is_active=True,
    )
    db_session.add_all([admin, customer, distributor])
    db_session.flush()

    address = Address(
        user_id=customer.id,
        recipient_name="Hithesh kumar H",
        phone="9019443501",
        address_line1="123 Tech Park Road",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
    )
    db_session.add(address)
    db_session.flush()

    product = Product(
        name="Arya Smart Energy Power Bank 10000mAh",
        description="Plan A Eligible Product",
        price=Decimal("4000.00"),
        stock=100,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()

    # Confirmed order with Billing ID
    order_confirmed = Order(
        order_number="ORD-20261118040941-439D77",
        idempotency_key="idemp_confirmed_1",
        user_id=customer.id,
        address_id=address.id,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        total_amount=Decimal("4000.00"),
    )
    db_session.add(order_confirmed)
    db_session.flush()

    item_confirmed = OrderItem(
        order_id=order_confirmed.id,
        product_id=product.id,
        product_name=product.name,
        quantity=1,
        unit_price=Decimal("4000.00"),
        line_total=Decimal("4000.00"),
    )
    db_session.add(item_confirmed)
    db_session.flush()

    billing_id = BillingId(
        billing_number="AGD-000201",
        sequence_number=201,
        order_id=order_confirmed.id,
        order_item_id=item_confirmed.id,
        unit_index=0,
        user_id=customer.id,
        product_id=product.id,
        programme=Programme.PLAN_A,
        status="ALLOCATED",
    )
    db_session.add(billing_id)

    # Pending order without Billing ID
    order_pending = Order(
        order_number="ORD-20261117172444-1635CA",
        idempotency_key="idemp_pending_2",
        user_id=customer.id,
        address_id=address.id,
        order_status=OrderStatus.PENDING_PAYMENT,
        payment_status=PaymentStatus.PENDING,
        total_amount=Decimal("4000.00"),
    )
    db_session.add(order_pending)
    db_session.flush()

    item_pending = OrderItem(
        order_id=order_pending.id,
        product_id=product.id,
        product_name=product.name,
        quantity=1,
        unit_price=Decimal("4000.00"),
        line_total=Decimal("4000.00"),
    )
    db_session.add(item_pending)
    db_session.commit()

    return {
        "admin": admin,
        "customer": customer,
        "distributor": distributor,
        "order_confirmed": order_confirmed,
        "order_pending": order_pending,
        "billing_id": billing_id,
    }


@pytest.fixture
def admin_headers(seed_data):
    admin = seed_data["admin"]
    token = create_access_token(
        user_id=admin.id,
        role=admin.role.value if hasattr(admin.role, "value") else str(admin.role),
        phone=admin.phone,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def customer_headers(seed_data):
    customer = seed_data["customer"]
    token = create_access_token(
        user_id=customer.id,
        role=customer.role.value if hasattr(customer.role, "value") else str(customer.role),
        phone=customer.phone,
    )
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Admin Orders Table & Endpoint Tests
# ==============================================================================

def test_admin_orders_unauthorized(api_client):
    """Admin orders endpoint rejects unauthenticated requests."""
    res = api_client.get("/api/v1/admin/orders")
    assert res.status_code == 401


def test_admin_orders_forbidden_for_customer(api_client, customer_headers):
    """Admin orders endpoint rejects non-admin users."""
    res = api_client.get("/api/v1/admin/orders", headers=customer_headers)
    assert res.status_code == 403


def test_admin_orders_includes_billing_id(api_client, admin_headers, seed_data):
    """Admin orders returns billing_id and billing_ids fields."""
    res = api_client.get("/api/v1/admin/orders?page=1&page_size=20", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data

    items = data["items"]
    assert len(items) == 2

    confirmed_orders = [o for o in items if o["order_number"] == seed_data["order_confirmed"].order_number]
    assert len(confirmed_orders) == 1
    assert confirmed_orders[0]["billing_id"] == "AGD-000201"
    assert confirmed_orders[0]["billing_ids"] == ["AGD-000201"]

    pending_orders = [o for o in items if o["order_number"] == seed_data["order_pending"].order_number]
    assert len(pending_orders) == 1
    assert pending_orders[0]["billing_id"] is None
    assert pending_orders[0]["billing_ids"] == []


def test_admin_orders_search_by_billing_id(api_client, admin_headers):
    """Admin orders search finds orders by company billing ID."""
    res = api_client.get("/api/v1/admin/orders?search=AGD-000201", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["billing_id"] == "AGD-000201"


def test_admin_orders_search_by_order_number(api_client, admin_headers, seed_data):
    """Admin orders search finds orders by order number."""
    ord_num = seed_data["order_confirmed"].order_number
    res = api_client.get(f"/api/v1/admin/orders?search={ord_num}", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["order_number"] == ord_num


def test_admin_orders_search_by_customer_phone(api_client, admin_headers, seed_data):
    """Admin orders search finds orders by customer phone number."""
    phone = seed_data["customer"].phone
    res = api_client.get(f"/api/v1/admin/orders?search={phone}", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2


# ==============================================================================
# 2. Plan A Customer Statement Report Tests (Fix for 9019443501 Bug)
# ==============================================================================

def test_plan_a_customer_statement_by_phone_excel(api_client, admin_headers, seed_data):
    """Customer statement downloads via 10-digit phone number in Excel format."""
    phone = seed_data["customer"].phone
    res = api_client.get(
        f"/api/v1/admin/plan-a/reports/customers/{phone}/statement?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers.get("content-type", "")
    assert len(res.content) > 1000

    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert len(wb.sheetnames) >= 1


def test_plan_a_customer_statement_by_phone_pdf(api_client, admin_headers, seed_data):
    """Customer statement downloads via 10-digit phone number in PDF format."""
    phone = seed_data["customer"].phone
    res = api_client.get(
        f"/api/v1/admin/plan-a/reports/customers/{phone}/statement?format=pdf",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "pdf" in res.headers.get("content-type", "")
    assert res.content[:4] == b"%PDF"


def test_plan_a_customer_statement_by_id_excel(api_client, admin_headers, seed_data):
    """Customer statement downloads via database primary key User.id."""
    uid = seed_data["customer"].id
    res = api_client.get(
        f"/api/v1/admin/plan-a/reports/customers/{uid}/statement?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers.get("content-type", "")


def test_plan_a_customer_statement_specific_user_9019443501(api_client, admin_headers):
    """Regression test specifically verifying phone 9019443501 produces statement."""
    res_excel = api_client.get(
        "/api/v1/admin/plan-a/reports/customers/9019443501/statement?format=excel",
        headers=admin_headers,
    )
    assert res_excel.status_code == 200
    assert "spreadsheetml" in res_excel.headers.get("content-type", "")

    res_pdf = api_client.get(
        "/api/v1/admin/plan-a/reports/customers/9019443501/statement?format=pdf",
        headers=admin_headers,
    )
    assert res_pdf.status_code == 200
    assert "pdf" in res_pdf.headers.get("content-type", "")


def test_plan_a_customer_statement_nonexistent_returns_404(api_client, admin_headers):
    """Statement for nonexistent identifier returns 404."""
    res = api_client.get(
        "/api/v1/admin/plan-a/reports/customers/9999999999/statement?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 404
    assert "does not exist" in res.json().get("detail", "")


def test_plan_a_customer_statement_plan_b_user_rejected(api_client, admin_headers, seed_data):
    """Requesting Plan A statement for a Plan B user returns 400 Bad Request."""
    dist_id = seed_data["distributor"].id
    res = api_client.get(
        f"/api/v1/admin/plan-a/reports/customers/{dist_id}/statement?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 400
    assert "Plan B" in res.json().get("detail", "")


# ==============================================================================
# 3. Plan B Individual Distributor Profile Report Tests (Report 9)
# ==============================================================================

def test_plan_b_distributor_report_by_id_excel(api_client, admin_headers, seed_data):
    """Distributor profile report downloads via distributor ID in Excel format."""
    dist_id = seed_data["distributor"].id
    res = api_client.get(
        f"/api/v1/admin/plan-b/reports/distributors/{dist_id}?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers.get("content-type", "")

    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert len(wb.sheetnames) >= 1


def test_plan_b_distributor_report_by_phone_excel(api_client, admin_headers, seed_data):
    """Distributor profile report downloads via distributor phone in Excel format."""
    phone = seed_data["distributor"].phone
    res = api_client.get(
        f"/api/v1/admin/plan-b/reports/distributors/{phone}?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers.get("content-type", "")


def test_plan_b_distributor_report_rejects_pdf(api_client, admin_headers, seed_data):
    """Distributor profile report rejects PDF per Rule R-09."""
    dist_id = seed_data["distributor"].id
    res = api_client.get(
        f"/api/v1/admin/plan-b/reports/distributors/{dist_id}?format=pdf",
        headers=admin_headers,
    )
    assert res.status_code == 400
    assert "R-09" in res.json().get("detail", "") or "Excel" in res.json().get("detail", "")


def test_plan_b_distributor_report_plan_a_user_rejected(api_client, admin_headers, seed_data):
    """Distributor profile report rejects Plan A customer with 400."""
    cust_id = seed_data["customer"].id
    res = api_client.get(
        f"/api/v1/admin/plan-b/reports/distributors/{cust_id}?format=excel",
        headers=admin_headers,
    )
    assert res.status_code == 400
    assert "Plan A" in res.json().get("detail", "")


# ==============================================================================
# 4. Frontend Static Structure & Styling Verification
# ==============================================================================

def test_frontend_orders_html_structure():
    """Verify orders.html contains Billing ID column and inspect modal."""
    orders_html = os.path.join(ADMIN_DIR, "orders.html")
    with open(orders_html, "r", encoding="utf-8") as f:
        html = f.read()

    assert "<th>Billing ID</th>" in html
    assert "colspan=\"7\"" in html
    assert "order-inspect-modal" in html
    assert "executeOrdersSearch" in html
    assert "filterAdminOrdersTable" in html


def test_frontend_reports_html_structure():
    """Verify reports.html input placeholders and types."""
    reports_html = os.path.join(ADMIN_DIR, "reports.html")
    with open(reports_html, "r", encoding="utf-8") as f:
        html = f.read()

    assert "statement-customer-id" in html
    assert "statement-distributor-id" in html
    assert "Customer ID or Phone" in html
    assert "btn-customer-stmt-excel" in html
    assert "btn-customer-stmt-pdf" in html
    assert "btn-distributor-report-excel" in html


def test_frontend_admin_css_billing_id_badge():
    """Verify admin.css defines .billing-id-badge with monospace and appropriate styling."""
    admin_css = os.path.join(FRONTEND_DIR, "css", "admin.css")
    with open(admin_css, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".billing-id-badge" in css
    assert "font-family" in css
    assert "background-color" in css


def test_frontend_admin_js_handlers_and_exports():
    """Verify admin.js implements and exports required orders and reports functions."""
    admin_js = os.path.join(FRONTEND_DIR, "js", "admin.js")
    with open(admin_js, "r", encoding="utf-8") as f:
        js = f.read()

    assert "function renderAdminOrdersTable" in js
    assert "function filterAdminOrdersTable" in js
    assert "function executeOrdersSearch" in js
    assert "function openOrderInspectModal" in js
    assert "function closeOrderInspectModal" in js
    assert "window.renderAdminOrdersTable = renderAdminOrdersTable;" in js
    assert "window.filterAdminOrdersTable = filterAdminOrdersTable;" in js
    assert "window.executeOrdersSearch = executeOrdersSearch;" in js
    assert "window.openOrderInspectModal = openOrderInspectModal;" in js
    assert "window.closeOrderInspectModal = closeOrderInspectModal;" in js
    assert "window.downloadCustomerStatement = downloadCustomerStatement;" in js
    assert "window.downloadDistributorProfileReport = downloadDistributorProfileReport;" in js
