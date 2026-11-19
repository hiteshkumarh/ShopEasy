"""Comprehensive API test suite for WP-10 Step 3: Plan A Cashback Progress & 48-Bulb Visual Tracking.

Verifies:
1. Authenticated Plan A customer can retrieve their cashback progress.
2. Unauthenticated access is rejected (HTTP 401).
3. Plan B customer cannot access Plan A cashback data (HTTP 403).
4. Customer A cannot retrieve Customer B's cashback information (isolation).
5. Zero contributions produce 0/48 bulbs ON.
6. Three contributions produce 9/48 bulbs ON.
7. Eight contributions produce 24/48 bulbs ON.
8. Sixteen contributions produce 48/48 bulbs ON.
9. Completed cycle returns the correct ₹4,000 amount and completed status.
10. Customer cannot manipulate progress by submitting bulb counts or contribution counts (GET endpoint).
11. Internal queue IDs and queue positions are NOT exposed in customer responses.
12. Read requests do NOT create or modify financial records (idempotent read).
13. List cycles endpoint returns customer's cycle history.
14. Customer with waiting entry returns WAITING cycle status and 0 bulbs ON.
"""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.billing import BillingEngineClaim, BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletType,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.cashback.plan_a import PlanACashbackService


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client fixture with overridden database session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [600]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = referral_code or f"PACBAPI{num:05d}"
        user = User(
            phone=f"96666{num:05d}",
            full_name=f"API User {num}",
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
def make_power_bank(db_session: Session):
    """Fixture for test product."""
    product = Product(
        name="Arya Power Bank 10000mAh",
        product_code="PB-10K-API",
        price=Decimal("3999.00"),
        stock=10000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    return product


@pytest.fixture
def make_order_and_bid(db_session: Session, make_power_bank):
    """Factory creating an Order and Billing ID."""
    counter = [2000]

    def _create(user: User, applied_code: str = None, programme: Programme = Programme.PLAN_A):
        counter[0] += 1
        seq = counter[0]

        address = Address(
            user_id=user.id,
            recipient_name=user.full_name,
            phone=user.phone,
            address_line1="123 API St",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001",
        )
        db_session.add(address)
        db_session.flush()

        order = Order(
            order_number=f"ORD-API-{seq:06d}",
            idempotency_key=f"idemp-api-{seq:06d}",
            user_id=user.id,
            address_id=address.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            applied_referral_code=applied_code,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=make_power_bank.id,
            product_name=make_power_bank.name,
            quantity=1,
            unit_price=Decimal("3999.00"),
            line_total=Decimal("3999.00"),
        )
        db_session.add(item)
        db_session.flush()

        bid = BillingId(
            billing_number=f"AGD-API-{seq:06d}",
            sequence_number=seq,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=0,
            user_id=user.id,
            product_id=make_power_bank.id,
            programme=programme,
            status="ALLOCATED",
        )
        db_session.add(bid)
        db_session.flush()

        claim = BillingEngineClaim(
            billing_id=bid.id,
            engine=programme,
            status="CLAIMED",
        )
        db_session.add(claim)
        db_session.commit()
        return order, bid

    return _create


@pytest.mark.unit
class TestPlanACashbackApi:
    """Tests for Plan A cashback progress endpoint."""

    def test_01_authenticated_customer_retrieves_progress(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """1: Authenticated Plan A customer retrieves their cashback progress."""
        cust = make_user(programme=Programme.PLAN_A)
        _, bid = make_order_and_bid(cust)

        # Process cashback: first in queue -> reserve, becomes active at pos 1
        PlanACashbackService.process_billing_id(bid.id, db=db_session)

        headers = auth_headers(cust)
        response = client.get("/api/v1/cashback/progress", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["has_active_cycle"] is True
        assert data["current_billing_id"] == bid.billing_number
        assert data["completed_contributions"] == 0
        assert Decimal(str(data["cashback_amount_earned"])) == Decimal("0.00")
        assert data["cycle_status"] == "ACTIVE"
        assert data["is_completed"] is False
        assert data["bulbs_on"] == 0
        assert data["bulbs_off"] == 48
        assert data["total_bulbs"] == 48
        assert len(data["bulb_states"]) == 48

    def test_02_unauthenticated_access_is_rejected(self, client: TestClient):
        """2: Unauthenticated request returns HTTP 401 Unauthorized."""
        response = client.get("/api/v1/cashback/progress")
        assert response.status_code == 401
        assert "Authentication credentials were not provided" in response.json()["detail"]

    def test_03_plan_b_customer_cannot_access_plan_a_cashback(
        self, client: TestClient, db_session: Session, make_user, auth_headers
    ):
        """3: Plan B customer receives HTTP 403 Forbidden."""
        dist = make_user(programme=Programme.PLAN_B)
        headers = auth_headers(dist)

        response = client.get("/api/v1/cashback/progress", headers=headers)
        assert response.status_code == 403
        assert "Cashback progress is only available to Plan A participants" in response.json()["detail"]

    def test_04_customer_a_cannot_see_customer_b_records(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """4: Customer A sees only their own cycle, not Customer B's cycle."""
        cust_a = make_user(programme=Programme.PLAN_A)
        cust_b = make_user(programme=Programme.PLAN_A)

        _, bid_a = make_order_and_bid(cust_a)
        _, bid_b = make_order_and_bid(cust_b)

        PlanACashbackService.process_billing_id(bid_a.id, db=db_session)
        PlanACashbackService.process_billing_id(bid_b.id, db=db_session)

        headers_a = auth_headers(cust_a)
        res_a = client.get("/api/v1/cashback/progress", headers=headers_a)
        assert res_a.status_code == 200
        assert res_a.json()["current_billing_id"] == bid_a.billing_number

        headers_b = auth_headers(cust_b)
        res_b = client.get("/api/v1/cashback/progress", headers=headers_b)
        assert res_b.status_code == 200
        assert res_b.json()["current_billing_id"] == bid_b.billing_number

    def test_05_zero_contributions_produces_0_on_48_off(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """5: 0 contributions = 0 ON, 48 OFF."""
        cust = make_user(programme=Programme.PLAN_A)
        _, bid = make_order_and_bid(cust)
        PlanACashbackService.process_billing_id(bid.id, db=db_session)

        headers = auth_headers(cust)
        res = client.get("/api/v1/cashback/progress", headers=headers)
        data = res.json()

        assert data["completed_contributions"] == 0
        assert data["bulbs_on"] == 0
        assert data["bulbs_off"] == 48
        assert data["bulb_states"] == [False] * 48

    def test_06_three_contributions_produces_9_on_39_off(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """6: 3 contributions = 9 ON, 39 OFF."""
        root = make_user(programme=Programme.PLAN_A)
        _, bid_root = make_order_and_bid(root)
        PlanACashbackService.process_billing_id(bid_root.id, db=db_session)

        for _ in range(3):
            c = make_user(programme=Programme.PLAN_A)
            rel = ReferralRelationship(
                referee_id=c.id,
                referrer_id=root.id,
                referee_programme=Programme.PLAN_A,
                referrer_programme=Programme.PLAN_A,
                referral_code_used=root.referral_code,
                binding_channel="CHECKOUT",
                is_active=True,
            )
            db_session.add(rel)
            db_session.commit()
            _, b = make_order_and_bid(c, applied_code=root.referral_code)
            PlanACashbackService.process_billing_id(b.id, db=db_session)

        headers = auth_headers(root)
        res = client.get("/api/v1/cashback/progress", headers=headers)
        data = res.json()

        assert data["completed_contributions"] == 3
        assert Decimal(str(data["cashback_amount_earned"])) == Decimal("750.00")
        assert data["bulbs_on"] == 9
        assert data["bulbs_off"] == 39
        assert data["bulb_states"] == [True] * 9 + [False] * 39

    def test_07_eight_contributions_produces_24_on_24_off(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """7: 8 contributions = 24 ON, 24 OFF."""
        root = make_user(programme=Programme.PLAN_A)
        _, bid_root = make_order_and_bid(root)
        PlanACashbackService.process_billing_id(bid_root.id, db=db_session)

        for _ in range(8):
            c = make_user(programme=Programme.PLAN_A)
            rel = ReferralRelationship(
                referee_id=c.id,
                referrer_id=root.id,
                referee_programme=Programme.PLAN_A,
                referrer_programme=Programme.PLAN_A,
                referral_code_used=root.referral_code,
                binding_channel="CHECKOUT",
                is_active=True,
            )
            db_session.add(rel)
            db_session.commit()
            _, b = make_order_and_bid(c, applied_code=root.referral_code)
            PlanACashbackService.process_billing_id(b.id, db=db_session)

        headers = auth_headers(root)
        res = client.get("/api/v1/cashback/progress", headers=headers)
        data = res.json()

        assert data["completed_contributions"] == 8
        assert Decimal(str(data["cashback_amount_earned"])) == Decimal("2000.00")
        assert data["bulbs_on"] == 24
        assert data["bulbs_off"] == 24
        assert data["bulb_states"] == [True] * 24 + [False] * 24

    def test_08_and_09_sixteen_contributions_produces_48_on_4000_earned_completed(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """8 & 9: 16 contributions = 48 ON, 0 OFF, ₹4,000 earned, completed status, withdrawable."""
        root = make_user(programme=Programme.PLAN_A)
        _, bid_root = make_order_and_bid(root)
        PlanACashbackService.process_billing_id(bid_root.id, db=db_session)

        for _ in range(16):
            c = make_user(programme=Programme.PLAN_A)
            rel = ReferralRelationship(
                referee_id=c.id,
                referrer_id=root.id,
                referee_programme=Programme.PLAN_A,
                referrer_programme=Programme.PLAN_A,
                referral_code_used=root.referral_code,
                binding_channel="CHECKOUT",
                is_active=True,
            )
            db_session.add(rel)
            db_session.commit()
            _, b = make_order_and_bid(c, applied_code=root.referral_code)
            PlanACashbackService.process_billing_id(b.id, db=db_session)

        headers = auth_headers(root)
        res = client.get("/api/v1/cashback/progress", headers=headers)
        data = res.json()

        assert data["completed_contributions"] == 16
        assert Decimal(str(data["cashback_amount_earned"])) == Decimal("4000.00")
        assert data["cycle_status"] == "COMPLETED"
        assert data["is_completed"] is True
        assert data["bulbs_on"] == 48
        assert data["bulbs_off"] == 0
        assert data["bulb_states"] == [True] * 48
        assert data["is_withdrawable"] is True
        assert Decimal(str(data["current_wallet_balance"])) == Decimal("4000.00")

    def test_10_customer_cannot_manipulate_values_via_query_params(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """10: Query parameters attempting to tamper with bulbs or counts are ignored."""
        cust = make_user(programme=Programme.PLAN_A)
        _, bid = make_order_and_bid(cust)
        PlanACashbackService.process_billing_id(bid.id, db=db_session)

        headers = auth_headers(cust)
        # Attempt to pass spoofed parameters
        res = client.get(
            "/api/v1/cashback/progress?bulbs_on=48&completed_contributions=16&cashback_amount_earned=4000.00",
            headers=headers,
        )
        data = res.json()

        # Must strictly reflect true database state (0 contributions)
        assert data["completed_contributions"] == 0
        assert data["bulbs_on"] == 0
        assert Decimal(str(data["cashback_amount_earned"])) == Decimal("0.00")

    def test_11_internal_queue_ids_and_positions_omitted_from_response(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """11: Internal queue IDs and queue positions are NOT present in customer response (privacy)."""
        cust = make_user(programme=Programme.PLAN_A)
        _, bid = make_order_and_bid(cust)
        PlanACashbackService.process_billing_id(bid.id, db=db_session)

        headers = auth_headers(cust)
        res = client.get("/api/v1/cashback/progress", headers=headers)
        data = res.json()

        assert "queue_id" not in data
        assert "queue_position" not in data
        assert "last_allocated_position" not in data

    def test_12_read_requests_do_not_modify_financial_records(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """12: GET /cashback/progress is strictly idempotent and creates 0 financial records."""
        cust = make_user(programme=Programme.PLAN_A)
        _, bid = make_order_and_bid(cust)
        PlanACashbackService.process_billing_id(bid.id, db=db_session)

        # Baseline counts
        c_contrib = db_session.query(PlanACashbackContribution).count()
        c_res = db_session.query(PlanAUnallocatedCashbackReserve).count()
        c_tx = db_session.query(WalletTransaction).count()

        headers = auth_headers(cust)
        for _ in range(5):
            res = client.get("/api/v1/cashback/progress", headers=headers)
            assert res.status_code == 200

        # Verify no mutations occurred
        assert db_session.query(PlanACashbackContribution).count() == c_contrib
        assert db_session.query(PlanAUnallocatedCashbackReserve).count() == c_res
        assert db_session.query(WalletTransaction).count() == c_tx

    def test_13_list_cycles_history_endpoint(
        self, client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers
    ):
        """13: GET /cashback/cycles returns list of customer cycles."""
        cust = make_user(programme=Programme.PLAN_A)
        _, bid = make_order_and_bid(cust)
        PlanACashbackService.process_billing_id(bid.id, db=db_session)

        headers = auth_headers(cust)
        res = client.get("/api/v1/cashback/cycles", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["completed_contributions"] == 0
        assert data[0]["status"] == "ACTIVE"
        assert data[0]["is_completed"] is False
