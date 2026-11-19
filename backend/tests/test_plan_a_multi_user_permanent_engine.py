"""Automated Multi-User Reliability and Concurrency Test Suite for Plan A Cashback Engine.

Strictly covers all 12 mandatory multi-user scenarios:
1. Two independent referral roots operating simultaneously.
2. Multiple customers purchasing under the same referral root.
3. Multiple customers purchasing under different referral roots.
4. Two or more simultaneous purchases competing for the last position in a cycle.
5. A customer purchasing their own products (BR-A4 / BR-A5 Option A).
6. A customer using another referral root's code.
7. Repeated payment and fulfilment callbacks (idempotency).
8. Server restart during contribution processing.
9. Recovery of interrupted contributions.
10. Completion of three consecutive cycles for one beneficiary (monotonic numbering).
11. Correct transition from one beneficiary to the next (graduation & advancement).
12. Correct wallet and ledger reconciliation after withdrawals.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import secrets
from typing import List, Tuple
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.security import create_access_token
from app.models.billing import BillingId
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
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction
from app.services.cashback.plan_a import PlanACashbackService
from app.services.wallet_service import execute_simulated_withdrawal, get_or_create_wallet


@pytest.fixture
def multi_user_db():
    """Create an isolated, in-memory SQLite database session for multi-user tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionClass()
    try:
        yield session, SessionClass, engine
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _create_test_user(db: Session, phone: str, name: str, ref_code: str, programme=Programme.PLAN_A) -> User:
    u = User(
        phone=phone,
        full_name=name,
        role=UserRole.CUSTOMER,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=ref_code,
    )
    db.add(u)
    db.flush()
    return u


def _create_test_order_with_billing(db: Session, user: User, quantity: int, ref_code=None) -> Tuple[Order, List[BillingId]]:
    addr = db.query(Address).filter(Address.user_id == user.id).first()
    if not addr:
        addr = Address(
            user_id=user.id,
            recipient_name=user.full_name or "Test User",
            phone=user.phone,
            address_line1="123 Test Street",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
            is_default=True,
        )
        db.add(addr)
        db.flush()

    prod = db.query(Product).filter(Product.product_code == "PB-3999").first()
    if not prod:
        prod = Product(
            name="Arya Power Bank 10000mAh",
            product_code="PB-3999",
            price=Decimal("3999.00"),
            stock=10000,
            is_active=True,
            is_power_bank=True,
        )
        db.add(prod)
        db.flush()

    order = Order(
        order_number=f"ORD-{user.id}-{int(datetime.now(timezone.utc).timestamp()*1000)%1000000}-{secrets.token_hex(4)}",
        idempotency_key=f"idemp-{secrets.token_hex(8)}",
        user_id=user.id,
        address_id=addr.id,
        total_amount=Decimal("3999.00") * quantity,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        applied_referral_code=ref_code,
        is_fulfilled=True,
    )
    db.add(order)
    db.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=prod.price,
        quantity=quantity,
        line_total=prod.price * quantity,
    )
    db.add(order_item)
    db.flush()

    bids = []
    for i in range(quantity):
        seq = db.query(BillingId).count() + 1
        bid = BillingId(
            order_id=order.id,
            order_item_id=order_item.id,
            product_id=prod.id,
            user_id=user.id,
            billing_number=f"AGD-{seq:06d}-{secrets.token_hex(2)}",
            unit_index=i + 1,
            sequence_number=seq,
            programme=Programme.PLAN_A,
        )
        db.add(bid)
        db.flush()
        bids.append(bid)

    db.commit()
    return order, bids


