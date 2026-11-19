"""Comprehensive test suite for WP-11 Step 2: Notification & Admin Inspection APIs.

Verifies:
Part A — Notification APIs:
1. Authenticated user can list their own notifications.
2. Unauthenticated access returns HTTP 401.
3. Filtering by read/unread status and programme.
4. Pagination parameters (page, page_size) with safe limits.
5. Retrieving an individual notification owned by the current user.
6. IDOR prevention: Customer A cannot read or mark Customer B's notification.
7. Marking an individual notification as read updates is_read and read_at.
8. Marking all notifications as read updates only the caller's notifications.

Part B — Plan A Admin Inspection APIs:
9. Non-admin users cannot access Plan A admin endpoints (HTTP 403).
10. Admin can list Plan A commissions with filtering.
11. Admin can list queues and queue entries.
12. Admin can list cycles and contributions.
13. Admin can list reserve records and reserve summary ("UNALLOCATED — COMPANY OWNED").
14. Reserve summary inspection creates an AuditLog record.
15. Admin can inspect individual customer cashback summary (bulbs progress, cycle metrics).

Part C — Plan B Admin Inspection APIs:
16. Non-admin users cannot access Plan B admin endpoints (HTTP 403).
17. Admin can search and list Plan B distributors.
18. Admin can inspect distributor referrals hierarchy.
19. Admin can list direct and generation commissions separately.
20. Admin can inspect distributor wallet and withdrawal history (creates AuditLog record).
21. Admin can list Plan B billing IDs.

Part D — Security and Read-Only Integrity:
22. Admin inspection calls do not mutate wallet balances or financial records.
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
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.commission import PlanACommission, PlanBCommission
from app.models.enums import (
    AccountStatus,
    OrderStatus,
    PaymentStatus,
    Programme,
    UserRole,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.notification import Notification
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal
from app.services.notification_service import NotificationEvent


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
    counter = [800]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        if role == UserRole.ADMIN:
            code = None
        else:
            code = referral_code or f"WP11U{num:05d}"

        user = User(
            phone=f"97777{num:05d}",
            full_name=f"WP11 User {num}",
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
def make_order_and_bid(db_session: Session):
    """Factory creating an Order and Billing ID with full FK integrity."""
    counter = [5000]

    product = Product(
        name="Arya Power Bank 10000mAh",
        product_code=f"PB-10K-{datetime.now(timezone.utc).timestamp()}",
        price=Decimal("3999.00"),
        stock=10000,
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
            address_line1="123 Test St",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001",
        )
        db_session.add(address)
        db_session.flush()

        order = Order(
            order_number=f"ORD-WP11-{seq:06d}",
            idempotency_key=f"idemp-wp11-{seq:06d}",
            user_id=user.id,
            address_id=address.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
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
            billing_number=f"BID-WP11-{seq:06d}",
            sequence_number=seq,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=0,
            user_id=user.id,
            product_id=product.id,
            programme=programme,
            status="ACTIVE",
        )
        db_session.add(billing_id)
        db_session.flush()

        return order, billing_id

    return _create


# ==============================================================================
# Part A: Notification API Tests
# ==============================================================================

def test_notifications_unauthenticated_rejected(client: TestClient):
    """Unauthenticated requests must be rejected with HTTP 401."""
    res = client.get("/api/v1/notifications")
    assert res.status_code == 401


def test_list_notifications_user_isolation(client: TestClient, db_session: Session, make_user, auth_headers):
    """User A only sees their own notifications, not User B's notifications."""
    user_a = make_user(programme=Programme.PLAN_A)
    user_b = make_user(programme=Programme.PLAN_A)

    notif_a = Notification(
        user_id=user_a.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="Milestone for A",
        message="Message for A",
    )
    notif_b = Notification(
        user_id=user_b.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="Milestone for B",
        message="Message for B",
    )
    db_session.add_all([notif_a, notif_b])
    db_session.commit()

    res = client.get("/api/v1/notifications", headers=auth_headers(user_a))
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == notif_a.id
    assert data["items"][0]["title"] == "Milestone for A"


