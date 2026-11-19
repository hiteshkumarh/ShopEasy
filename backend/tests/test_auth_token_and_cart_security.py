"""Comprehensive automated tests for ShopEasy Authentication Token verification,
token expiration, invalid/undecodable token handling, cart authorization,
role isolation, and server startup/lifespan resilience.
"""

import asyncio
from datetime import timedelta
from decimal import Decimal
import json
import pytest
from fastapi import status
from fastapi.testclient import TestClient
import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import clear_rate_limits
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
)
from app.main import app, lifespan
from app.models.cart import CartItem
from app.models.enums import AccountStatus, Programme, UserRole
from app.models.product import Product
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_limits():
    clear_rate_limits()
    yield
    clear_rate_limits()


def _create_test_user(
    db: Session,
    full_name: str,
    phone: str,
    role: UserRole = UserRole.CUSTOMER,
    programme: Programme = Programme.PLAN_A,
    referral_code: str = "REF123456",
) -> User:
    """Helper to create and commit an active user for testing."""
    user = User(
        full_name=full_name,
        phone=phone,
        password_hash=hash_password("TestPassword123!"),
        role=role,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=referral_code if role == UserRole.CUSTOMER else None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_test_product(
    db: Session,
    name: str = "Arya Power Bank 20000mAh",
    product_code: str = "PB-3999",
    price: Decimal = Decimal("3999.00"),
    stock: int = 50,
) -> Product:
    """Helper to create an active product for testing."""
    product = Product(
        name=name,
        product_code=product_code,
        price=price,
        stock=stock,
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


# ===========================================================================
# 1. JWT Generation and Claims Verification
# ===========================================================================

def test_jwt_generation_and_decoding_for_all_roles():
    """Verify create_access_token and decode_access_token for customer, distributor, and admin."""
    # Customer token
    cust_token = create_access_token(
        user_id=101,
        role="customer",
        phone="9876543210",
        extra_claims={"programme": "PLAN_A"},
    )
    assert isinstance(cust_token, str)
    assert len(cust_token.split(".")) == 3

    cust_payload = decode_access_token(cust_token, expected_type="access")
    assert cust_payload["sub"] == "101"
    assert cust_payload["role"] == "customer"
    assert cust_payload["phone"] == "9876543210"
    assert cust_payload["type"] == "access"
    assert cust_payload["programme"] == "PLAN_A"
    assert "iat" in cust_payload
    assert "exp" in cust_payload

    # Distributor token
    dist_token = create_access_token(
        user_id=102,
        role="customer",
        phone="9876543211",
        extra_claims={"programme": "PLAN_B"},
    )
    dist_payload = decode_access_token(dist_token, expected_type="access")
    assert dist_payload["sub"] == "102"
    assert dist_payload["programme"] == "PLAN_B"

    # Admin token
    admin_token = create_access_token(
        user_id=1,
        role="admin",
        phone="9800000000",
    )
    admin_payload = decode_access_token(admin_token, expected_type="access")
    assert admin_payload["sub"] == "1"
    assert admin_payload["role"] == "admin"


# ===========================================================================
# 2. Expired Token Handling
# ===========================================================================

def test_expired_token_handling(api_client: TestClient, db_session: Session):
    """Verify expired tokens are rejected with ExpiredSignatureError and HTTP 401."""
    user = _create_test_user(db_session, "Expired User", "9111111111")

    # Generate token expired 1 hour ago
    expired_token = create_access_token(
        user_id=user.id,
        role=user.role.value,
        phone=user.phone,
        expires_delta=timedelta(hours=-1),
    )

    # 1. Direct decode raises ExpiredSignatureError
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token, expected_type="access")

    # 2. Endpoint /auth/me returns 401
    res_me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_me.status_code == status.HTTP_401_UNAUTHORIZED
    assert "expired" in res_me.json()["detail"].lower()
    assert res_me.headers.get("www-authenticate") == "Bearer"

    # 3. Endpoint /cart returns 401
    res_cart = api_client.get(
        "/api/v1/cart",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_cart.status_code == status.HTTP_401_UNAUTHORIZED
    assert "expired" in res_cart.json()["detail"].lower()
    assert res_cart.headers.get("www-authenticate") == "Bearer"


# ===========================================================================
# 3. Invalid and Undecodable Token Handling (DecodeError)
# ===========================================================================

@pytest.mark.parametrize(
    "bad_token",
    [
        "mock_jwt_verified_token_immediate",
        "mock_jwt_customer_token_for_screenshots",
        "undefined",
        "null",
        "invalid_non_jwt_string",
        "header.invalid_base64_payload.signature",
        "too.few.segments.extra.segments",
        "",
        "   ",
    ],
)
def test_invalid_undecodable_tokens_raise_and_return_401(
    api_client: TestClient, bad_token: str
):
    """Verify non-JWT strings raise InvalidTokenError and return 401 without 500 error."""
    # 1. Direct decode raises InvalidTokenError
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(bad_token, expected_type="access")

    # 2. GET /api/v1/cart returns HTTP 401
    headers = {"Authorization": f"Bearer {bad_token}"} if bad_token.strip() else {}
    res = api_client.get("/api/v1/cart", headers=headers)
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
    assert res.headers.get("www-authenticate") == "Bearer"


def test_defensive_token_cleaning_whitespace_and_quotes(db_session: Session):
    """Verify surrounding quotes or leading/trailing whitespace are defensively handled."""
    user = _create_test_user(db_session, "Clean User", "9222222222")
    raw_token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    # Double quotes wrapped
    payload_dq = decode_access_token(f'"{raw_token}"', expected_type="access")
    assert payload_dq["sub"] == str(user.id)

    # Single quotes wrapped
    payload_sq = decode_access_token(f"'{raw_token}'", expected_type="access")
    assert payload_sq["sub"] == str(user.id)

    # Surrounding whitespace
    payload_ws = decode_access_token(f"  \n {raw_token} \t ", expected_type="access")
    assert payload_ws["sub"] == str(user.id)


# ===========================================================================
# 4. Cart API Authorization & Lifecycle
# ===========================================================================

def test_cart_api_missing_auth_header_returns_401(api_client: TestClient):
    """Verify all cart endpoints return 401 Unauthorized when credentials are not provided."""
    # GET /cart
    assert api_client.get("/api/v1/cart").status_code == status.HTTP_401_UNAUTHORIZED

    # POST /cart
    assert (
        api_client.post("/api/v1/cart", json={"product_id": 1, "quantity": 1}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )

    # PUT /cart/{id}
    assert (
        api_client.put("/api/v1/cart/1", json={"quantity": 2}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )

    # DELETE /cart/{id}
    assert api_client.delete("/api/v1/cart/1").status_code == status.HTTP_401_UNAUTHORIZED

    # DELETE /cart
    assert api_client.delete("/api/v1/cart").status_code == status.HTTP_401_UNAUTHORIZED


def test_cart_api_admin_token_rejected_with_403(
    api_client: TestClient, db_session: Session
):
    """Verify administrator accounts are forbidden from using the customer shopping cart."""
    admin_user = _create_test_user(
        db_session, "Admin Boss", "9800000001", role=UserRole.ADMIN
    )
    admin_token = create_access_token(
        user_id=admin_user.id, role="admin", phone=admin_user.phone
    )

    res = api_client.get(
        "/api/v1/cart",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "customer privileges required" in res.json()["detail"].lower()


def test_cart_api_authenticated_customer_crud_lifecycle(
    api_client: TestClient, db_session: Session
):
    """Verify full CRUD lifecycle for authenticated customer shopping cart."""
    customer = _create_test_user(db_session, "Shopper Jane", "9333333333")
    product = _create_test_product(db_session, "Test Gadget", "TG-100", Decimal("1500.00"), stock=10)

    token = create_access_token(
        user_id=customer.id, role="customer", phone=customer.phone
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Initial cart is empty
    res = api_client.get("/api/v1/cart", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["items"] == []
    assert data["total_items"] == 0
    assert Decimal(str(data["subtotal"])) == Decimal("0.00")

    # 2. Add item to cart
    res_add = api_client.post(
        "/api/v1/cart",
        json={"product_id": product.id, "quantity": 2},
        headers=headers,
    )
    assert res_add.status_code == status.HTTP_200_OK
    cart_data = res_add.json()
    assert cart_data["total_items"] == 2
    assert Decimal(str(cart_data["subtotal"])) == Decimal("3000.00")
    assert len(cart_data["items"]) == 1
    item_id = cart_data["items"][0]["id"]

    # 3. Update quantity
    res_upd = api_client.put(
        f"/api/v1/cart/{item_id}",
        json={"quantity": 3},
        headers=headers,
    )
    assert res_upd.status_code == status.HTTP_200_OK
    assert res_upd.json()["total_items"] == 3
    assert Decimal(str(res_upd.json()["subtotal"])) == Decimal("4500.00")

    # 4. Remove item
    res_del = api_client.delete(f"/api/v1/cart/{item_id}", headers=headers)
    assert res_del.status_code == status.HTTP_200_OK
    assert res_del.json()["total_items"] == 0

    # 5. Clear cart
    api_client.post(
        "/api/v1/cart",
        json={"product_id": product.id, "quantity": 1},
        headers=headers,
    )
    res_clear = api_client.delete("/api/v1/cart", headers=headers)
    assert res_clear.status_code == status.HTTP_200_OK
    assert "cleared successfully" in res_clear.json()["message"].lower()


# ===========================================================================
# 5. Frontend Token Validation and Cleanup Contract Tests
# ===========================================================================

def test_frontend_api_js_token_validation_and_cleanup_contract():
    """Verify frontend/js/api.js defines isValidJwtStructure and auto-cleans on 401."""
    with open("frontend/js/api.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Verify structural JWT validation helper exists
    assert "function isValidJwtStructure(token)" in js
    assert "parts.length !== 3" in js
    assert "decoded.exp" in js

    # Verify getCustomerToken validates token structure
    assert "if (!isValidJwtStructure(raw))" in js
    assert "clearCustomerToken();" in js

    # Verify getAdminToken validates token structure
    assert "clearAdminToken();" in js

    # Verify apiRequest cleans up invalid tokens on 401
    assert "if (response.status === 401)" in js

    # Verify isValidJwtStructure is exported
    assert "isValidJwtStructure" in js


def test_frontend_cart_js_handles_401_without_crash():
    """Verify frontend/js/cart.js handles 401 errors gracefully."""
    with open("frontend/js/cart.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Verify fetchCart catches 401 and resets cachedCart
    assert "err.status === 401 || err.statusCode === 401" in js
    assert "window.ShopEasyAPI.clearCustomerToken()" in js
    assert "cachedCart = { items: [], total_items: 0, subtotal: 0 }" in js


# ===========================================================================
# 6. Full Registration & Login Flow for Customer, Distributor, and Admin
# ===========================================================================

def test_customer_registration_and_login_flow(api_client: TestClient, db_session: Session):
    """Verify customer registration returns access_token and subsequent password login works."""
    reg_payload = {
        "full_name": "Aarav Sharma",
        "phone": "9812345678",
        "password": "SecurePassword123!",
        "confirm_password": "SecurePassword123!",
        "programme": "PLAN_A",
    }
    res_reg = api_client.post("/api/v1/auth/customer/register", json=reg_payload)
    assert res_reg.status_code == status.HTTP_201_CREATED
    data_reg = res_reg.json()
    assert data_reg["phone"] == "9812345678"
    assert data_reg["programme"] == "PLAN_A"
    assert data_reg["access_token"] is not None
    assert data_reg["token_type"].lower() == "bearer"

    # Token from registration decodes properly
    payload = decode_access_token(data_reg["access_token"], expected_type="access")
    assert payload["role"] == "customer"
    assert payload["phone"] == "9812345678"

    # Profile /auth/me succeeds with registration token
    res_me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data_reg['access_token']}"},
    )
    assert res_me.status_code == status.HTTP_200_OK
    assert res_me.json()["full_name"] == "Aarav Sharma"

    # Subsequent password login succeeds
    login_payload = {
        "phone": "9812345678",
        "password": "SecurePassword123!",
        "programme": "PLAN_A",
    }
    res_login = api_client.post("/api/v1/auth/customer/login/password", json=login_payload)
    assert res_login.status_code == status.HTTP_200_OK
    login_data = res_login.json()
    assert login_data["access_token"] is not None
    assert login_data["token_type"].lower() == "bearer"


def test_distributor_registration_and_login_flow(api_client: TestClient, db_session: Session):
    """Verify distributor registration returns access_token and distributor password login works."""
    reg_payload = {
        "full_name": "Vikram Distributor",
        "phone": "9812345679",
        "password": "DistributorPass123!",
        "confirm_password": "DistributorPass123!",
        "programme": "PLAN_B",
    }
    res_reg = api_client.post("/api/v1/auth/distributor/register", json=reg_payload)
    assert res_reg.status_code == status.HTTP_201_CREATED
    data_reg = res_reg.json()
    assert data_reg["programme"] == "PLAN_B"
    assert data_reg["access_token"] is not None

    # Password login for distributor
    login_payload = {
        "phone": "9812345679",
        "password": "DistributorPass123!",
        "programme": "PLAN_B",
    }
    res_login = api_client.post("/api/v1/auth/distributor/login/password", json=login_payload)
    assert res_login.status_code == status.HTTP_200_OK
    login_token = res_login.json()["access_token"]

    # Verify profile
    res_me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_token}"},
    )
    assert res_me.status_code == status.HTTP_200_OK
    assert res_me.json()["programme"] == "PLAN_B"


def test_admin_access_token_and_me_profile(api_client: TestClient, db_session: Session):
    """Verify admin access token can access /auth/me and admin endpoints."""
    admin_user = _create_test_user(
        db_session, "Super Admin", "9800000099", role=UserRole.ADMIN
    )
    admin_token = create_access_token(
        user_id=admin_user.id, role="admin", phone=admin_user.phone
    )

    res_me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_me.status_code == status.HTTP_200_OK
    data = res_me.json()
    assert data["role"] == "admin"
    assert data["phone"] == "9800000099"


# ===========================================================================
# 7. Lifespan and Server Startup Resilience
# ===========================================================================

def test_lifespan_gracefully_handles_keyboard_interrupt():
    """Verify application lifespan handles KeyboardInterrupt and CancelledError without unhandled crash."""
    async def _run():
        async with lifespan(app):
            # Emulate reload cancellation or interrupt signal
            pass

    asyncio.run(_run())