# ---------------------------------------------------------------------------
# Test 1: Two independent referral roots operating simultaneously
# ---------------------------------------------------------------------------
def test_01_two_independent_referral_roots_simultaneous(multi_user_db):
    session, session_factory, _ = multi_user_db

    root_a = _create_test_user(session, "9100000001", "Root A", "TREE1A")
    buyer_a = _create_test_user(session, "9100000002", "Buyer A", "TREE1B")
    session.add(ReferralRelationship(referee_id=buyer_a.id, referrer_id=root_a.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="TREE1A", binding_channel="checkout", is_active=True))

    root_b = _create_test_user(session, "9200000001", "Root B", "TREE2A")
    buyer_b = _create_test_user(session, "9200000002", "Buyer B", "TREE2B")
    session.add(ReferralRelationship(referee_id=buyer_b.id, referrer_id=root_b.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="TREE2A", binding_channel="checkout", is_active=True))
    session.commit()

    _, root_a_bids = _create_test_order_with_billing(session, root_a, 1)
    _, root_b_bids = _create_test_order_with_billing(session, root_b, 1)

    PlanACashbackService.process_billing_id(root_a_bids[0].id, session_factory=session_factory)
    PlanACashbackService.process_billing_id(root_b_bids[0].id, session_factory=session_factory)

    q_a = session.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == root_a.id).first()
    q_b = session.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == root_b.id).first()
    assert q_a is not None and q_b is not None
    assert q_a.id != q_b.id

    _, a_bids = _create_test_order_with_billing(session, buyer_a, 2, ref_code="TREE1A")
    _, b_bids = _create_test_order_with_billing(session, buyer_b, 2, ref_code="TREE2A")

    PlanACashbackService.process_billing_id(a_bids[0].id, session_factory=session_factory)
    PlanACashbackService.process_billing_id(b_bids[0].id, session_factory=session_factory)

    contrib_a = session.query(PlanACashbackContribution).filter(PlanACashbackContribution.contributing_billing_id == a_bids[0].id).first()
    contrib_b = session.query(PlanACashbackContribution).filter(PlanACashbackContribution.contributing_billing_id == b_bids[0].id).first()

    assert contrib_a.queue_id == q_a.id and contrib_a.recipient_user_id == root_a.id
    assert contrib_b.queue_id == q_b.id and contrib_b.recipient_user_id == root_b.id


# ---------------------------------------------------------------------------
# Test 2: Multiple customers purchasing under the same referral root
# ---------------------------------------------------------------------------
def test_02_multiple_customers_under_same_referral_root(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9300000001", "Root Tree", "ROOTTREE")
    buyers = [
        _create_test_user(session, f"930000000{i}", f"Downline {i}", f"DOWN{i}")
        for i in range(2, 5)
    ]
    for b in buyers:
        session.add(ReferralRelationship(referee_id=b.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="ROOTTREE", binding_channel="checkout", is_active=True))
    session.commit()

    _, root_bids = _create_test_order_with_billing(session, root, 1)
    PlanACashbackService.process_billing_id(root_bids[0].id, session_factory=session_factory)

    for idx, b in enumerate(buyers):
        _, b_bids = _create_test_order_with_billing(session, b, 5, ref_code="ROOTTREE")
        for bid in b_bids:
            res = PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)
            assert res.status == "CONTRIBUTED"
            assert res.recipient_user_id == root.id

    cyc = session.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == root.id).first()
    assert cyc.completed_contributions == 15
    assert cyc.total_earned == Decimal("3750.00")
    assert cyc.status == "ACTIVE"


# ---------------------------------------------------------------------------
# Test 3: Multiple customers purchasing under different referral roots (interleaved)
# ---------------------------------------------------------------------------
def test_03_multiple_customers_under_different_referral_roots(multi_user_db):
    session, session_factory, _ = multi_user_db

    r1 = _create_test_user(session, "9410000001", "Root 1", "R1CODE")
    r2 = _create_test_user(session, "9420000001", "Root 2", "R2CODE")
    b1 = _create_test_user(session, "9410000002", "Buyer 1", "B1CODE")
    b2 = _create_test_user(session, "9420000002", "Buyer 2", "B2CODE")

    session.add(ReferralRelationship(referee_id=b1.id, referrer_id=r1.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="R1CODE", binding_channel="checkout", is_active=True))
    session.add(ReferralRelationship(referee_id=b2.id, referrer_id=r2.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="R2CODE", binding_channel="checkout", is_active=True))
    session.commit()

    _, r1_bids = _create_test_order_with_billing(session, r1, 1)
    _, r2_bids = _create_test_order_with_billing(session, r2, 1)
    PlanACashbackService.process_billing_id(r1_bids[0].id, session_factory=session_factory)
    PlanACashbackService.process_billing_id(r2_bids[0].id, session_factory=session_factory)

    _, b1_bids = _create_test_order_with_billing(session, b1, 4, ref_code="R1CODE")
    _, b2_bids = _create_test_order_with_billing(session, b2, 4, ref_code="R2CODE")

    # Interleaved processing: B1, B2, B1, B2...
    for i in range(4):
        res1 = PlanACashbackService.process_billing_id(b1_bids[i].id, session_factory=session_factory)
        res2 = PlanACashbackService.process_billing_id(b2_bids[i].id, session_factory=session_factory)
        assert res1.recipient_user_id == r1.id
        assert res2.recipient_user_id == r2.id

    c1 = session.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == r1.id).first()
    c2 = session.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == r2.id).first()
    assert c1.completed_contributions == 4
    assert c2.completed_contributions == 4