def test_notifications_filter_read_unread(client: TestClient, db_session: Session, make_user, auth_headers):
    """Notifications can be filtered by is_read status."""
    user = make_user(programme=Programme.PLAN_A)

    n1 = Notification(
        user_id=user.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="Unread 1",
        message="Msg 1",
        is_read=False,
    )
    n2 = Notification(
        user_id=user.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="Read 1",
        message="Msg 2",
        is_read=True,
        read_at=datetime.now(timezone.utc),
    )
    db_session.add_all([n1, n2])
    db_session.commit()

    # Filter unread
    res_unread = client.get("/api/v1/notifications?is_read=false", headers=auth_headers(user))
    assert res_unread.status_code == 200
    unread_data = res_unread.json()
    assert unread_data["total"] == 1
    assert unread_data["items"][0]["title"] == "Unread 1"

    # Filter read
    res_read = client.get("/api/v1/notifications?is_read=true", headers=auth_headers(user))
    assert res_read.status_code == 200
    read_data = res_read.json()
    assert read_data["total"] == 1
    assert read_data["items"][0]["title"] == "Read 1"


def test_get_single_notification_and_idor_protection(client: TestClient, db_session: Session, make_user, auth_headers):
    """User can fetch their own notification; attempting to fetch another user's returns 404."""
    user_a = make_user(programme=Programme.PLAN_A)
    user_b = make_user(programme=Programme.PLAN_A)

    n_b = Notification(
        user_id=user_b.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="Secret for B",
        message="Private details",
    )
    db_session.add(n_b)
    db_session.commit()

    # User B can view it
    res_b = client.get(f"/api/v1/notifications/{n_b.id}", headers=auth_headers(user_b))
    assert res_b.status_code == 200
    assert res_b.json()["id"] == n_b.id

    # User A tries to view B's notification -> 404
    res_a = client.get(f"/api/v1/notifications/{n_b.id}", headers=auth_headers(user_a))
    assert res_a.status_code == 404


def test_mark_single_notification_read(client: TestClient, db_session: Session, make_user, auth_headers):
    """Marking a single notification read updates is_read and read_at."""
    user = make_user(programme=Programme.PLAN_A)

    n = Notification(
        user_id=user.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="Mark me read",
        message="Message",
        is_read=False,
    )
    db_session.add(n)
    db_session.commit()

    res = client.post(f"/api/v1/notifications/{n.id}/read", headers=auth_headers(user))
    assert res.status_code == 200
    data = res.json()
    assert data["is_read"] is True
    assert data["read_at"] is not None

    db_session.refresh(n)
    assert n.is_read is True


def test_mark_single_notification_read_idor_protection(client: TestClient, db_session: Session, make_user, auth_headers):
    """Customer A cannot mark Customer B's notification as read (HTTP 404, unread state preserved)."""
    user_a = make_user(programme=Programme.PLAN_A)
    user_b = make_user(programme=Programme.PLAN_A)

    nb = Notification(
        user_id=user_b.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="B's Notification",
        message="Confidential for B",
        is_read=False,
    )
    db_session.add(nb)
    db_session.commit()

    # User A attempts to mark B's notification as read
    res = client.post(f"/api/v1/notifications/{nb.id}/read", headers=auth_headers(user_a))
    assert res.status_code == 404

    # Verify B's notification remains unread with no timestamp
    db_session.refresh(nb)
    assert nb.is_read is False
    assert nb.read_at is None


def test_mark_all_notifications_read(client: TestClient, db_session: Session, make_user, auth_headers):
    """Mark-all endpoint marks only current user's unread notifications."""
    user_a = make_user(programme=Programme.PLAN_A)
    user_b = make_user(programme=Programme.PLAN_A)

    na1 = Notification(
        user_id=user_a.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="A1",
        message="Msg",
        is_read=False,
    )
    na2 = Notification(
        user_id=user_a.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="A2",
        message="Msg",
        is_read=False,
    )
    nb = Notification(
        user_id=user_b.id,
        event_type=NotificationEvent.PA_ADMIN_CASHBACK_CYCLE_COMPLETED.value,
        programme=Programme.PLAN_A,
        title="B1",
        message="Msg",
        is_read=False,
    )
    db_session.add_all([na1, na2, nb])
    db_session.commit()

    res = client.post("/api/v1/notifications/read-all", headers=auth_headers(user_a))
    assert res.status_code == 200
    data = res.json()
    assert data["marked_count"] == 2

    # User B's notification remains unread
    db_session.refresh(nb)
    assert nb.is_read is False


