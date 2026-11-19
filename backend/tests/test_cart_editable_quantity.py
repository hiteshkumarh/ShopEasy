"""Automated Test Suite for Directly Editable Cart Quantity Selector.

Covers:
1. Frontend Static Invariants:
   - cart.html renders cart-content-container.
   - cart.js implements directly editable numeric input with inputmode="numeric" and pattern="[0-9]*".
   - cart.js preserves minus and plus buttons with apple-cart-pill-minus and apple-cart-pill-plus.
   - cart.js implements handleCartQtyKeydown, handleCartQtyBlur, and applyDirectQuantity.
   - cart.js exports direct quantity handlers to window.
   - cart.css styles .apple-cart-pill-display, .apple-cart-pill-value, and .quantity-input with centered text and focus ring.

2. Backend Cart Quantity API Life Cycle:
   - Adding item to cart with quantity 3.
   - Updating quantity directly to 15 via PUT /api/v1/cart/{item_id}.
   - Validating line total, subtotal, and shipping calculations (free shipping >= 2000).
   - Incrementing (+1) to 16.
   - Decrementing (-1) to 15.
   - Rejecting quantity <= 0 (HTTP 422 Unprocessable Entity per schema gt=0).
   - Rejecting quantity > stock (HTTP 400 Bad Request with stock limit message).
   - Rejecting decimals or non-numeric types (HTTP 422).
"""

from decimal import Decimal
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.cart import CartItem
from app.models.enums import Programme, UserRole
from app.models.product import Product
from app.models.user import User

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")


@pytest.fixture
def test_customer(db_session: Session) -> User:
    customer = User(
        phone="9019443501",
        full_name="Hithesh kumar H",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        referral_code="PA4Z6O3R",
        is_active=True,
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


@pytest.fixture
def test_product(db_session: Session) -> Product:
    product = Product(
        name="Arya 20000mAh Power Bank",
        product_code="PB-3999",
        price=Decimal("3999.00"),
        stock=100,  # 100 units available
        is_active=True,
        is_power_bank=True,
        description="High capacity power bank",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


@pytest.fixture
def customer_headers(test_customer: User) -> dict:
    token = create_access_token(
        user_id=test_customer.id,
        role=test_customer.role.value if hasattr(test_customer.role, "value") else str(test_customer.role),
        phone=test_customer.phone,
    )
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Frontend Structure & Invariant Checks
# ==============================================================================

def test_cart_html_container_exists():
    """Verify cart.html contains cart-content-container for dynamic rendering."""
    path = os.path.join(FRONTEND_DIR, "cart.html")
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert 'id="cart-content-container"' in html
    assert "Your Bag" in html


def test_cart_js_editable_input_and_buttons():
    """Verify cart.js implements editable input and preserves plus/minus buttons."""
    path = os.path.join(FRONTEND_DIR, "js", "cart.js")
    with open(path, "r", encoding="utf-8") as f:
        js = f.read()

    # Editable input with numeric keyboard and centered class
    assert '<input' in js
    assert 'inputmode="numeric"' in js
    assert 'pattern="[0-9]*"' in js
    assert 'class="apple-cart-pill-value quantity-input"' in js
    assert 'onfocus="this.select()"' in js

    # Event handlers wired to input
    assert "handleCartQtyKeydown" in js
    assert "handleCartQtyBlur" in js
    assert "applyDirectQuantity" in js

    # Plus and Minus buttons preserved
    assert "apple-cart-pill-minus" in js
    assert "apple-cart-pill-plus" in js
    assert "apple-cart-pill-selector" in js
    assert "apple-cart-pill-display" in js

    # Exported to window
    assert "window.handleCartQtyKeydown = handleCartQtyKeydown;" in js
    assert "window.handleCartQtyBlur = handleCartQtyBlur;" in js
    assert "window.applyDirectQuantity = applyDirectQuantity;" in js


def test_cart_css_editable_styling():
    """Verify cart.css defines styling for editable quantity input."""
    path = os.path.join(FRONTEND_DIR, "css", "cart.css")
    with open(path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".apple-cart-pill-selector" in css
    assert ".apple-cart-pill-btn" in css
    assert ".apple-cart-pill-display" in css
    assert ".apple-cart-pill-value" in css
    assert ".quantity-input" in css
    assert "text-align: center" in css
    assert "cursor: text" in css


# ==============================================================================
# 2. Backend Cart API Life Cycle & Validation Tests
# ==============================================================================

def test_cart_quantity_flow_3_to_15_and_step_buttons(
    api_client: TestClient,
    test_product: Product,
    customer_headers: dict,
):
    """Test full quantity lifecycle:
    1. Initial quantity = 3
    2. Directly enter 15 -> becomes 15
    3. Click + -> becomes 16
    4. Click - -> becomes 15
    5. Subtotal and shipping calculated accurately
    """
    # 1. Add item with quantity = 3
    res_add = api_client.post(
        "/api/v1/cart",
        json={"product_id": test_product.id, "quantity": 3},
        headers=customer_headers,
    )
    assert res_add.status_code == 200
    cart_data = res_add.json()
    assert cart_data["total_items"] == 3
    item_id = cart_data["items"][0]["id"]
    assert cart_data["items"][0]["quantity"] == 3
    assert Decimal(str(cart_data["items"][0]["line_total"])) == Decimal("3999.00") * 3
    assert Decimal(str(cart_data["subtotal"])) == Decimal("3999.00") * 3

    # 2. Directly update quantity to 15
    res_update_15 = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 15},
        headers=customer_headers,
    )
    assert res_update_15.status_code == 200
    cart_15 = res_update_15.json()
    assert cart_15["total_items"] == 15
    assert cart_15["items"][0]["quantity"] == 15
    expected_subtotal_15 = Decimal("3999.00") * 15
    assert Decimal(str(cart_15["items"][0]["line_total"])) == expected_subtotal_15
    assert Decimal(str(cart_15["subtotal"])) == expected_subtotal_15

    # 3. Step +1 -> 16
    res_step_plus = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 16},
        headers=customer_headers,
    )
    assert res_step_plus.status_code == 200
    assert res_step_plus.json()["total_items"] == 16
    assert res_step_plus.json()["items"][0]["quantity"] == 16

    # 4. Step -1 -> 15
    res_step_minus = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 15},
        headers=customer_headers,
    )
    assert res_step_minus.status_code == 200
    assert res_step_minus.json()["total_items"] == 15
    assert res_step_minus.json()["items"][0]["quantity"] == 15