# ---------------------------------------------------------------------------
# Test 4: Two or more simultaneous purchases competing for the last position in a cycle
# ---------------------------------------------------------------------------
def test_04_simultaneous_purchases_competing_for_cycle_completion(tmp_path):
    db_file = tmp_path / "concurrent_last_pos.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.execute(text("PRAGMA synchronous=NORMAL;"))
        conn.commit()

    Base.metadata.create_all(engine)
    SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    init_db = SessionMaker()
    root = _create_test_user(init_db, "9500000001", "Race Root", "RACEROOT")
    b1 = _create_test_user(init_db, "9500000002", "Race B1", "RACEB1")
    b2 = _create_test_user(init_db, "9500000003", "Race B2", "RACEB2")
    init_db.add(ReferralRelationship(referee_id=b1.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="RACEROOT", binding_channel="checkout", is_active=True))
    init_db.add(ReferralRelationship(referee_id=b2.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="RACEROOT", binding_channel="checkout", is_active=True))
    init_db.commit()

    # Root has 2 queue entries
    _, root_bids = _create_test_order_with_billing(init_db, root, 2)
    for bid in root_bids:
        PlanACashbackService.process_billing_id(bid.id, session_factory=SessionMaker)

    # Pre-fill cycle with 15 contributions from b1's 16-item order
    _, b1_bids = _create_test_order_with_billing(init_db, b1, 16, ref_code="RACEROOT")
    for bid in b1_bids[:15]:
        PlanACashbackService.process_billing_id(bid.id, session_factory=SessionMaker)

    # Prepare two competing purchases: b1's 16th item vs b2's 1st item
    _, b2_bids = _create_test_order_with_billing(init_db, b2, 1, ref_code="RACEROOT")
    bid1_id = b1_bids[15].id
    bid2_id = b2_bids[0].id
    root_id = root.id
    init_db.close()

    # Launch both simultaneously in separate threads
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(PlanACashbackService.process_billing_id, bid1_id, None, SessionMaker)
        f2 = executor.submit(PlanACashbackService.process_billing_id, bid2_id, None, SessionMaker)
        r1, r2 = f1.result(), f2.result()

    assert r1.status == "CONTRIBUTED"
    assert r2.status == "CONTRIBUTED"

    check_db = SessionMaker()
    cycles = check_db.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == root_id).order_by(PlanACashbackCycle.cycle_number.asc()).all()
    assert len(cycles) == 2
    assert cycles[0].status == "COMPLETED" and cycles[0].completed_contributions == 16
    assert cycles[1].status == "ACTIVE" and cycles[1].completed_contributions == 1

    # Wallet credited exactly ₹4,000 for the completed cycle
    w = check_db.query(Wallet).filter(Wallet.user_id == root_id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION).first()
    assert w.balance == Decimal("4000.00")
    check_db.close()