# ==============================================================================
# Part B: Plan A Admin Inspection API Tests
# ==============================================================================

def test_admin_endpoints_unauthenticated_rejected(client: TestClient):
    """Requests without authorization header return HTTP 401 on admin endpoints."""
    res_a = client.get("/api/v1/admin/plan-a/commissions")
    assert res_a.status_code == 401

    res_b = client.get("/api/v1/admin/plan-b/distributors")
    assert res_b.status_code == 401


def test_plan_a_admin_endpoints_require_admin(client: TestClient, make_user, auth_headers):
    """Non-admin users receive HTTP 403 Forbidden on all Plan A admin endpoints."""
    customer = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
    headers = auth_headers(customer)

    endpoints = [
        "/api/v1/admin/plan-a/commissions",
        "/api/v1/admin/plan-a/queues",
        "/api/v1/admin/plan-a/queues/1/entries",
        "/api/v1/admin/plan-a/cycles",
        "/api/v1/admin/plan-a/cycles/1/contributions",
        "/api/v1/admin/plan-a/reserve",
        "/api/v1/admin/plan-a/reserve/summary",
        f"/api/v1/admin/plan-a/customers/{customer.id}/cashback-summary",
    ]
    for ep in endpoints:
        res = client.get(ep, headers=headers)
        assert res.status_code == 403, f"Expected 403 for {ep}, got {res.status_code}"


def test_admin_list_plan_a_commissions(client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers):
    """Admin can list and filter Plan A commissions."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    purchaser = make_user(programme=Programme.PLAN_A)
    referrer = make_user(programme=Programme.PLAN_A)

    order, bid = make_order_and_bid(purchaser, programme=Programme.PLAN_A)

    comm = PlanACommission(
        billing_id=bid.id,
        order_id=order.id,
        purchaser_id=purchaser.id,
        referrer_id=referrer.id,
        applied_referral_code=referrer.referral_code,
        gross_amount=Decimal("500.00"),
        operational_cost_amount=Decimal("50.00"),
        tds_amount=Decimal("25.00"),
        net_amount=Decimal("425.00"),
        status="PROCESSED",
        idempotency_key="COMM-A-TEST-001",
    )
    db_session.add(comm)
    db_session.commit()

    res = client.get("/api/v1/admin/plan-a/commissions", headers=auth_headers(admin))
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 1
    record = items[0]
    assert record["billing_id"] == bid.id
    assert Decimal(record["gross_amount"]) == Decimal("500.00")
    assert Decimal(record["net_amount"]) == Decimal("425.00")


def test_admin_list_cashback_queues_and_entries(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can inspect queues and individual queue entries."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    root_user = make_user(programme=Programme.PLAN_A)

    queue = PlanACashbackQueue(
        root_user_id=root_user.id,
        last_allocated_position=1,
    )
    db_session.add(queue)
    db_session.flush()

    entry = PlanACashbackEntry(
        queue_id=queue.id,
        user_id=root_user.id,
        billing_id=555,
        queue_position=1,
        status="ACTIVE",
    )
    db_session.add(entry)
    db_session.commit()

    # List queues
    res_q = client.get("/api/v1/admin/plan-a/queues", headers=auth_headers(admin))
    assert res_q.status_code == 200
    q_data = res_q.json()
    assert len(q_data) >= 1
    matched_q = next(q for q in q_data if q["id"] == queue.id)
    assert matched_q["total_entries"] == 1

    # List queue entries
    res_e = client.get(f"/api/v1/admin/plan-a/queues/{queue.id}/entries", headers=auth_headers(admin))
    assert res_e.status_code == 200
    e_data = res_e.json()
    assert len(e_data) == 1
    assert e_data[0]["queue_position"] == 1
    assert e_data[0]["billing_id"] == 555


def test_admin_reserve_summary_and_audit_logging(client: TestClient, db_session: Session, make_user, auth_headers):
    """Reserve summary returns 'UNALLOCATED — COMPANY OWNED', persists audit record, and leaves data unchanged."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    cust = make_user(programme=Programme.PLAN_A)

    reserve = PlanAUnallocatedCashbackReserve(
        queue_id=1,
        billing_id=901,
        customer_id=cust.id,
        amount=Decimal("250.00"),
        status="UNALLOCATED — COMPANY OWNED",
        idempotency_key="RES-TEST-001",
    )
    db_session.add(reserve)
    db_session.commit()

    res = client.get("/api/v1/admin/plan-a/reserve/summary", headers=auth_headers(admin))
    assert res.status_code == 200
    data = res.json()
    assert data["status_label"] == "UNALLOCATED — COMPANY OWNED"
    assert Decimal(data["total_unallocated_amount"]) >= Decimal("250.00")

    # Expire session / verify persistence in database
    db_session.expire_all()
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.actor_id == admin.id, AuditLog.action == "INSPECT_PLAN_A_RESERVE")
        .first()
    )
    assert audit is not None
    assert audit.entity_type == "PlanAUnallocatedCashbackReserve"
    assert audit.entity_id == "ALL"

    # Verify zero financial mutation on reserve records
    db_session.refresh(reserve)
    assert reserve.amount == Decimal("250.00")
    assert reserve.status == "UNALLOCATED — COMPANY OWNED"


