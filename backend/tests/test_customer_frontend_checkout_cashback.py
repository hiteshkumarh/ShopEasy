"""Comprehensive tests for ShopEasy / Arya Global Digital Customer Frontend UI,
Checkout, Authentication & Plan A Cashback Corrections across all 7 functional areas.
"""

from decimal import Decimal
import json
import re
from typing import Dict

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import clear_rate_limits
from app.core.security import decode_access_token
from app.models.enums import OrderStatus, PaymentStatus, Programme, UserRole
from app.models.product import Product
from app.models.user import Address, User
from app.schemas.auth import CustomerRegisterResponse
from app.schemas.order import CheckoutRequest, OrderItemResponse, OrderResponse


@pytest.fixture(autouse=True)
def reset_limits():
    clear_rate_limits()
    yield
    clear_rate_limits()


# ===========================================================================
# Area 1: Plan A Cashback Cycle – Replace Numbers with Bulbs
# ===========================================================================

def test_area1_dashboard_html_clean_summary_and_no_wordy_descriptions():
    """Verify dashboard.html displays clean dynamic summary and Option A bulb progress."""
    with open("frontend/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Verify clean dynamic summary element exists and displays 0/48 Bulbs
    assert 'id="cashback-progress-summary"' in html
    assert "Progress: 0/48 Bulbs" in html
    assert "Cashback Cycle Progress" in html
    assert "Target: ₹4,000.00" in html

    # Verify wallet threshold copy updates
    assert "Minimum Withdrawal: ₹700" in html
    assert "Requirement: 48/48 Cycle Completion" in html

    # Verify prohibited wordy texts are removed
    assert "16 contributions = ₹4,000.00" not in html
    assert "Every eligible Power Bank order advances your cycle by illuminating 3 bulbs. Complete all 48 bulbs across 16 contributions to earn ₹4,000.00." not in html
    assert "Cycle Withdrawal Ineligible" not in html
    assert "Full ₹4,000.00 target required for withdrawal" not in html

    # Verify withdrawal button preserves ₹4,000 target rule
    assert "Request ₹4,000.00 Withdrawal" in html


def test_area1_dashboard_js_bulb_icons_no_number_labels():
    """Verify dashboard.js renders visual bulb SVG icons without numbers 1-48 or '#bulbNum' labels."""
    with open("frontend/js/dashboard.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Verify bulb SVG icon is rendered
    assert "bulb-icon-svg" in js
    assert "<path d=\"M9 18h6\"></path>" in js
    assert "<path d=\"M10 22h4\"></path>" in js

    # Verify bulb numbers inside bulb indicator and #bulbNum labels are removed
    assert '<span class="bulb-label">#${bulbNum}</span>' not in js
    assert '<span>${bulbNum}</span>' not in js

    # Verify clean dynamic summary updates to 48 bulbs
    assert "cashback-progress-summary" in js
    assert "Progress: ${illuminatedBulbs}/48 Bulbs" in js

    # Verify wallet note updates
    assert "Minimum Withdrawal: ₹700" in js
    assert "Requirement: 48/48 Cycle Completion" in js

    # Verify withdrawal ineligible text does not contain prohibited wordings
    assert "Cycle Withdrawal Ineligible" not in js


def test_area1_dashboard_css_bulb_indicator_styling():
    """Verify dashboard.css provides glowing illuminated state and unlit neutral state."""
    with open("frontend/css/dashboard.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".bulb-indicator.bulb-on" in css
    assert ".bulb-indicator.bulb-off" in css
    assert ".bulb-icon-svg" in css
    assert "radial-gradient" in css


# ===========================================================================
# Area 2: Currency Symbol Replacement (INR ₹)
# ===========================================================================

def test_area2_format_inr_two_decimal_precision():
    """Verify formatINR in data.js and main.js enforces two decimal places and INR symbol."""
    with open("frontend/js/data.js", "r", encoding="utf-8") as f:
        data_js = f.read()

    assert "minimumFractionDigits: 2" in data_js
    assert "maximumFractionDigits: 2" in data_js
    assert "window.formatINR = formatINR" in data_js

    with open("frontend/js/main.js", "r", encoding="utf-8") as f:
        main_js = f.read()

    assert "minimumFractionDigits: 2" in main_js
    assert "maximumFractionDigits: 2" in main_js
    assert "window.formatINR = formatINR" in main_js


def test_area2_no_literal_dollar_currency_in_customer_html():
    """Verify no customer-facing HTML contains literal dollar signs in prose or price tags."""
    customer_pages = [
        "frontend/index.html",
        "frontend/products.html",
        "frontend/product-details.html",
        "frontend/cart.html",
        "frontend/checkout.html",
        "frontend/orders.html",
        "frontend/dashboard.html",
        "frontend/distributor-dashboard.html",
        "frontend/profile.html",
        "frontend/login.html",
    ]
    for page in customer_pages:
        with open(page, "r", encoding="utf-8") as f:
            content = f.read()
        # Remove scripts and styles
        clean = re.sub(r"<script[\s\S]*?</script>", "", content)
        clean = re.sub(r"<style[\s\S]*?</style>", "", clean)
        # Search for dollar prices
        matches = re.findall(r"(\$[0-9A-Za-z\.,]+)", clean)
        assert len(matches) == 0, f"Found dollar currency in {page}: {matches}"


# ===========================================================================
# Area 3: Apple-Style Pill Quantity Selector
# ===========================================================================

def test_area3_pill_quantity_selector_structure_and_dynamic_subtotal():
    """Verify products.js implements Apple-style pill selector with real-time subtotal."""
    with open("frontend/js/products.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "apple-pill-qty-selector" in js
    assert "apple-pill-btn pill-minus" in js
    assert "apple-pill-btn pill-plus" in js
    assert "apple-pill-input" in js
    assert "detail-dynamic-subtotal" in js
    assert "data-unit-price" in js
    assert "data-max-stock" in js

    # Verify bounds enforcement and dynamic recalculation in adjustDetailQty
    assert "Math.max(1, Math.min(maxStock, val + delta))" in js
    assert "subtotalEl.innerHTML" in js

    with open("frontend/css/products.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".apple-pill-qty-selector" in css
    assert ".apple-pill-btn" in css
    assert ".apple-pill-input" in css


def test_area3_cart_apple_style_pill_selector_and_order_summary():
    """Verify cart.js and cart.css implement Apple-style pill selector and refined order summary."""
    with open("frontend/js/cart.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "apple-cart-pill-selector" in js
    assert "apple-cart-pill-minus" in js
    assert "apple-cart-pill-plus" in js
    assert "apple-cart-pill-value" in js
    assert "summary-shipping-pill" in js
    assert "cart-checkout-cta" in js

    with open("frontend/css/cart.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".apple-cart-pill-selector" in css
    assert ".apple-cart-pill-btn" in css
    assert ".apple-cart-pill-display" in css
    assert ".summary-shipping-pill" in css
    assert ".cart-checkout-cta" in css


# ===========================================================================
# Area 4: Orders Page Images & Human Statuses
# ===========================================================================

def test_area4_order_item_schema_and_model_product_image():
    """Verify OrderItem model and OrderItemResponse schema expose product_image."""
    with open("backend/app/schemas/order.py", "r", encoding="utf-8") as f:
        schema = f.read()
    assert "product_image: Optional[str] = None" in schema

    with open("backend/app/models/order.py", "r", encoding="utf-8") as f:
        model = f.read()
    assert "def product_image(self)" in model


def test_area4_orders_html_renders_images_and_human_statuses():
    """Verify orders.html renders real product image tags and human-readable statuses."""
    with open("frontend/orders.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Verify placeholder PKG is eliminated
    assert ">PKG<" not in html
    assert "order-item-img" in html
    assert "formatHumanStatus" in html
    assert "Payment Pending" in html
    assert "Payment Successful" in html
    assert "statusInfo.badgeClass" in html


# ===========================================================================
# Area 5: Profile Icon Navigation
# ===========================================================================

def test_area5_navigation_js_profile_icon_link():
    """Verify customer account navigation icon links to profile.html and Orders link remains orders.html."""
    with open("frontend/js/navigation.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "btn.setAttribute('href', 'profile.html')" in js
    assert "btn.setAttribute('title', `Profile (" in js
    assert "btn.textContent = `My Profile (" in js


# ===========================================================================
# Area 6: Registration Auto-Login
# ===========================================================================

def test_area6_registration_returns_access_token(api_client: TestClient):
    """Verify registering a new customer generates and returns an access token."""
    phone = "9876000001"
    res = api_client.post(
        "/api/v1/auth/customer/register",
        json={
            "full_name": "Rohan Sharma",
            "phone": phone,
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_A",
        },
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    assert "access_token" in data
    assert data["access_token"] is not None
    assert data["token_type"] == "bearer"

    # Verify token payload
    token_claims = decode_access_token(data["access_token"])
    assert token_claims["phone"] == phone
    assert token_claims["role"] == "customer"


def test_area6_auth_js_auto_login_and_redirect():
    """Verify auth.js hydrates session and redirects immediately without prompting re-login."""
    with open("frontend/js/auth.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "window.ShopEasyAPI.setCustomerToken(authToken)" in js
    assert "window.ShopEasyAPI.setCustomerUser" in js
    assert "Registration successful. Redirecting to dashboard..." in js
    assert "Please sign in" not in js


# ===========================================================================
# Area 7: Checkout Simulated Payment Completion
# ===========================================================================

def test_area7_checkout_with_simulate_payment_confirms_immediately(
    api_client: TestClient,
    db_session,
):
    """Verify submitting checkout with simulate_payment=True transitions order to CONFIRMED and COMPLETED."""
    from app.models.billing import BillingCounter

    # Seed BillingCounter for fulfilment allocation
    counter = db_session.query(BillingCounter).filter(BillingCounter.sequence_name == "GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=0)
        db_session.add(counter)
        db_session.commit()

    # 1. Register customer
    reg_res = api_client.post(
        "/api/v1/auth/customer/register",
        json={
            "full_name": "Aryan Patel",
            "phone": "9876000002",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "programme": "PLAN_A",
        },
    )
    assert reg_res.status_code in (200, 201), reg_res.text
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create address
    addr_res = api_client.post(
        "/api/v1/addresses",
        headers=headers,
        json={
            "recipient_name": "Aryan Patel",
            "phone": "9876000002",
            "address_line1": "100 Innovation Way",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560001",
            "is_default": True,
        },
    )
    assert addr_res.status_code in (200, 201), addr_res.text
    addr_id = addr_res.json()["id"]

    # 3. Create Power Bank product in stock
    prod = Product(
        name="Arya 20000mAh Power Bank",
        product_code="POWER-BANK-20K",
        price=Decimal("3999.00"),
        stock=50,
        is_active=True,
        image_url="https://images.unsplash.com/photo-1609592424364-e1e5b8d03541?w=400",
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)

    # 4. Add to cart
    cart_res = api_client.post(
        "/api/v1/cart",
        headers=headers,
        json={"product_id": prod.id, "quantity": 1},
    )
    assert cart_res.status_code == 200

    # 5. Execute checkout with simulate_payment=True
    chk_res = api_client.post(
        "/api/v1/orders/checkout",
        headers=headers,
        json={
            "address_id": addr_id,
            "idempotency_key": "test_sim_chk_12345",
            "simulate_payment": True,
        },
    )
    assert chk_res.status_code in (200, 201), chk_res.text
    order_data = chk_res.json()

    # 6. Verify order transitioned to CONFIRMED and COMPLETED
    assert order_data["order_status"] == OrderStatus.CONFIRMED.value
    assert order_data["payment_status"] == PaymentStatus.COMPLETED.value
    assert order_data["payment_reference"] is not None

    # 7. Verify Billing IDs were allocated and product image populated
    items = order_data["order_items"]
    assert len(items) == 1
    assert items[0]["product_image"] == prod.image_url
    assert len(items[0]["billing_ids"]) == 1
    assert items[0]["billing_ids"][0]["billing_number"].startswith("AGD-")

    # 8. Verify cart is cleared
    cart_check = api_client.get("/api/v1/cart", headers=headers)
    assert cart_check.status_code == 200
    assert len(cart_check.json()["items"]) == 0