# ---------------------------------------------------------------------------
# Test 5: A customer purchasing their own products (BR-A4 / BR-A5 Option A)
# ---------------------------------------------------------------------------
def test_05_customer_purchasing_own_products_routes_to_reserve(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9600000001", "Self Buyer", "SELF1")
    session.commit()

    # 1st purchase: creates queue and routes ₹250 to reserve (BR-A4)
    _, bid1 = _create_test_order_with_billing(session, root, 1)
    res1 = PlanACashbackService.process_billing_id(bid1[0].id, session_factory=session_factory)
    assert res1.status == "RESERVED_INITIAL_QUEUE"

    # 2nd purchase: Root is active recipient -> routes ₹250 to reserve (BR-A5 Option A)
    _, bid2 = _create_test_order_with_billing(session, root, 1)
    res2 = PlanACashbackService.process_billing_id(bid2[0].id, session_factory=session_factory)
    assert res2.status == "RESERVED_RECIPIENT_PURCHASE"

    # Verify both are recorded in PlanAUnallocatedCashbackReserve
    reserves = session.query(PlanAUnallocatedCashbackReserve).filter(PlanAUnallocatedCashbackReserve.customer_id == root.id).all()
    assert len(reserves) == 2

    # Active cycle has NOT received contributions from own purchases
    cyc = session.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == root.id).first()
    assert cyc.completed_contributions == 0


# ---------------------------------------------------------------------------
# Test 6: A customer using another referral root's code
# ---------------------------------------------------------------------------
def test_06_customer_using_another_referral_roots_code(multi_user_db):
    session, session_factory, _ = multi_user_db

    # Tree 1: Hithesh
    hithesh = _create_test_user(session, "9710000001", "Hithesh", "PAJA3W14")
    # Tree 2: Punith
    punith = _create_test_user(session, "9720000001", "Punith", "PAR8L0CA")

    # Downline in Tree 1
    h_downline = _create_test_user(session, "9710000002", "H Downline", "PAZ68RRD")
    session.add(ReferralRelationship(referee_id=h_downline.id, referrer_id=hithesh.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="PAJA3W14", binding_channel="checkout", is_active=True))

    # Customer 04 registers using PAZ68RRD (belongs to Hithesh's tree!)
    cust04 = _create_test_user(session, "9710000003", "Customer 04", "PATTKEDN")
    session.add(ReferralRelationship(referee_id=cust04.id, referrer_id=h_downline.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="PAZ68RRD", binding_channel="checkout", is_active=True))
    session.commit()

    _, h_bids = _create_test_order_with_billing(session, hithesh, 1)
    _, p_bids = _create_test_order_with_billing(session, punith, 1)
    PlanACashbackService.process_billing_id(h_bids[0].id, session_factory=session_factory)
    PlanACashbackService.process_billing_id(p_bids[0].id, session_factory=session_factory)

    q_h = session.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == hithesh.id).first()
    q_p = session.query(PlanACashbackQueue).filter(PlanACashbackQueue.root_user_id == punith.id).first()

    # Customer 04 purchases with PAZ68RRD
    _, c04_bids = _create_test_order_with_billing(session, cust04, 1, ref_code="PAZ68RRD")
    res = PlanACashbackService.process_billing_id(c04_bids[0].id, session_factory=session_factory)

    # Authoritative verification: routes to Hithesh's Queue (q_h), NEVER Punith's Queue (q_p)
    assert res.queue_id == q_h.id
    assert res.queue_id != q_p.id


