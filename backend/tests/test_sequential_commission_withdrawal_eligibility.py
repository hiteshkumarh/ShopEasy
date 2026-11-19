"""Comprehensive test suite for Sequential Commission Wallet Withdrawal Eligibility.

Verifies:
1. 0/16 contributions: 0/48 bulbs; withdrawal disabled.
2. 1/16 contributions: 3/48 bulbs; withdrawal disabled.
3. 8/16 contributions: 24/48 bulbs; withdrawal disabled.
4. 15/16 contributions: 45/48 bulbs; withdrawal disabled.
5. 16/16 contributions and ₹4,000 available: 48/48 bulbs; withdrawal enabled.
6. Completed cycle but insufficient available balance (e.g. ₹0): withdrawal rejected.
7. Repeated withdrawal requests: idempotent return, zero duplicate debit.
8. Customer cannot withdraw another customer's balance (isolation).
"""

from decimal import Decimal
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.billing import BillingEngineClaim, BillingId
from app.models.cashback import (
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
)
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletType,
    WithdrawalStatus,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User
from app.models.wallet import Wallet, Withdrawal
from app.services.wallet_service import (
    execute_simulated_withdrawal,
    get_or_create_wallet,
)


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
    counter = [900]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = referral_code or f"PAWD{num:05d}"
        user = User(
            phone=f"97777{num:05d}",
            full_name=f"Withdrawal User {num}",
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
def make_cycle_setup(db_session: Session):
    """Factory to create a Plan A queue, entry, billing ID, and cycle."""
    bid_seq = [500]

    def _create_setup(
        user: User,
        contributions: int = 0,
        cycle_status: str = "ACTIVE",
        wallet_balance: Decimal = Decimal("0.00"),
    ):
        bid_seq[0] += 1
        seq = bid_seq[0]

        addr = Address(
            user_id=user.id,
            recipient_name=user.full_name,
            phone=user.phone,
            address_line1="123 Test St",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
        )
        db_session.add(addr)
        db_session.flush()

        prod = Product(
            name="Power Bank Test",
            product_code=f"PB-WD-{seq}",
            price=Decimal("2000.00"),
            stock=100,
            is_active=True,
            is_power_bank=True,
        )
        db_session.add(prod)
        db_session.flush()

        order = Order(
            user_id=user.id,
            order_number=f"ORD-WD-{seq}",
            total_amount=Decimal("2000.00"),
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            address_id=addr.id,
            idempotency_key=f"IK-WD-{seq}",
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            product_name=prod.name,
            quantity=1,
            unit_price=Decimal("2000.00"),
            line_total=Decimal("2000.00"),
        )
        db_session.add(item)
        db_session.flush()

        bid = BillingId(
            billing_number=f"AGD-WD-{seq:06d}",
            order_id=order.id,
            order_item_id=item.id,
            unit_index=1,
            product_id=prod.id,
            user_id=user.id,
            sequence_number=seq,
            programme=Programme.PLAN_A,
        )
        db_session.add(bid)
        db_session.flush()

        claim = BillingEngineClaim(
            billing_id=bid.id,
            engine=Programme.PLAN_A,
            status="CLAIMED",
        )
        db_session.add(claim)
        db_session.flush()

        queue = PlanACashbackQueue(
            root_user_id=user.id,
            last_allocated_position=1,
        )
        db_session.add(queue)
        db_session.flush()

        entry = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=user.id,
            billing_id=bid.id,
            queue_position=1,
            status=cycle_status,
        )
        db_session.add(entry)
        db_session.flush()

        cycle = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry.id,
            recipient_user_id=user.id,
            recipient_billing_id=bid.id,
            cycle_number=1,
            completed_contributions=contributions,
            total_earned=Decimal("250.00") * contributions,
            status=cycle_status,
        )
        db_session.add(cycle)
        db_session.flush()

        queue.active_cycle_id = cycle.id if cycle_status == "ACTIVE" else None

        wallet = get_or_create_wallet(db_session, user_id=user.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION)
        wallet.balance = wallet_balance
        db_session.flush()

        return queue, entry, cycle, wallet

    return _create_setup