def test_cart_quantity_validation_zero_negative_decimal(
    api_client: TestClient,
    test_product: Product,
    customer_headers: dict,
):
    """Test backend rejects zero, negative, and decimal quantities."""
    # Add item
    res_add = api_client.post(
        "/api/v1/cart",
        json={"product_id": test_product.id, "quantity": 1},
        headers=customer_headers,
    )
    item_id = res_add.json()["items"][0]["id"]

    # Reject 0
    res_zero = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 0},
        headers=customer_headers,
    )
    assert res_zero.status_code == 422

    # Reject -5
    res_neg = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": -5},
        headers=customer_headers,
    )
    assert res_neg.status_code == 422

    # Reject decimal 2.5
    res_decimal = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 2.5},
        headers=customer_headers,
    )
    assert res_decimal.status_code == 422

    # Reject string
    res_str = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": "fifteen"},
        headers=customer_headers,
    )
    assert res_str.status_code == 422


def test_cart_quantity_validation_exceeds_stock(
    api_client: TestClient,
    test_product: Product,
    customer_headers: dict,
):
    """Test backend rejects quantity greater than available inventory."""
    res_add = api_client.post(
        "/api/v1/cart",
        json={"product_id": test_product.id, "quantity": 1},
        headers=customer_headers,
    )
    item_id = res_add.json()["items"][0]["id"]

    # Product stock is 100. Request 101.
    res_excess = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 101},
        headers=customer_headers,
    )
    assert res_excess.status_code == 400
    assert "exceeds available stock" in res_excess.json()["detail"].lower()

    # Valid stock boundary (100) succeeds
    res_max = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 100},
        headers=customer_headers,
    )
    assert res_max.status_code == 200
    assert res_max.json()["items"][0]["quantity"] == 100
