"""
backend/tests/test_wp12_step5_billing_id_api.py
API integration tests for WP-12 Step 5: Billing ID API Integration.

Verifies:
1. Successful 1-unit order returns actual billing_number.
2. Multi-unit order returns separate Billing IDs for every unit.
3. Every Billing ID belongs to the correct order item (order_item_id match and unit_index).
4. Pending payment does not expose unissued Billing IDs (empty list).
5. Failed payment does not expose unissued Billing IDs (empty list).
6. Customer cannot access another customer's order history (HTTP 404 / ownership filter).
7. Plan A and Plan B data remain isolated.
8. Empty purchase history returns items: [], total: 0.
9. Existing order response fields remain compatible (all existing fields intact).
10. No duplicate Billing IDs or orders introduced.
"""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.billing import BillingEngineClaim, BillingId
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client fixture with overridden database session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def auth_headers():
    """Factory generating Bearer authorization headers for a given User."""
    def _headers(user: User) -> dict:
        token = create_access_token(
            user_id=user.id,
            role=user.role.value,
            phone=user.phone,
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [700]

    def _create(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = referral_code or f"S5API{num:05d}"
        user = User(
            phone=f"97777{num:05d}",
            full_name=f"Step5 User {num}",
            role=role,
            programme=programme,
            account_status=AccountStatus.ACTIVE,
            referral_code=code,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create


@pytest.fixture
def make_address(db_session: Session):
    """Factory creating a delivery address for a user."""
    def _create(user: User) -> Address:
        addr = Address(
            user_id=user.id,
            recipient_name=user.full_name,
            phone=user.phone,
            address_line1="456 Step 5 Boulevard",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
        )
        db_session.add(addr)
        db_session.flush()
        return addr

    return _create


@pytest.fixture
def make_product(db_session: Session):
    """Factory creating products."""
    counter = [10]

    def _create(name: str = "Arya Power Bank 10000mAh", price: Decimal = Decimal("3999.00")) -> Product:
        counter[0] += 1
        num = counter[0]
        prod = Product(
            name=name,
            product_code=f"PB-STEP5-{num}",
            price=price,
            stock=1000,
            is_power_bank=True,
            is_active=True,
        )
        db_session.add(prod)
        db_session.flush()
        return prod

    return _create


def test_successful_1_unit_order_returns_actual_billing_number(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 1: Successful 1-unit order returns actual billing_number from backend."""
    user = make_user(programme=Programme.PLAN_A)
    addr = make_address(user)
    prod = make_product()

    order = Order(
        order_number="ORD-S5-0001",
        idempotency_key="idemp-s5-0001",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=1,
        line_total=Decimal("3999.00"),
    )
    db_session.add(item)
    db_session.flush()

    bid = BillingId(
        billing_number="AGD-000201",
        sequence_number=201,
        order_id=order.id,
        order_item_id=item.id,
        unit_index=0,
        user_id=user.id,
        product_id=prod.id,
        programme=Programme.PLAN_A,
        status="ALLOCATED",
    )
    db_session.add(bid)
    db_session.commit()

    headers = auth_headers(user)

    # 1. GET /api/v1/orders
    resp = client.get("/api/v1/orders", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    order_data = data["items"][0]
    assert order_data["id"] == order.id

    # Check order-level billing_ids
    assert len(order_data["billing_ids"]) == 1
    assert order_data["billing_ids"][0]["billing_number"] == "AGD-000201"
    assert order_data["billing_ids"][0]["unit_index"] == 0

    # Check item-level billing_ids
    assert len(order_data["order_items"]) == 1
    assert len(order_data["order_items"][0]["billing_ids"]) == 1
    assert order_data["order_items"][0]["billing_ids"][0]["billing_number"] == "AGD-000201"
    assert order_data["order_items"][0]["billing_ids"][0]["unit_index"] == 0

    # 2. GET /api/v1/orders/{order_id}
    detail_resp = client.get(f"/api/v1/orders/{order.id}", headers=headers)
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["id"] == order.id
    assert len(detail_data["billing_ids"]) == 1
    assert detail_data["billing_ids"][0]["billing_number"] == "AGD-000201"
    assert len(detail_data["order_items"][0]["billing_ids"]) == 1
    assert detail_data["order_items"][0]["billing_ids"][0]["billing_number"] == "AGD-000201"


def test_multi_unit_order_returns_separate_billing_ids_for_every_unit(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 2: Multi-unit order returns separate Billing IDs for every unit."""
    user = make_user(programme=Programme.PLAN_A)
    addr = make_address(user)
    prod = make_product()

    order = Order(
        order_number="ORD-S5-0002",
        idempotency_key="idemp-s5-0002",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("11997.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=3,
        line_total=Decimal("11997.00"),
    )
    db_session.add(item)
    db_session.flush()

    expected_bids = ["AGD-000301", "AGD-000302", "AGD-000303"]
    for idx, b_num in enumerate(expected_bids):
        bid = BillingId(
            billing_number=b_num,
            sequence_number=301 + idx,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=idx,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(bid)
    db_session.commit()

    headers = auth_headers(user)
    resp = client.get(f"/api/v1/orders/{order.id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Verify item has exactly 3 Billing IDs
    item_bids = data["order_items"][0]["billing_ids"]
    assert len(item_bids) == 3
    numbers = [b["billing_number"] for b in item_bids]
    unit_indices = [b["unit_index"] for b in item_bids]

    assert numbers == expected_bids
    assert unit_indices == [0, 1, 2]
    assert len(set(numbers)) == 3  # All distinct


def test_every_billing_id_belongs_to_correct_order_item(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 3: Every Billing ID belongs to the correct order item (order_item_id match and unit_index)."""
    user = make_user(programme=Programme.PLAN_B)
    addr = make_address(user)
    prod1 = make_product("Arya Power Bank 10000mAh", Decimal("3999.00"))
    prod2 = make_product("Arya Fast Charger 65W", Decimal("1999.00"))

    order = Order(
        order_number="ORD-S5-0003",
        idempotency_key="idemp-s5-0003",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("9997.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order)
    db_session.flush()

    item1 = OrderItem(
        order_id=order.id,
        product_id=prod1.id,
        product_name=prod1.name,
        unit_price=Decimal("3999.00"),
        quantity=2,
        line_total=Decimal("7998.00"),
    )
    item2 = OrderItem(
        order_id=order.id,
        product_id=prod2.id,
        product_name=prod2.name,
        unit_price=Decimal("1999.00"),
        quantity=1,
        line_total=Decimal("1999.00"),
    )
    db_session.add_all([item1, item2])
    db_session.flush()

    # Item 1 has 2 units
    bid1 = BillingId(
        billing_number="AGD-000401",
        sequence_number=401,
        order_id=order.id,
        order_item_id=item1.id,
        unit_index=0,
        user_id=user.id,
        product_id=prod1.id,
        programme=Programme.PLAN_B,
        status="ALLOCATED",
    )
    bid2 = BillingId(
        billing_number="AGD-000402",
        sequence_number=402,
        order_id=order.id,
        order_item_id=item1.id,
        unit_index=1,
        user_id=user.id,
        product_id=prod1.id,
        programme=Programme.PLAN_B,
        status="ALLOCATED",
    )
    # Item 2 has 1 unit
    bid3 = BillingId(
        billing_number="AGD-000403",
        sequence_number=403,
        order_id=order.id,
        order_item_id=item2.id,
        unit_index=0,
        user_id=user.id,
        product_id=prod2.id,
        programme=Programme.PLAN_B,
        status="ALLOCATED",
    )
    db_session.add_all([bid1, bid2, bid3])
    db_session.commit()

    headers = auth_headers(user)
    resp = client.get(f"/api/v1/orders/{order.id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    items = data["order_items"]
    assert len(items) == 2

    # Verify item 1
    resp_item1 = next(it for it in items if it["id"] == item1.id)
    assert len(resp_item1["billing_ids"]) == 2
    for b in resp_item1["billing_ids"]:
        assert b["order_item_id"] == item1.id
    assert resp_item1["billing_ids"][0]["billing_number"] == "AGD-000401"
    assert resp_item1["billing_ids"][0]["unit_index"] == 0
    assert resp_item1["billing_ids"][1]["billing_number"] == "AGD-000402"
    assert resp_item1["billing_ids"][1]["unit_index"] == 1

    # Verify item 2
    resp_item2 = next(it for it in items if it["id"] == item2.id)
    assert len(resp_item2["billing_ids"]) == 1
    assert resp_item2["billing_ids"][0]["order_item_id"] == item2.id
    assert resp_item2["billing_ids"][0]["billing_number"] == "AGD-000403"
    assert resp_item2["billing_ids"][0]["unit_index"] == 0


def test_pending_payment_does_not_expose_unissued_billing_ids(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 4: Pending payment does not expose unissued Billing IDs (returns empty list, no fabrication)."""
    user = make_user(programme=Programme.PLAN_A)
    addr = make_address(user)
    prod = make_product()

    order = Order(
        order_number="ORD-S5-PENDING",
        idempotency_key="idemp-s5-pending",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.PENDING_PAYMENT,
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=1,
        line_total=Decimal("3999.00"),
    )
    db_session.add(item)
    db_session.commit()

    headers = auth_headers(user)
    resp = client.get("/api/v1/orders", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    ord_resp = data["items"][0]

    # Must be empty lists, absolutely no synthetic Billing IDs
    assert ord_resp["billing_ids"] == []
    assert ord_resp["order_items"][0]["billing_ids"] == []


def test_failed_payment_does_not_expose_unissued_billing_ids(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 5: Failed payment does not expose unissued Billing IDs (returns empty list)."""
    user = make_user(programme=Programme.PLAN_B)
    addr = make_address(user)
    prod = make_product()

    order = Order(
        order_number="ORD-S5-FAILED",
        idempotency_key="idemp-s5-failed",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.FAILED,
        payment_status=PaymentStatus.FAILED,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=2,
        line_total=Decimal("7998.00"),
    )
    db_session.add(item)
    db_session.commit()

    headers = auth_headers(user)
    resp = client.get(f"/api/v1/orders/{order.id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["billing_ids"] == []
    assert data["order_items"][0]["billing_ids"] == []


def test_customer_cannot_access_another_customer_order_history(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 6: Customer cannot access another customer's order history (HTTP 404 / ownership filter)."""
    customer_a = make_user(programme=Programme.PLAN_A)
    customer_b = make_user(programme=Programme.PLAN_A)
    addr_a = make_address(customer_a)
    prod = make_product()

    order_a = Order(
        order_number="ORD-CUST-A",
        idempotency_key="idemp-cust-a",
        user_id=customer_a.id,
        address_id=addr_a.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order_a)
    db_session.flush()

    item_a = OrderItem(
        order_id=order_a.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=1,
        line_total=Decimal("3999.00"),
    )
    db_session.add(item_a)
    db_session.flush()

    bid_a = BillingId(
        billing_number="AGD-000501",
        sequence_number=501,
        order_id=order_a.id,
        order_item_id=item_a.id,
        unit_index=0,
        user_id=customer_a.id,
        product_id=prod.id,
        programme=Programme.PLAN_A,
        status="ALLOCATED",
    )
    db_session.add(bid_a)
    db_session.commit()

    # Customer B attempts to list orders
    headers_b = auth_headers(customer_b)
    resp_b_list = client.get("/api/v1/orders", headers=headers_b)
    assert resp_b_list.status_code == 200
    data_b_list = resp_b_list.json()
    assert data_b_list["total"] == 0
    assert data_b_list["items"] == []

    # Customer B attempts to retrieve Customer A's order by ID
    resp_b_detail = client.get(f"/api/v1/orders/{order_a.id}", headers=headers_b)
    assert resp_b_detail.status_code == 404
    assert "not found" in resp_b_detail.json()["detail"].lower()


def test_plan_a_and_plan_b_data_remain_isolated(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 7: Plan A and Plan B order and Billing ID data remain isolated."""
    plan_a_user = make_user(programme=Programme.PLAN_A)
    plan_b_user = make_user(programme=Programme.PLAN_B)
    addr_a = make_address(plan_a_user)
    addr_b = make_address(plan_b_user)
    prod = make_product()

    # Plan A order
    order_a = Order(
        order_number="ORD-PLAN-A",
        idempotency_key="idemp-plan-a",
        user_id=plan_a_user.id,
        address_id=addr_a.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order_a)
    db_session.flush()

    item_a = OrderItem(
        order_id=order_a.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=1,
        line_total=Decimal("3999.00"),
    )
    db_session.add(item_a)
    db_session.flush()

    bid_a = BillingId(
        billing_number="AGD-PLAN-A-01",
        sequence_number=601,
        order_id=order_a.id,
        order_item_id=item_a.id,
        unit_index=0,
        user_id=plan_a_user.id,
        product_id=prod.id,
        programme=Programme.PLAN_A,
        status="ALLOCATED",
    )
    db_session.add(bid_a)

    # Plan B order
    order_b = Order(
        order_number="ORD-PLAN-B",
        idempotency_key="idemp-plan-b",
        user_id=plan_b_user.id,
        address_id=addr_b.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order_b)
    db_session.flush()

    item_b = OrderItem(
        order_id=order_b.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=1,
        line_total=Decimal("3999.00"),
    )
    db_session.add(item_b)
    db_session.flush()

    bid_b = BillingId(
        billing_number="AGD-PLAN-B-01",
        sequence_number=602,
        order_id=order_b.id,
        order_item_id=item_b.id,
        unit_index=0,
        user_id=plan_b_user.id,
        product_id=prod.id,
        programme=Programme.PLAN_B,
        status="ALLOCATED",
    )
    db_session.add(bid_b)
    db_session.commit()

    # Plan A user query
    resp_a = client.get("/api/v1/orders", headers=auth_headers(plan_a_user))
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["total"] == 1
    assert data_a["items"][0]["id"] == order_a.id
    assert data_a["items"][0]["billing_ids"][0]["billing_number"] == "AGD-PLAN-A-01"

    # Plan B user query
    resp_b = client.get("/api/v1/orders", headers=auth_headers(plan_b_user))
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["total"] == 1
    assert data_b["items"][0]["id"] == order_b.id
    assert data_b["items"][0]["billing_ids"][0]["billing_number"] == "AGD-PLAN-B-01"


def test_empty_purchase_history_returns_empty_items_and_zero_total(
    client: TestClient,
    make_user,
    auth_headers,
):
    """Test 8: Empty purchase history returns items: [], total: 0."""
    user = make_user()
    headers = auth_headers(user)
    resp = client.get("/api/v1/orders", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"items": [], "total": 0}


def test_existing_order_response_fields_remain_compatible(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 9: Existing order response fields remain compatible (all existing fields intact)."""
    user = make_user()
    addr = make_address(user)
    prod = make_product()

    order = Order(
        order_number="ORD-S5-COMPAT",
        idempotency_key="idemp-s5-compat",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        payment_reference="PAY-REF-123",
        applied_referral_code="REF123",
        is_first_successful_order=True,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=Decimal("3999.00"),
        quantity=1,
        line_total=Decimal("3999.00"),
    )
    db_session.add(item)
    db_session.commit()

    resp = client.get(f"/api/v1/orders/{order.id}", headers=auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()

    # Required top-level fields
    required_order_fields = [
        "id", "order_number", "idempotency_key", "user_id", "address_id",
        "total_amount", "order_status", "payment_status", "payment_reference",
        "applied_referral_code", "is_first_successful_order", "created_at",
        "updated_at", "order_items", "order_allocation", "address", "billing_ids"
    ]
    for field in required_order_fields:
        assert field in data, f"Missing field '{field}' in OrderResponse"

    assert data["order_number"] == "ORD-S5-COMPAT"
    assert data["payment_reference"] == "PAY-REF-123"
    assert data["applied_referral_code"] == "REF123"
    assert data["is_first_successful_order"] is True

    # Required item fields
    required_item_fields = [
        "id", "product_id", "product_name", "unit_price", "quantity",
        "line_total", "billing_ids"
    ]
    item_data = data["order_items"][0]
    for field in required_item_fields:
        assert field in item_data, f"Missing field '{field}' in OrderItemResponse"


def test_no_duplicate_billing_ids_or_orders_introduced(
    client: TestClient,
    db_session: Session,
    make_user,
    make_address,
    make_product,
    auth_headers,
):
    """Test 10: Multi-item multi-unit order does not introduce duplicate orders or Billing IDs via joinedload."""
    user = make_user()
    addr = make_address(user)
    prod1 = make_product("Arya PB 1", Decimal("3999.00"))
    prod2 = make_product("Arya PB 2", Decimal("3999.00"))

    order = Order(
        order_number="ORD-S5-DEDUP",
        idempotency_key="idemp-s5-dedup",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("15996.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db_session.add(order)
    db_session.flush()

    item1 = OrderItem(
        order_id=order.id,
        product_id=prod1.id,
        product_name=prod1.name,
        unit_price=Decimal("3999.00"),
        quantity=2,
        line_total=Decimal("7998.00"),
    )
    item2 = OrderItem(
        order_id=order.id,
        product_id=prod2.id,
        product_name=prod2.name,
        unit_price=Decimal("3999.00"),
        quantity=2,
        line_total=Decimal("7998.00"),
    )
    db_session.add_all([item1, item2])
    db_session.flush()

    # 4 distinct billing IDs
    bids = [
        BillingId(
            billing_number=f"AGD-DEDUP-{i}",
            sequence_number=700 + i,
            order_id=order.id,
            order_item_id=item1.id if i <= 2 else item2.id,
            unit_index=0 if i in (1, 3) else 1,
            user_id=user.id,
            product_id=prod1.id if i <= 2 else prod2.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        for i in range(1, 5)
    ]
    db_session.add_all(bids)
    db_session.commit()

    resp = client.get("/api/v1/orders", headers=auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()

    # Check order list has exactly 1 order, not duplicated by cartesian product
    assert data["total"] == 1
    assert len(data["items"]) == 1

    ord_resp = data["items"][0]
    # Check order-level billing_ids has exactly 4 distinct items
    order_b_nums = [b["billing_number"] for b in ord_resp["billing_ids"]]
    assert len(order_b_nums) == 4
    assert len(set(order_b_nums)) == 4

    # Check item 1 has exactly 2 distinct billing IDs
    item1_data = next(it for it in ord_resp["order_items"] if it["id"] == item1.id)
    item1_b_nums = [b["billing_number"] for b in item1_data["billing_ids"]]
    assert len(item1_b_nums) == 2
    assert len(set(item1_b_nums)) == 2

    # Check item 2 has exactly 2 distinct billing IDs
    item2_data = next(it for it in ord_resp["order_items"] if it["id"] == item2.id)
    item2_b_nums = [b["billing_number"] for b in item2_data["billing_ids"]]
    assert len(item2_b_nums) == 2
    assert len(set(item2_b_nums)) == 2