# ---------------------------------------------------------------------------
# Test 7: Repeated payment and fulfilment callbacks (idempotency)
# ---------------------------------------------------------------------------
def test_07_repeated_payment_and_fulfilment_callbacks_idempotency(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9810000001", "Idemp Root", "IDEMPROOT")
    buyer = _create_test_user(session, "9810000002", "Idemp Buyer", "IDEMPBUY")
    session.add(ReferralRelationship(referee_id=buyer.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="IDEMPROOT", binding_channel="checkout", is_active=True))
    session.commit()

    _, r_bids = _create_test_order_with_billing(session, root, 1)
    PlanACashbackService.process_billing_id(r_bids[0].id, session_factory=session_factory)

    order, b_bids = _create_test_order_with_billing(session, buyer, 2, ref_code="IDEMPROOT")

    # First execution via process_order_cashback
    results1 = PlanACashbackService.process_order_cashback(order.id, session_factory=session_factory)
    assert all(r.status == "CONTRIBUTED" for r in results1)

    # Repeated webhook / callback 1
    results2 = PlanACashbackService.process_order_cashback(order.id, session_factory=session_factory)
    assert all(r.status == "ALREADY_PROCESSED" for r in results2)

    # Repeated callback 2 on individual billing ID
    res_single = PlanACashbackService.process_billing_id(b_bids[0].id, session_factory=session_factory)
    assert res_single.status == "ALREADY_PROCESSED"

    # Exactly 2 contributions recorded
    assert session.query(PlanACashbackContribution).count() == 2


# ---------------------------------------------------------------------------
# Test 8: Server restart during contribution processing
# ---------------------------------------------------------------------------
def test_08_server_restart_during_contribution_processing(tmp_path):
    db_file = tmp_path / "server_restart.db"
    engine1 = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine1)
    SessionMaker1 = sessionmaker(bind=engine1, autocommit=False, autoflush=False)

    s1 = SessionMaker1()
    root = _create_test_user(s1, "9820000001", "Restart Root", "RSTROOT")
    buyer = _create_test_user(s1, "9820000002", "Restart Buyer", "RSTBUY")
    s1.add(ReferralRelationship(referee_id=buyer.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="RSTROOT", binding_channel="checkout", is_active=True))
    s1.commit()

    _, r_bids = _create_test_order_with_billing(s1, root, 1)
    PlanACashbackService.process_billing_id(r_bids[0].id, session_factory=SessionMaker1)

    _, b_bids = _create_test_order_with_billing(s1, buyer, 16, ref_code="RSTROOT")
    b_ids = [bid.id for bid in b_bids]
    root_id = root.id

    # Process first 8 before restart
    for bid_id in b_ids[:8]:
        PlanACashbackService.process_billing_id(bid_id, session_factory=SessionMaker1)

    s1.close()
    engine1.dispose()

    # SIMULATE SERVER RESTART: Create completely new engine and session factory
    engine2 = create_engine(f"sqlite:///{db_file}")
    SessionMaker2 = sessionmaker(bind=engine2, autocommit=False, autoflush=False)

    # Process remaining 8 after restart
    for bid_id in b_ids[8:]:
        res = PlanACashbackService.process_billing_id(bid_id, session_factory=SessionMaker2)
        assert res.status == "CONTRIBUTED"

    s2 = SessionMaker2()
    cyc = s2.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == root_id).first()
    assert cyc.completed_contributions == 16
    assert cyc.status == "COMPLETED"

    w = s2.query(Wallet).filter(Wallet.user_id == root_id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION).first()
    assert w.balance == Decimal("4000.00")
    s2.close()
    engine2.dispose()