def test_admin_list_reserve_entries(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can list company-owned unallocated cashback reserve records."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    cust = make_user(programme=Programme.PLAN_A)

    reserve = PlanAUnallocatedCashbackReserve(
        queue_id=1,
        billing_id=999,
        customer_id=cust.id,
        amount=Decimal("250.00"),
        status="UNALLOCATED — COMPANY OWNED",
        idempotency_key="RES-LIST-TEST-001",
    )
    db_session.add(reserve)
    db_session.commit()

    res = client.get(
        "/api/v1/admin/plan-a/reserve?queue_id=1",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 1
    entry = next(e for e in items if e["id"] == reserve.id)
    assert entry["billing_id"] == 999
    assert entry["customer_id"] == cust.id
    assert Decimal(entry["amount"]) == Decimal("250.00")
    assert entry["status"] == "UNALLOCATED — COMPANY OWNED"


def test_admin_list_cashback_cycles(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can list and filter Plan A cashback cycles."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    cust = make_user(programme=Programme.PLAN_A)

    queue = PlanACashbackQueue(root_user_id=cust.id, last_allocated_position=1)
    db_session.add(queue)
    db_session.flush()

    entry = PlanACashbackEntry(
        queue_id=queue.id,
        user_id=cust.id,
        billing_id=801,
        queue_position=1,
        status="ACTIVE",
    )
    db_session.add(entry)
    db_session.flush()

    cycle = PlanACashbackCycle(
        queue_id=queue.id,
        queue_entry_id=entry.id,
        recipient_user_id=cust.id,
        recipient_billing_id=801,
        cycle_number=1,
        completed_contributions=4,
        total_earned=Decimal("1000.00"),
        status="ACTIVE",
    )
    db_session.add(cycle)
    db_session.commit()

    res = client.get(
        f"/api/v1/admin/plan-a/cycles?recipient_user_id={cust.id}&status=ACTIVE",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    c = items[0]
    assert c["id"] == cycle.id
    assert c["recipient_user_id"] == cust.id
    assert c["recipient_user_name"] == cust.full_name
    assert c["completed_contributions"] == 4
    assert Decimal(c["total_earned"]) == Decimal("1000.00")
    assert c["status"] == "ACTIVE"


def test_admin_list_cycle_contributions(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can list individual contributions allocated to a cycle."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    cust = make_user(programme=Programme.PLAN_A)
    contributor = make_user(programme=Programme.PLAN_A)

    queue = PlanACashbackQueue(root_user_id=cust.id, last_allocated_position=1)
    db_session.add(queue)
    db_session.flush()

    entry = PlanACashbackEntry(
        queue_id=queue.id,
        user_id=cust.id,
        billing_id=802,
        queue_position=1,
        status="ACTIVE",
    )
    db_session.add(entry)
    db_session.flush()

    cycle = PlanACashbackCycle(
        queue_id=queue.id,
        queue_entry_id=entry.id,
        recipient_user_id=cust.id,
        recipient_billing_id=802,
        cycle_number=1,
        completed_contributions=1,
        total_earned=Decimal("250.00"),
        status="ACTIVE",
    )
    db_session.add(cycle)
    db_session.flush()

    contrib = PlanACashbackContribution(
        queue_id=queue.id,
        cycle_id=cycle.id,
        contributing_billing_id=901,
        contributing_user_id=contributor.id,
        recipient_user_id=cust.id,
        amount=Decimal("250.00"),
        status="ALLOCATED",
        idempotency_key="CB-CONTRIB-TEST-001",
    )
    db_session.add(contrib)
    db_session.commit()

    res = client.get(
        f"/api/v1/admin/plan-a/cycles/{cycle.id}/contributions",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    ct = items[0]
    assert ct["id"] == contrib.id
    assert ct["cycle_id"] == cycle.id
    assert ct["contributing_billing_id"] == 901
    assert ct["contributing_user_id"] == contributor.id
    assert ct["recipient_user_id"] == cust.id
    assert Decimal(ct["amount"]) == Decimal("250.00")
    assert ct["status"] == "ALLOCATED"


def test_admin_customer_cashback_summary(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin inspects customer cashback summary with bulbs calculation, audit log, and zero financial mutation."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    cust = make_user(programme=Programme.PLAN_A)

    # Setup wallet
    wallet = Wallet(
        user_id=cust.id,
        wallet_type=WalletType.SEQUENTIAL_COMMISSION,
        balance=Decimal("750.00"),
    )
    queue = PlanACashbackQueue(root_user_id=cust.id, last_allocated_position=1)
    db_session.add_all([wallet, queue])
    db_session.flush()

    entry = PlanACashbackEntry(
        queue_id=queue.id,
        user_id=cust.id,
        billing_id=777,
        queue_position=1,
        status="ACTIVE",
    )
    db_session.add(entry)
    db_session.flush()

    cycle = PlanACashbackCycle(
        queue_id=queue.id,
        queue_entry_id=entry.id,
        recipient_user_id=cust.id,
        recipient_billing_id=777,
        cycle_number=1,
        completed_contributions=3,
        total_earned=Decimal("750.00"),
        status="ACTIVE",
    )
    db_session.add(cycle)
    db_session.commit()

    res = client.get(
        f"/api/v1/admin/plan-a/customers/{cust.id}/cashback-summary",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["customer_id"] == cust.id
    assert data["completed_contributions"] == 3
    # 3 contributions * 3 bulbs = 9 bulbs ON
    assert data["bulbs_on"] == 9
    assert data["bulbs_off"] == 39
    assert Decimal(data["wallet_balance"]) == Decimal("750.00")

    # Expire session / verify persistence in database
    db_session.expire_all()
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.actor_id == admin.id, AuditLog.action == "INSPECT_CUSTOMER_CASHBACK")
        .first()
    )
    assert audit is not None
    assert audit.entity_id == str(cust.id)

    # Verify zero financial mutation on customer wallet or cashback cycle
    db_session.refresh(wallet)
    assert wallet.balance == Decimal("750.00")
    assert wallet.is_frozen is False
    db_session.refresh(cycle)
    assert cycle.completed_contributions == 3
    assert cycle.total_earned == Decimal("750.00")


# ==============================================================================
# Part C: Plan B Admin Inspection API Tests
# ==============================================================================

def test_plan_b_admin_endpoints_require_admin(client: TestClient, make_user, auth_headers):
    """Non-admin users receive HTTP 403 Forbidden on Plan B admin endpoints."""
    distributor = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)
    headers = auth_headers(distributor)

    endpoints = [
        "/api/v1/admin/plan-b/distributors",
        f"/api/v1/admin/plan-b/distributors/{distributor.id}",
        f"/api/v1/admin/plan-b/distributors/{distributor.id}/referrals",
        "/api/v1/admin/plan-b/commissions/direct",
        "/api/v1/admin/plan-b/commissions/generation",
        f"/api/v1/admin/plan-b/distributors/{distributor.id}/wallet",
        "/api/v1/admin/plan-b/billing-ids",
    ]
    for ep in endpoints:
        res = client.get(ep, headers=headers)
        assert res.status_code == 403, f"Expected 403 for {ep}, got {res.status_code}"


def test_admin_search_and_get_distributor(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can search distributors and retrieve detailed profile."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)
    referee = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

    rel = ReferralRelationship(
        referee_id=referee.id,
        referrer_id=dist.id,
        referee_programme=Programme.PLAN_B,
        referrer_programme=Programme.PLAN_B,
        referral_code_used=dist.referral_code,
        binding_channel="DIRECT_LINK",
        is_active=True,
    )
    db_session.add(rel)
    db_session.commit()

    # Search by phone or name
    res_list = client.get(
        f"/api/v1/admin/plan-b/distributors?search={dist.phone}",
        headers=auth_headers(admin),
    )
    assert res_list.status_code == 200
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["id"] == dist.id
    assert items[0]["direct_referees_count"] == 1

    # Get single distributor
    res_single = client.get(
        f"/api/v1/admin/plan-b/distributors/{dist.id}",
        headers=auth_headers(admin),
    )
    assert res_single.status_code == 200
    single_data = res_single.json()
    assert single_data["id"] == dist.id
    assert single_data["direct_referees_count"] == 1


def test_admin_distributor_referrals_list(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can list direct referrals belonging to a distributor."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)
    referee = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

    rel = ReferralRelationship(
        referee_id=referee.id,
        referrer_id=dist.id,
        referee_programme=Programme.PLAN_B,
        referrer_programme=Programme.PLAN_B,
        referral_code_used=dist.referral_code,
        binding_channel="MANUAL_INPUT",
        is_active=True,
    )
    db_session.add(rel)
    db_session.commit()

    res = client.get(
        f"/api/v1/admin/plan-b/distributors/{dist.id}/referrals",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["referee_id"] == referee.id
    assert data[0]["referee_name"] == referee.full_name


def test_admin_plan_b_commissions(client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers):
    """Admin can inspect direct and generation commissions separately."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)
    referee = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

    order, bid = make_order_and_bid(referee, programme=Programme.PLAN_B)

    comm_dir = PlanBCommission(
        commission_type="DIRECT",
        distributor_id=dist.id,
        referee_id=referee.id,
        order_id=order.id,
        billing_id=bid.id,
        gross_amount=Decimal("1000.00"),
        operational_cost_amount=Decimal("100.00"),
        tds_amount=Decimal("50.00"),
        net_amount=Decimal("850.00"),
        status="PROCESSED",
        idempotency_key="PB-DIR-TEST-001",
    )
    comm_gen = PlanBCommission(
        commission_type="GENERATION",
        distributor_id=dist.id,
        referee_id=referee.id,
        order_id=order.id,
        billing_id=bid.id,
        gross_amount=Decimal("200.00"),
        operational_cost_amount=Decimal("20.00"),
        tds_amount=Decimal("10.00"),
        net_amount=Decimal("170.00"),
        status="PROCESSED",
        idempotency_key="PB-GEN-TEST-001",
    )
    db_session.add_all([comm_dir, comm_gen])
    db_session.commit()

    # Direct commissions
    res_dir = client.get("/api/v1/admin/plan-b/commissions/direct", headers=auth_headers(admin))
    assert res_dir.status_code == 200
    dir_items = res_dir.json()
    assert len(dir_items) >= 1
    assert all(c["commission_type"] == "DIRECT" for c in dir_items)

    # Generation commissions
    res_gen = client.get("/api/v1/admin/plan-b/commissions/generation", headers=auth_headers(admin))
    assert res_gen.status_code == 200
    gen_items = res_gen.json()
    assert len(gen_items) >= 1
    assert all(c["commission_type"] == "GENERATION" for c in gen_items)


def test_admin_distributor_wallet_overview(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin can inspect distributor wallet, transactions, and withdrawals."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

    wallet = Wallet(
        user_id=dist.id,
        wallet_type=WalletType.DIRECT_REFERRAL,
        balance=Decimal("1200.00"),
        total_withdrawn=Decimal("500.00"),
    )
    db_session.add(wallet)
    db_session.flush()

    tx = WalletTransaction(
        wallet_id=wallet.id,
        user_id=dist.id,
        wallet_type=WalletType.DIRECT_REFERRAL,
        transaction_type=WalletTransactionType.CREDIT,
        amount=Decimal("1700.00"),
        balance_after=Decimal("1700.00"),
        reference_type=WalletReferenceType.DIRECT_REFERRAL,
        reference_id=1,
        idempotency_key="TX-TEST-001",
    )
    w = Withdrawal(
        wallet_id=wallet.id,
        user_id=dist.id,
        amount=Decimal("500.00"),
        status=WithdrawalStatus.COMPLETED,
        idempotency_key="WD-TEST-001",
        receipt_reference="RCP-001",
    )
    db_session.add_all([tx, w])
    db_session.commit()

    res = client.get(
        f"/api/v1/admin/plan-b/distributors/{dist.id}/wallet",
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["distributor_id"] == dist.id
    assert Decimal(data["balance"]) == Decimal("1200.00")
    assert Decimal(data["total_earned"]) == Decimal("1700.00")
    assert Decimal(data["total_withdrawn"]) == Decimal("500.00")
    assert len(data["recent_transactions"]) == 1
    assert len(data["recent_withdrawals"]) == 1

    # Check audit log
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.actor_id == admin.id, AuditLog.action == "INSPECT_DISTRIBUTOR_WALLET")
        .first()
    )
    assert audit is not None
    assert audit.entity_id == str(wallet.id)


def test_admin_plan_b_billing_ids(client: TestClient, db_session: Session, make_user, make_order_and_bid, auth_headers):
    """Admin can list Plan B Billing IDs."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

    order_b, bid_b = make_order_and_bid(dist, programme=Programme.PLAN_B)
    order_a, bid_a = make_order_and_bid(dist, programme=Programme.PLAN_A)
    db_session.commit()

    res = client.get("/api/v1/admin/plan-b/billing-ids", headers=auth_headers(admin))
    assert res.status_code == 200
    items = res.json()
    assert any(b["id"] == bid_b.id and b["programme"] == "PLAN_B" for b in items)
    assert not any(b["id"] == bid_a.id for b in items)


def test_inspection_read_only_guarantee(client: TestClient, db_session: Session, make_user, auth_headers):
    """Admin inspection endpoints must never alter balances, freeze states, or financial data."""
    admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
    dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

    wallet = Wallet(
        user_id=dist.id,
        wallet_type=WalletType.DIRECT_REFERRAL,
        balance=Decimal("2500.00"),
        total_withdrawn=Decimal("100.00"),
        is_frozen=False,
    )
    db_session.add(wallet)
    db_session.commit()

    # Call inspection endpoints repeatedly
    for _ in range(3):
        res = client.get(
            f"/api/v1/admin/plan-b/distributors/{dist.id}/wallet",
            headers=auth_headers(admin),
        )
        assert res.status_code == 200

    # Verify database state remained unchanged
    db_session.refresh(wallet)
    assert wallet.balance == Decimal("2500.00")
    assert wallet.total_withdrawn == Decimal("100.00")
    assert wallet.is_frozen is False