def test_01_zero_contributions_disabled(client: TestClient, make_user, make_cycle_setup):
    """Case 1: 0/16 contributions: 0/48 bulbs; withdrawal disabled."""
    user = make_user()
    make_cycle_setup(user=user, contributions=0, cycle_status="ACTIVE", wallet_balance=Decimal("0.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    # 1. Cashback Progress
    cb_resp = client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {token}"})
    assert cb_resp.status_code == status.HTTP_200_OK
    cb_data = cb_resp.json()
    assert cb_data["completed_contributions"] == 0
    assert cb_data["bulbs_on"] == 0
    assert cb_data["bulbs_off"] == 48
    assert cb_data["is_withdrawable"] is False

    # 2. Dashboard Earnings
    dash_resp = client.get("/api/v1/dashboard/earnings", headers={"Authorization": f"Bearer {token}"})
    assert dash_resp.status_code == status.HTTP_200_OK
    dash_data = dash_resp.json()
    assert dash_data["sequential_progress"]["completed_commissions"] == 0
    assert dash_data["withdrawal_eligibility"]["sequential_commission_eligible"] is False

    # 3. Direct Withdrawal Attempt
    wd_resp = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-FAIL-01"},
    )
    assert wd_resp.status_code == status.HTTP_400_BAD_REQUEST


def test_02_one_contribution_disabled(client: TestClient, make_user, make_cycle_setup):
    """Case 2: 1/16 contributions: 3/48 bulbs; withdrawal disabled."""
    user = make_user()
    make_cycle_setup(user=user, contributions=1, cycle_status="ACTIVE", wallet_balance=Decimal("0.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    cb_resp = client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {token}"})
    assert cb_resp.status_code == status.HTTP_200_OK
    cb_data = cb_resp.json()
    assert cb_data["completed_contributions"] == 1
    assert cb_data["bulbs_on"] == 3
    assert cb_data["bulbs_off"] == 45
    assert cb_data["is_withdrawable"] is False

    dash_resp = client.get("/api/v1/dashboard/earnings", headers={"Authorization": f"Bearer {token}"})
    assert dash_resp.status_code == status.HTTP_200_OK
    dash_data = dash_resp.json()
    assert dash_data["sequential_progress"]["completed_commissions"] == 1
    assert dash_data["withdrawal_eligibility"]["sequential_commission_eligible"] is False


def test_03_eight_contributions_disabled(client: TestClient, make_user, make_cycle_setup):
    """Case 3: 8/16 contributions: 24/48 bulbs; withdrawal disabled."""
    user = make_user()
    make_cycle_setup(user=user, contributions=8, cycle_status="ACTIVE", wallet_balance=Decimal("0.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    cb_resp = client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {token}"})
    assert cb_resp.status_code == status.HTTP_200_OK
    cb_data = cb_resp.json()
    assert cb_data["completed_contributions"] == 8
    assert cb_data["bulbs_on"] == 24
    assert cb_data["bulbs_off"] == 24
    assert cb_data["is_withdrawable"] is False

    dash_resp = client.get("/api/v1/dashboard/earnings", headers={"Authorization": f"Bearer {token}"})
    assert dash_resp.status_code == status.HTTP_200_OK
    dash_data = dash_resp.json()
    assert dash_data["sequential_progress"]["completed_commissions"] == 8
    assert dash_data["withdrawal_eligibility"]["sequential_commission_eligible"] is False


def test_04_fifteen_contributions_disabled(client: TestClient, make_user, make_cycle_setup):
    """Case 4: 15/16 contributions: 45/48 bulbs; withdrawal disabled."""
    user = make_user()
    make_cycle_setup(user=user, contributions=15, cycle_status="ACTIVE", wallet_balance=Decimal("0.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    cb_resp = client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {token}"})
    assert cb_resp.status_code == status.HTTP_200_OK
    cb_data = cb_resp.json()
    assert cb_data["completed_contributions"] == 15
    assert cb_data["bulbs_on"] == 45
    assert cb_data["bulbs_off"] == 3
    assert cb_data["is_withdrawable"] is False

    dash_resp = client.get("/api/v1/dashboard/earnings", headers={"Authorization": f"Bearer {token}"})
    assert dash_resp.status_code == status.HTTP_200_OK
    dash_data = dash_resp.json()
    assert dash_data["sequential_progress"]["completed_commissions"] == 15
    assert dash_data["withdrawal_eligibility"]["sequential_commission_eligible"] is False


def test_05_sixteen_contributions_enabled_and_withdrawal(client: TestClient, make_user, make_cycle_setup):
    """Case 5: 16/16 contributions and ₹4,000 available: 48/48 bulbs; withdrawal enabled and executable."""
    user = make_user()
    make_cycle_setup(user=user, contributions=16, cycle_status="COMPLETED", wallet_balance=Decimal("4000.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    # 1. Cashback Progress
    cb_resp = client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {token}"})
    assert cb_resp.status_code == status.HTTP_200_OK
    cb_data = cb_resp.json()
    assert cb_data["completed_contributions"] == 16
    assert cb_data["bulbs_on"] == 48
    assert cb_data["bulbs_off"] == 0
    assert cb_data["is_completed"] is True
    assert cb_data["is_withdrawable"] is True
    assert Decimal(str(cb_data["current_wallet_balance"])) == Decimal("4000.00")

    # 2. Dashboard Earnings
    dash_resp = client.get("/api/v1/dashboard/earnings", headers={"Authorization": f"Bearer {token}"})
    assert dash_resp.status_code == status.HTTP_200_OK
    dash_data = dash_resp.json()
    assert dash_data["sequential_progress"]["completed_commissions"] == 16
    assert dash_data["sequential_progress"]["status"] == "completed"
    assert dash_data["withdrawal_eligibility"]["sequential_commission_eligible"] is True

    # 3. Execute Simulated Withdrawal
    wd_resp = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-SUCCESS-05"},
    )
    assert wd_resp.status_code == status.HTTP_200_OK
    wd_data = wd_resp.json()
    assert Decimal(str(wd_data["amount"])) == Decimal("4000.00")
    assert wd_data["status"].lower() == "completed"


def test_06_completed_cycle_zero_balance_disabled(client: TestClient, make_user, make_cycle_setup):
    """Case 6: Completed cycle but insufficient available balance (e.g. ₹0): withdrawal rejected."""
    user = make_user()
    make_cycle_setup(user=user, contributions=16, cycle_status="COMPLETED", wallet_balance=Decimal("0.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    # Cashback progress shows cycle completed, but not withdrawable due to balance 0
    cb_resp = client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {token}"})
    assert cb_resp.status_code == status.HTTP_200_OK
    assert cb_resp.json()["is_withdrawable"] is False

    # Dashboard eligibility flag is False
    dash_resp = client.get("/api/v1/dashboard/earnings", headers={"Authorization": f"Bearer {token}"})
    assert dash_resp.status_code == status.HTTP_200_OK
    assert dash_resp.json()["withdrawal_eligibility"]["sequential_commission_eligible"] is False

    # Withdrawal endpoint rejects with 400
    wd_resp = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-FAIL-06"},
    )
    assert wd_resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "No available balance to withdraw" in wd_resp.json()["detail"]


def test_07_repeated_withdrawal_requests_idempotent(client: TestClient, make_user, make_cycle_setup):
    """Case 7: Repeated withdrawal requests: no duplicate payout or wallet debit."""
    user = make_user()
    make_cycle_setup(user=user, contributions=16, cycle_status="COMPLETED", wallet_balance=Decimal("4000.00"))
    token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

    # First withdrawal request
    wd_resp1 = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-REPLAY-KEY"},
    )
    assert wd_resp1.status_code == status.HTTP_200_OK
    wd_id1 = wd_resp1.json()["id"]

    # Replay withdrawal request with the same idempotency key
    wd_resp2 = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-REPLAY-KEY"},
    )
    assert wd_resp2.status_code == status.HTTP_200_OK
    assert wd_resp2.json()["id"] == wd_id1
    assert Decimal(str(wd_resp2.json()["amount"])) == Decimal("4000.00")

    # A third request with a DIFFERENT idempotency key fails because balance is now ₹0
    wd_resp3 = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-NEW-KEY"},
    )
    assert wd_resp3.status_code == status.HTTP_400_BAD_REQUEST


def test_08_customer_cannot_withdraw_another_customer_wallet(client: TestClient, make_user, make_cycle_setup):
    """Case 8: Customer cannot withdraw another customer's balance."""
    user_a = make_user()
    user_b = make_user()
    make_cycle_setup(user=user_a, contributions=16, cycle_status="COMPLETED", wallet_balance=Decimal("4000.00"))
    make_cycle_setup(user=user_b, contributions=0, cycle_status="ACTIVE", wallet_balance=Decimal("0.00"))

    token_b = create_access_token(user_id=user_b.id, role="customer", phone=user_b.phone)

    # User B calling withdraw cannot withdraw User A's ₹4,000 balance
    wd_resp = client.post(
        "/api/v1/wallets/withdraw",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"wallet_type": "sequential_commission", "idempotency_key": "WD-STEAL-KEY"},
    )
    assert wd_resp.status_code == status.HTTP_400_BAD_REQUEST