# ---------------------------------------------------------------------------
# Test 9: Recovery of interrupted contributions
# ---------------------------------------------------------------------------
def test_09_recovery_of_interrupted_contributions(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9830000001", "Recov Root", "RECROOT")
    buyer = _create_test_user(session, "9830000002", "Recov Buyer", "RECBUY")
    session.add(ReferralRelationship(referee_id=buyer.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="RECROOT", binding_channel="checkout", is_active=True))
    session.commit()

    _, r_bids = _create_test_order_with_billing(session, root, 1)
    PlanACashbackService.process_billing_id(r_bids[0].id, session_factory=session_factory)

    order, b_bids = _create_test_order_with_billing(session, buyer, 4, ref_code="RECROOT")

    # Simulate interruption: only first 2 were processed before network timeout
    PlanACashbackService.process_billing_id(b_bids[0].id, session_factory=session_factory)
    PlanACashbackService.process_billing_id(b_bids[1].id, session_factory=session_factory)

    # Recovery sweep runs for the entire order
    recovery_results = PlanACashbackService.process_order_cashback(order.id, session_factory=session_factory)

    assert recovery_results[0].status == "ALREADY_PROCESSED"
    assert recovery_results[1].status == "ALREADY_PROCESSED"
    assert recovery_results[2].status == "CONTRIBUTED"
    assert recovery_results[3].status == "CONTRIBUTED"

    assert session.query(PlanACashbackContribution).count() == 4


# ---------------------------------------------------------------------------
# Test 10: Completion of three consecutive cycles for one beneficiary (monotonic numbering)
# ---------------------------------------------------------------------------
def test_10_completion_of_three_consecutive_cycles_for_one_beneficiary(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9840000001", "Three Cyc Root", "THREEROOT")
    buyer = _create_test_user(session, "9840000002", "Three Cyc Buyer", "THREEBUY")
    session.add(ReferralRelationship(referee_id=buyer.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="THREEROOT", binding_channel="checkout", is_active=True))
    session.commit()

    # Root has 3 queue entries
    _, root_bids = _create_test_order_with_billing(session, root, 3)
    for bid in root_bids:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    # Buyer purchases 48 units (16 * 3)
    _, buyer_bids = _create_test_order_with_billing(session, buyer, 48, ref_code="THREEROOT")
    for bid in buyer_bids:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    cycles = session.query(PlanACashbackCycle).filter(PlanACashbackCycle.recipient_user_id == root.id).order_by(PlanACashbackCycle.id.asc()).all()
    assert len(cycles) == 3
    assert [c.cycle_number for c in cycles] == [1, 2, 3]
    assert all(c.status == "COMPLETED" for c in cycles)
    assert all(c.completed_contributions == 16 for c in cycles)

    w = session.query(Wallet).filter(Wallet.user_id == root.id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION).first()
    assert w.balance == Decimal("12000.00")


# ---------------------------------------------------------------------------
# Test 11: Correct transition from one beneficiary to the next (graduation & advancement)
# ---------------------------------------------------------------------------
def test_11_correct_transition_from_one_beneficiary_to_the_next(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9850000001", "Grad Root", "GRADROOT")
    c2 = _create_test_user(session, "9850000002", "Grad Next", "GRADNEXT")
    c3 = _create_test_user(session, "9850000003", "Grad Downline", "GRADDOWN")

    session.add(ReferralRelationship(referee_id=c2.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="GRADROOT", binding_channel="checkout", is_active=True))
    session.add(ReferralRelationship(referee_id=c3.id, referrer_id=c2.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="GRADNEXT", binding_channel="checkout", is_active=True))
    session.commit()

    # Root has 16 items
    _, root_bids = _create_test_order_with_billing(session, root, 16)
    for bid in root_bids:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    # C2 has 1 item (enqueued at position 17)
    _, c2_bids = _create_test_order_with_billing(session, c2, 1, ref_code="GRADROOT")
    PlanACashbackService.process_billing_id(c2_bids[0].id, session_factory=session_factory)

    # C3 purchases 47 items (1 from C2 + 47 from C3 = 48 contributions total to Root)
    _, c3_bids = _create_test_order_with_billing(session, c3, 47, ref_code="GRADNEXT")
    for bid in c3_bids[:46]:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    # 48th contribution total (c3_bids[46]) completes Root's 3rd cycle
    res48 = PlanACashbackService.process_billing_id(c3_bids[46].id, session_factory=session_factory)
    assert res48.status == "CONTRIBUTED"
    assert res48.recipient_user_id == root.id
    assert res48.cycle_completed is True

    # C4 registers under C3 and purchases 1 item (49th contribution in queue)
    c4 = _create_test_user(session, "9850000004", "Grad C4", "GRADC4")
    session.add(ReferralRelationship(referee_id=c4.id, referrer_id=c3.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="GRADDOWN", binding_channel="checkout", is_active=True))
    session.commit()

    _, c4_bids = _create_test_order_with_billing(session, c4, 1, ref_code="GRADDOWN")
    # 49th contribution: Root has completed 3 cycles and graduates. Next recipient is C2!
    res49 = PlanACashbackService.process_billing_id(c4_bids[0].id, session_factory=session_factory)
    assert res49.status == "CONTRIBUTED"
    assert res49.recipient_user_id == c2.id

    c2_cycle = session.query(PlanACashbackCycle).filter(PlanACashbackCycle.id == res49.cycle_id).first()
    c2_entry = session.query(PlanACashbackEntry).filter(PlanACashbackEntry.billing_id == c2_bids[0].id).first()
    assert c2_cycle.queue_entry_id == c2_entry.id
    assert c2_cycle.recipient_user_id == c2.id


# ---------------------------------------------------------------------------
# Test 12: Correct wallet and ledger reconciliation after withdrawals
# ---------------------------------------------------------------------------
def test_12_wallet_and_ledger_reconciliation_after_withdrawals(multi_user_db):
    session, session_factory, _ = multi_user_db

    root = _create_test_user(session, "9860000001", "Withdr Root", "WDROOT")
    buyer = _create_test_user(session, "9860000002", "Withdr Buyer", "WDBUY")
    session.add(ReferralRelationship(referee_id=buyer.id, referrer_id=root.id, referee_programme=Programme.PLAN_A, referrer_programme=Programme.PLAN_A, referral_code_used="WDROOT", binding_channel="checkout", is_active=True))
    session.commit()

    _, r_bids = _create_test_order_with_billing(session, root, 3)
    for bid in r_bids:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    # Buyer purchases 48 units in a single order (completing all 3 cycles)
    _, b_bids = _create_test_order_with_billing(session, buyer, 48, ref_code="WDROOT")

    # Complete Cycle 1 & Cycle 2 (first 32 contributions = ₹8,000)
    for bid in b_bids[:32]:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    wallet = session.query(Wallet).filter(Wallet.user_id == root.id, Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION).first()
    assert wallet.balance == Decimal("8000.00")
    assert wallet.total_withdrawn == Decimal("0.00")

    # Withdraw ₹8,000 using domain service
    wd = execute_simulated_withdrawal(
        db=session,
        customer=root,
        wallet_type=WalletType.SEQUENTIAL_COMMISSION,
        idempotency_key="WTX-WD-TEST-001",
    )
    session.commit()

    assert wallet.balance == Decimal("0.00")
    assert wallet.total_withdrawn == Decimal("8000.00")

    # Complete Cycle 3 (remaining 16 contributions = ₹4,000)
    for bid in b_bids[32:]:
        PlanACashbackService.process_billing_id(bid.id, session_factory=session_factory)

    session.refresh(wallet)
    assert wallet.balance == Decimal("4000.00")
    assert wallet.total_withdrawn == Decimal("8000.00")
    # Total earned across cycles = balance (4000) + total_withdrawn (8000) = 12000
    assert wallet.balance + wallet.total_withdrawn == Decimal("12000.00")

    txs = session.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet.id).all()
    credits = [t for t in txs if t.transaction_type == WalletTransactionType.CREDIT]
    debits = [t for t in txs if t.transaction_type == WalletTransactionType.DEBIT]
    assert len(credits) == 3
    assert len(debits) == 1
    assert debits[0].amount == Decimal("8000.00")


# ---------------------------------------------------------------------------
# Test 13: Customer Session & Dashboard API Isolation
# ---------------------------------------------------------------------------
def test_13_customer_session_and_dashboard_api_isolation(api_client: TestClient, db_session: Session):
    u1 = _create_test_user(db_session, "9910000001", "User One", "UONE1")
    u2 = _create_test_user(db_session, "9920000002", "User Two", "UTWO2")
    db_session.commit()

    t1 = create_access_token(user_id=u1.id, role=u1.role.value, phone=u1.phone)
    t2 = create_access_token(user_id=u2.id, role=u2.role.value, phone=u2.phone)

    r1 = api_client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {t1}"})
    assert r1.status_code == 200

    r2 = api_client.get("/api/v1/cashback/progress", headers={"Authorization": f"Bearer {t2}"})
    assert r2.status_code == 200

    data1, data2 = r1.json(), r2.json()
    assert data1["cycle_status"] in ["NO_CYCLE", "WAITING", "ACTIVE", "COMPLETED"]
    assert data2["cycle_status"] in ["NO_CYCLE", "WAITING", "ACTIVE", "COMPLETED"]
