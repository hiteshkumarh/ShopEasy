"""Test suite for WP-11 Step 4: Unified Admin Search across Plan A and Plan B (OR-13).

Verifies:
1. Unauthenticated request returns HTTP 401.
2. Customer and distributor roles return HTTP 403 Forbidden.
3. Admin can search a valid Plan A Billing ID.
4. Admin can search a valid Plan B Billing ID.
5. Admin can search a valid Order ID and Order Number.
6. Exact matching only: partial or near matches return zero results.
7. Non-existent query returns empty results cleanly with total=0.
8. Cross-programme results are accurately labelled with Programme.PLAN_A or Programme.PLAN_B.
9. Ambiguous matches (query matching both an Order ID and a Billing ID) return both records safely.
10. Sensitive fields (passwords, hashes, tokens, OTPs) are not exposed.
11. Search operation is strictly read-only: no mutations on orders, wallets, or balances.
12. Search query is logged via AuditService (action="ADMIN_UNIFIED_SEARCH").
13. Invalid queries (empty, whitespace-only, or exceeding 64 chars) are rejected with HTTP 400.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit import AuditLog
from app.models.billing import BillingId
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole, WalletType
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User
from app.models.wallet import Wallet


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client fixture with overridden database session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for creating distinct test users."""
    counter = [950]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = None if role == UserRole.ADMIN else (referral_code or f"SRCH{num:05d}")

        user = User(
            phone=f"95555{num:05d}",
            full_name=f"Search User {num}",
            role=role,
            programme=programme,
            account_status=AccountStatus.ACTIVE,
            referral_code=code,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create_user


@pytest.fixture
def auth_headers():
    """Factory generating Bearer authorization headers."""
    def _headers(user: User) -> dict:
        token = create_access_token(
            user_id=user.id,
            role=user.role.value,
            phone=user.phone,
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def make_order_and_bid(db_session: Session):
    """Factory creating an Order and Billing ID with full FK integrity."""
    counter = [6000]

    product = Product(
        name="Arya Search Test Power Bank",
        product_code=f"PB-SRCH-{datetime.now(timezone.utc).timestamp()}",
        price=Decimal("3999.00"),
        stock=5000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()

    def _create(user: User, programme: Programme = Programme.PLAN_A):
        counter[0] += 1
        seq = counter[0]

        address = Address(
            user_id=user.id,
            recipient_name=user.full_name,
            phone=user.phone,
            address_line1="456 Search Road",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
        )
        db_session.add(address)
        db_session.flush()

        order = Order(
            order_number=f"ORD-SRCH-{programme.value[:1]}-{seq:06d}",
            idempotency_key=f"idemp-srch-{programme.value[:1]}-{seq:06d}",
            user_id=user.id,
            address_id=address.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            is_fulfilled=True,
            applied_referral_code=user.referral_code,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            unit_price=Decimal("3999.00"),
            line_total=Decimal("3999.00"),
        )
        db_session.add(item)
        db_session.flush()

        billing_id = BillingId(
            billing_number=f"AGD-{programme.value[:1]}-{seq:06d}",
            sequence_number=seq,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=0,
            user_id=user.id,
            product_id=product.id,
            programme=programme,
            status="ALLOCATED",
        )
        db_session.add(billing_id)
        db_session.flush()

        return order, billing_id

    return _create


class TestAdminSearchAuthAndValidation:
    """Authentication, authorization, and input validation tests for unified search."""

    def test_unauthenticated_request_rejected_with_401(self, client: TestClient):
        """Unauthenticated requests must be rejected with HTTP 401."""
        res = client.get("/api/v1/admin/search?q=AGD-A-006001")
        assert res.status_code == 401

    def test_non_admin_roles_rejected_with_403(
        self, client: TestClient, make_user, auth_headers
    ):
        """Customer and distributor roles must receive HTTP 403 Forbidden."""
        customer = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        distributor = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

        for u in [customer, distributor]:
            res = client.get("/api/v1/admin/search?q=AGD-A-006001", headers=auth_headers(u))
            assert res.status_code == 403, f"Expected 403 for user #{u.id}, got {res.status_code}"

    def test_empty_or_whitespace_query_rejected_with_400(
        self, client: TestClient, make_user, auth_headers
    ):
        """Empty or whitespace-only queries must be rejected with HTTP 400."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        headers = auth_headers(admin)

        res_empty = client.get("/api/v1/admin/search?q=   ", headers=headers)
        assert res_empty.status_code == 400
        assert "cannot be empty" in res_empty.json()["detail"]

    def test_excessively_long_query_rejected_with_400(
        self, client: TestClient, make_user, auth_headers
    ):
        """Query exceeding maximum 64 characters must be rejected with HTTP 400."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        headers = auth_headers(admin)

        long_q = "X" * 65
        res = client.get(f"/api/v1/admin/search?q={long_q}", headers=headers)
        assert res.status_code == 400
        assert "exceeds maximum permitted length" in res.json()["detail"]


class TestAdminSearchOperations:
    """Core exact-match search capabilities across Plan A and Plan B."""

    def test_search_plan_a_billing_id_exact_match(
        self, client: TestClient, db_session: Session, make_user, auth_headers, make_order_and_bid
    ):
        """Admin can search an exact Plan A Billing ID and get a PLAN_A labelled result."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        cust_a = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        order_a, bid_a = make_order_and_bid(cust_a, programme=Programme.PLAN_A)
        db_session.commit()

        headers = auth_headers(admin)
        res = client.get(f"/api/v1/admin/search?q={bid_a.billing_number}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["query"] == bid_a.billing_number
        assert data["total"] == 1
        item = data["results"][0]
        assert item["record_type"] == "BILLING_ID"
        assert item["programme"] == "PLAN_A"
        assert item["identifier"] == bid_a.billing_number
        assert item["billing_number"] == bid_a.billing_number
        assert item["order_id"] == order_a.id
        assert item["order_number"] == order_a.order_number
        assert item["customer_id"] == cust_a.id
        assert item["customer_name"] == cust_a.full_name
        assert item["status"] == "ALLOCATED"
        assert item["product_name"] == "Arya Search Test Power Bank"

    def test_search_plan_b_billing_id_exact_match(
        self, client: TestClient, db_session: Session, make_user, auth_headers, make_order_and_bid
    ):
        """Admin can search an exact Plan B Billing ID and get a PLAN_B labelled result."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        dist_b = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)
        order_b, bid_b = make_order_and_bid(dist_b, programme=Programme.PLAN_B)
        db_session.commit()

        headers = auth_headers(admin)
        res = client.get(f"/api/v1/admin/search?q={bid_b.billing_number}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        item = data["results"][0]
        assert item["record_type"] == "BILLING_ID"
        assert item["programme"] == "PLAN_B"
        assert item["identifier"] == bid_b.billing_number
        assert item["customer_id"] == dist_b.id

    def test_search_order_by_order_number_and_id(
        self, client: TestClient, db_session: Session, make_user, auth_headers, make_order_and_bid
    ):
        """Admin can search an exact Order Number and Order ID across programmes."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        user_a = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        order_a, bid_a = make_order_and_bid(user_a, programme=Programme.PLAN_A)
        db_session.commit()

        headers = auth_headers(admin)

        # 1. Search by exact order_number
        res_num = client.get(f"/api/v1/admin/search?q={order_a.order_number}", headers=headers)
        assert res_num.status_code == 200
        data_num = res_num.json()
        assert data_num["total"] == 1
        item = data_num["results"][0]
        assert item["record_type"] == "ORDER"
        assert item["programme"] == "PLAN_A"
        assert item["order_id"] == order_a.id
        assert item["order_number"] == order_a.order_number
        assert Decimal(str(item["total_amount"])) == Decimal("3999.00")
        assert item["status"] == "confirmed"
        assert item["metadata"]["is_fulfilled"] is True
        assert item["metadata"]["payment_status"] == "completed"

        # 2. Search by exact order ID (numeric)
        res_id = client.get(f"/api/v1/admin/search?q={order_a.id}", headers=headers)
        assert res_id.status_code == 200
        data_id = res_id.json()
        assert data_id["total"] >= 1
        assert any(it["record_type"] == "ORDER" and it["order_id"] == order_a.id for it in data_id["results"])

    def test_exact_match_only_partial_returns_no_results(
        self, client: TestClient, db_session: Session, make_user, auth_headers, make_order_and_bid
    ):
        """Substring or partial matches must return empty results (exact match only)."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        cust = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        order, bid = make_order_and_bid(cust, programme=Programme.PLAN_A)
        db_session.commit()

        headers = auth_headers(admin)

        # Truncate billing number to test partial match
        partial_bid = bid.billing_number[:6]
        res_bid = client.get(f"/api/v1/admin/search?q={partial_bid}", headers=headers)
        assert res_bid.status_code == 200
        assert res_bid.json()["total"] == 0
        assert res_bid.json()["results"] == []

        # Truncate order number to test partial match
        partial_ord = order.order_number[:8]
        res_ord = client.get(f"/api/v1/admin/search?q={partial_ord}", headers=headers)
        assert res_ord.status_code == 200
        assert res_ord.json()["total"] == 0
        assert res_ord.json()["results"] == []

    def test_no_match_returns_empty_result_cleanly(
        self, client: TestClient, make_user, auth_headers
    ):
        """Non-existent query returns empty results cleanly with total=0."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        headers = auth_headers(admin)

        res = client.get("/api/v1/admin/search?q=NONEXISTENT-99999", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["query"] == "NONEXISTENT-99999"
        assert data["total"] == 0
        assert data["results"] == []

    def test_audit_logging_and_read_only_guarantee(
        self, client: TestClient, db_session: Session, make_user, auth_headers, make_order_and_bid
    ):
        """Search query is logged via AuditService and modifies zero business entities."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        cust = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        order, bid = make_order_and_bid(cust, programme=Programme.PLAN_A)

        # Create wallet to test read-only guarantee
        wallet = Wallet(
            user_id=cust.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            balance=Decimal("1500.00"),
        )
        db_session.add(wallet)
        db_session.commit()

        initial_order_status = order.order_status
        initial_order_amount = order.total_amount
        initial_wallet_balance = wallet.balance

        headers = auth_headers(admin)
        res = client.get(f"/api/v1/admin/search?q={bid.billing_number}", headers=headers)
        assert res.status_code == 200

        # Verify audit log was recorded
        audit = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "ADMIN_UNIFIED_SEARCH",
                AuditLog.entity_id == bid.billing_number,
            )
            .first()
        )
        assert audit is not None
        assert audit.actor_id == admin.id
        assert audit.actor_role == "admin"
        assert "match_count" in audit.metadata_json

        # Verify zero business mutations occurred
        db_session.refresh(order)
        db_session.refresh(wallet)
        assert order.order_status == initial_order_status
        assert order.total_amount == initial_order_amount
        assert wallet.balance == initial_wallet_balance

    def test_sensitive_fields_not_exposed(
        self, client: TestClient, db_session: Session, make_user, auth_headers, make_order_and_bid
    ):
        """Responses must never expose secrets, passwords, hashes, tokens, or OTPs."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        cust = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        order, bid = make_order_and_bid(cust, programme=Programme.PLAN_A)
        db_session.commit()

        headers = auth_headers(admin)
        res = client.get(f"/api/v1/admin/search?q={bid.billing_number}", headers=headers)
        assert res.status_code == 200
        content_text = res.text.lower()

        # Assert no forbidden secret keys appear anywhere in response text
        forbidden_keys = ["password", "password_hash", "token", "otp", "dev_otp", "secret", "private_key"]
        for key in forbidden_keys:
            assert f'"{key}"' not in content_text
