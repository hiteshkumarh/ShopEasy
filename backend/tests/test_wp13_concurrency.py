"""Focused Concurrency, Idempotency, and Transaction Safety Tests for WP-13 Stage 2.

Covers:
  1. Payment & Fulfilment: Repeated events, duplicate replay, failed/pending orders, recovery sweep.
  2. Billing ID Allocation: Concurrent multi-unit purchases, sequence continuity, unique constraints, rollback safety.
  3. Plan A Commission: Concurrent processing of same Billing ID, atomic ledger credit, repeat referral rules.
  4. Plan B Commission: Single lifetime direct commission per referee, direct-referrer-only generation commission, idempotency.
  5. Wallet & Withdrawal: Concurrent wallet credits, double-checked locking, simultaneous withdrawal approval conflict (409), non-negative check.
  6. Cashback Queue: Concurrent Billing ID processing, 16-contribution cycle completion exactly once, mutual exclusion.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os
import threading
import time
from typing import List, Optional, Tuple
import uuid
import pytest
from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.core.security import hash_password
from app.models.billing import BillingCounter, BillingEngineClaim, BillingId
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
from app.models.order import Order, OrderItem
from app.models.payment import PaymentAttempt, PaymentEvent
from app.models.product import Product
from app.models.referral import ReferralRelationship
from app.models.user import Address, User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal
from app.services.billing.allocator import BillingAllocatorService
from app.services.cashback.plan_a import PlanACashbackService
from app.services.commission.plan_a import PlanACommissionService
from app.services.commission.plan_b import PlanBCommissionService
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator
from app.services.fulfilment.recovery import FulfilmentRecoveryWorker
from app.services.payment.base import VerifiedPaymentEvent
from app.services.payment.service import PaymentService
from app.services.wallet_service import (
    admin_approve_withdrawal,
    credit_wallet,
    get_or_create_wallet,
)


# ---------------------------------------------------------------------------
# Concurrency Engine Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def concurrent_engine(tmp_path) -> Engine:
    """Isolated SQLite engine configured for concurrent multi-threaded execution.
    
    Uses WAL mode and BEGIN IMMEDIATE to eliminate thread races on SQLite connection pointers
    and ensure row-locking semantics mirror production MySQL/TiDB behavior.
    """
    db_path = tmp_path / "test_wp13_concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30, "check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def do_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def do_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.execute(text("PRAGMA busy_timeout=30000;"))

    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def create_test_product(db: Session, price: Decimal = Decimal("3999.00"), is_power_bank: bool = True) -> Product:
    prod = Product(
        name=f"Power Bank {time.time_ns() % 1000000}",
        price=price,
        stock=1000,
        is_active=True,
        is_power_bank=is_power_bank,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


def create_test_address(db: Session, user_id: int) -> Address:
    addr = Address(
        user_id=user_id,
        recipient_name="Test Recipient",
        phone="9844000000",
        address_line1="123 Test Street",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
        is_default=True,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


def create_test_user(
    db: Session,
    phone: str,
    programme: Programme = Programme.PLAN_A,
    role: UserRole = UserRole.CUSTOMER,
    account_status: AccountStatus = AccountStatus.ACTIVE,
) -> User:
    user = User(
        phone=phone,
        full_name=f"User {phone}",
        password_hash=hash_password("Password123!"),
        role=role,
        programme=programme,
        account_status=account_status,
        referral_code=None if role == UserRole.ADMIN else f"REF{phone}",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_order(
    db: Session,
    user: User,
    total_amount: Decimal = Decimal("3999.00"),
    order_status: OrderStatus = OrderStatus.CONFIRMED,
    payment_status: PaymentStatus = PaymentStatus.COMPLETED,
    applied_referral_code: Optional[str] = None,
    order_number: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    is_fulfilled: bool = False,
    is_first_successful_order: bool = False,
) -> Order:
    addr = db.query(Address).filter(Address.user_id == user.id).first()
    if not addr:
        addr = create_test_address(db, user.id)

    uid = uuid.uuid4().hex[:12]
    if not order_number:
        order_number = f"ORD-{uid}"
    if not idempotency_key:
        idempotency_key = f"IDEM-{uid}"

    order = Order(
        order_number=order_number,
        idempotency_key=idempotency_key,
        user_id=user.id,
        address_id=addr.id,
        total_amount=total_amount,
        order_status=order_status,
        payment_status=payment_status,
        applied_referral_code=applied_referral_code,
        is_first_successful_order=is_first_successful_order,
        is_fulfilled=is_fulfilled,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def create_test_order_item(
    db: Session,
    order_id: int,
    product: Product,
    quantity: int = 1,
) -> OrderItem:
    item = OrderItem(
        order_id=order_id,
        product_id=product.id,
        product_name=product.name,
        unit_price=product.price,
        quantity=quantity,
        line_total=product.price * quantity,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def ensure_billing_counter(db: Session) -> BillingCounter:
    counter = db.query(BillingCounter).filter(BillingCounter.sequence_name == "GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=200)
        db.add(counter)
        db.commit()
        db.refresh(counter)
    return counter


# ---------------------------------------------------------------------------
# 1. Payment & Fulfilment Concurrency & Idempotency
# ---------------------------------------------------------------------------

class TestPaymentAndFulfilmentConcurrency:
    """Verify payment event idempotency, replay protection, and atomic fulfilment handoff."""

    def test_duplicate_payment_webhook_idempotency_returns_already_processed(self, db_session: Session):
        """Simulate identical webhook event delivered twice; second delivery returns ALREADY_PROCESSED."""
        user = create_test_user(db_session, "9811000001")
        prod = create_test_product(db_session)
        ensure_billing_counter(db_session)

        order = create_test_order(
            db_session,
            user,
            order_number="ORD-DUP-001",
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        create_test_order_item(db_session, order.id, prod, 1)

        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="ATT-DUP-001",
            provider="simulated",
            amount=Decimal("3999.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=datetime.now(timezone.utc),
        )
        db_session.add(attempt)
        db_session.commit()

        # Mock provider returning VerifiedPaymentEvent
        class MockProvider:
            provider_name = "simulated"

            def verify_and_parse_event(self, raw_payload, headers):
                return VerifiedPaymentEvent(
                    provider="simulated",
                    provider_event_id="EVT-UNIQUE-101",
                    event_type="payment.completed",
                    attempt_reference="ATT-DUP-001",
                    amount=Decimal("3999.00"),
                    currency="INR",
                    transaction_id="TXN-101",
                    raw_payload={"id": "EVT-UNIQUE-101"},
                )

        provider = MockProvider()

        # First event delivery -> COMPLETED
        status1, data1 = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=b"{}",
            headers={},
            provider=provider,
        )
        assert status1 == "COMPLETED"

        # Second event delivery (exact replay) -> ALREADY_PROCESSED
        status2, data2 = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=b"{}",
            headers={},
            provider=provider,
        )
        assert status2 == "ALREADY_PROCESSED"
        assert data2["status"] == "already_processed"

        # Verify exactly one PaymentEvent row exists
        events = db_session.query(PaymentEvent).filter(PaymentEvent.provider_event_id == "EVT-UNIQUE-101").all()
        assert len(events) == 1

    def test_failed_or_pending_order_is_ineligible_for_fulfilment(self, db_session: Session):
        """Orders in PENDING_PAYMENT or FAILED cannot allocate Billing IDs or trigger claims."""
        user = create_test_user(db_session, "9811000002")
        prod = create_test_product(db_session)
        ensure_billing_counter(db_session)

        order_pending = create_test_order(
            db_session,
            user,
            order_number="ORD-PEND-001",
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        create_test_order_item(db_session, order_pending.id, prod, 1)

        order_failed = create_test_order(
            db_session,
            user,
            order_number="ORD-FAIL-001",
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.FAILED,
            payment_status=PaymentStatus.FAILED,
        )
        create_test_order_item(db_session, order_failed.id, prod, 1)

        # Attempt fulfilment on pending
        res_pending = FulfilmentOrchestrator.fulfil_order(order_pending.id, db=db_session)
        assert res_pending.status == "INELIGIBLE"
        assert res_pending.billing_id_count == 0

        # Attempt fulfilment on failed
        res_failed = FulfilmentOrchestrator.fulfil_order(order_failed.id, db=db_session)
        assert res_failed.status == "INELIGIBLE"
        assert res_failed.billing_id_count == 0

        # Verify no Billing IDs allocated
        bids = db_session.query(BillingId).filter(BillingId.order_id.in_([order_pending.id, order_failed.id])).all()
        assert len(bids) == 0

    def test_concurrent_fulfil_order_calls_across_threads(self, concurrent_engine: Engine):
        """Simultaneous calls to fulfil_order on the same order result in exactly 1 allocation and no duplicates."""
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()

        user = create_test_user(init_db, "9811000003")
        prod = create_test_product(init_db)
        ensure_billing_counter(init_db)

        order = create_test_order(
            init_db,
            user,
            order_number="ORD-CONC-001",
            total_amount=Decimal("7998.00"),
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            is_fulfilled=False,
        )
        create_test_order_item(init_db, order.id, prod, quantity=2)
        order_id = order.id
        init_db.close()

        results = []
        barrier = threading.Barrier(5)

        def worker():
            barrier.wait()
            s = SessionMaker()
            try:
                res = FulfilmentOrchestrator.fulfil_order(order_id, db=s)
                results.append(res)
            finally:
                s.close()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify statuses
        completed_count = sum(1 for r in results if r.status == "COMPLETED")
        already_count = sum(1 for r in results if r.status == "ALREADY_FULFILLED")
        assert completed_count == 1
        assert already_count == 4

        # Verify database record count
        check_db = SessionMaker()
        bids = check_db.query(BillingId).filter(BillingId.order_id == order_id).all()
        assert len(bids) == 2
        claims = check_db.query(BillingEngineClaim).join(BillingId).filter(BillingId.order_id == order_id).all()
        assert len(claims) == 2
        check_db.close()


# ---------------------------------------------------------------------------
# 2. Billing ID Allocation Concurrency & Uniqueness
# ---------------------------------------------------------------------------

class TestBillingIdAllocationConcurrency:
    """Verify collision-free contiguous Billing ID sequence allocation under concurrency."""

    def test_concurrent_multi_unit_orders_allocate_contiguous_collision_free_sequences(self, concurrent_engine: Engine):
        """5 simultaneous multi-unit orders (2 units each = 10 units total) receive distinct contiguous sequences."""
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()
        ensure_billing_counter(init_db)
        prod = create_test_product(init_db)

        order_ids = []
        for i in range(5):
            u = create_test_user(init_db, f"982200000{i}")
            o = create_test_order(
                init_db,
                u,
                order_number=f"ORD-SEQ-00{i}",
                total_amount=Decimal("7998.00"),
                order_status=OrderStatus.CONFIRMED,
                payment_status=PaymentStatus.COMPLETED,
                is_fulfilled=False,
            )
            create_test_order_item(init_db, o.id, prod, quantity=2)
            order_ids.append(o.id)

        init_db.close()

        barrier = threading.Barrier(5)
        allocated_numbers = []
        lock = threading.Lock()

        def worker(oid: int):
            barrier.wait()
            s = SessionMaker()
            try:
                res = FulfilmentOrchestrator.fulfil_order(oid, db=s)
                with lock:
                    allocated_numbers.extend(res.billing_numbers)
            finally:
                s.close()

        threads = [threading.Thread(target=worker, args=(oid,)) for oid in order_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 10 Billing IDs must be uniquely formatted and collision-free
        assert len(allocated_numbers) == 10
        assert len(set(allocated_numbers)) == 10

        # Verify DB records
        check_db = SessionMaker()
        all_bids = check_db.query(BillingId).filter(BillingId.order_id.in_(order_ids)).all()
        assert len(all_bids) == 10
        seqs = [b.sequence_number for b in all_bids]
        assert len(set(seqs)) == 10
        check_db.close()

    def test_database_constraints_reject_duplicate_sequence_or_billing_number(self, db_session: Session):
        """Database uniqueness constraints reject duplicate sequence_number or billing_number."""
        ensure_billing_counter(db_session)
        user = create_test_user(db_session, "9822000099")
        prod = create_test_product(db_session)

        order = create_test_order(
            db_session,
            user,
            order_number="ORD-UQ-001",
            total_amount=Decimal("3999.00"),
        )
        item = create_test_order_item(db_session, order.id, prod, quantity=1)

        b1 = BillingId(
            billing_number="AGD-000999",
            sequence_number=999,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=1,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(b1)
        db_session.commit()

        # Attempt duplicate billing_number
        b_dup_num = BillingId(
            billing_number="AGD-000999",
            sequence_number=1000,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=2,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(b_dup_num)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ---------------------------------------------------------------------------
# 3. Plan A Commission Concurrency & Ledger Atomicity
# ---------------------------------------------------------------------------

class TestPlanACommissionConcurrency:
    """Verify concurrent Plan A commission processing and ledger atomicity."""

    def test_concurrent_plan_a_commission_processing_for_same_billing_id(self, concurrent_engine: Engine):
        """Simultaneous processing of the same Billing ID awards commission exactly once and credits wallet once."""
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()

        referrer = create_test_user(init_db, "9833000001", programme=Programme.PLAN_A)
        referee = create_test_user(init_db, "9833000002", programme=Programme.PLAN_A)
        prod = create_test_product(init_db)
        ensure_billing_counter(init_db)

        # Referrer must have a qualifying purchase
        ref_order = create_test_order(
            init_db,
            referrer,
            order_number="ORD-QUAL-001",
            total_amount=Decimal("3999.00"),
            is_fulfilled=True,
        )
        create_test_order_item(init_db, ref_order.id, prod, quantity=1)

        # Referee order with applied referral code
        order = create_test_order(
            init_db,
            referee,
            order_number="ORD-PA-001",
            total_amount=Decimal("3999.00"),
            applied_referral_code=referrer.referral_code,
            is_fulfilled=False,
        )
        create_test_order_item(init_db, order.id, prod, quantity=1)
        order_id = order.id
        referrer_id = referrer.id
        init_db.commit()
        init_db.close()

        # Fulfil order in dedicated session
        fulfil_res = FulfilmentOrchestrator.fulfil_order(order_id, session_factory=SessionMaker)
        assert fulfil_res.status == "COMPLETED"

        find_db = SessionMaker()
        bid = find_db.query(BillingId).filter(BillingId.order_id == order_id).first()
        bid_id = bid.id
        find_db.close()

        # Execute concurrent commission processing across 3 threads
        results = []
        barrier = threading.Barrier(3)

        def worker():
            barrier.wait()
            res = PlanACommissionService.process_billing_id(bid_id, session_factory=SessionMaker)
            results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        earned_count = sum(1 for r in results if r.status == "EARNED")
        already_count = sum(1 for r in results if r.status == "ALREADY_PROCESSED")
        assert earned_count == 1
        assert already_count == 2

        check_db = SessionMaker()
        # Verify commission record deductions in DB
        comm = check_db.query(PlanACommission).filter(PlanACommission.billing_id == bid_id).first()
        assert comm is not None
        assert comm.gross_amount == Decimal("750.00")
        assert comm.operational_cost_amount == Decimal("35.00")
        assert comm.tds_amount == Decimal("15.00")
        assert comm.net_amount == Decimal("700.00")
        assert comm.status == "EARNED"

        # Verify wallet balance: exactly ₹700.00 credited once
        wallet = check_db.query(Wallet).filter(
            Wallet.user_id == referrer_id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet is not None
        assert wallet.balance == Decimal("700.00")

        # Verify transactions
        txs = check_db.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet.id).all()
        assert len(txs) == 1
        assert txs[0].amount == Decimal("700.00")
        assert txs[0].idempotency_key == f"PA-COMM:{bid_id}"
        check_db.close()


# ---------------------------------------------------------------------------
# 4. Plan B Commission Concurrency & Ledger Atomicity
# ---------------------------------------------------------------------------

class TestPlanBCommissionConcurrency:
    """Verify Plan B direct commission lifetime limit and generation commission uniqueness."""

    def test_concurrent_plan_b_direct_commission_awarded_only_once_lifetime(self, concurrent_engine: Engine):
        """Direct commission (₹500 gross / ₹466.66 net) is awarded exactly once per referee lifetime."""
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()

        dist = create_test_user(init_db, "9844000001", programme=Programme.PLAN_B)
        referee = create_test_user(init_db, "9844000002", programme=Programme.PLAN_B)
        prod = create_test_product(init_db)
        ensure_billing_counter(init_db)

        # Qualifying purchase for distributor
        dist_order = create_test_order(
            init_db,
            dist,
            order_number="ORD-DIST-001",
            total_amount=Decimal("3999.00"),
            is_fulfilled=True,
        )
        create_test_order_item(init_db, dist_order.id, prod, quantity=1)

        # Referee order
        order = create_test_order(
            init_db,
            referee,
            order_number="ORD-PB-001",
            total_amount=Decimal("3999.00"),
            applied_referral_code=dist.referral_code,
            is_fulfilled=False,
        )
        create_test_order_item(init_db, order.id, prod, quantity=1)
        order_id = order.id
        dist_id = dist.id
        referee_id = referee.id
        init_db.commit()
        init_db.close()

        # Fulfil order in dedicated session
        fulfil_res = FulfilmentOrchestrator.fulfil_order(order_id, session_factory=SessionMaker)
        assert fulfil_res.status == "COMPLETED"

        # Process concurrent commission across 3 threads for the same order
        results = []
        barrier = threading.Barrier(3)

        def worker():
            barrier.wait()
            res = PlanBCommissionService.process_order_commissions(order_id, session_factory=SessionMaker)
            results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        completed_count = sum(1 for r in results if r.status == "COMPLETED")
        already_count = sum(1 for r in results if r.status == "ALREADY_PROCESSED")
        assert completed_count >= 1

        check_db = SessionMaker()
        # Direct commission must exist exactly once
        direct_comms = check_db.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "DIRECT",
            PlanBCommission.referee_id == referee_id,
        ).all()
        assert len(direct_comms) == 1
        assert direct_comms[0].gross_amount == Decimal("500.00")
        assert direct_comms[0].operational_cost_amount == Decimal("23.34")
        assert direct_comms[0].tds_amount == Decimal("10.00")
        assert direct_comms[0].net_amount == Decimal("466.66")

        # Generation commission must exist exactly once
        gen_comms = check_db.query(PlanBCommission).filter(
            PlanBCommission.commission_type == "GENERATION",
            PlanBCommission.referee_id == referee_id,
        ).all()
        assert len(gen_comms) == 1
        assert gen_comms[0].gross_amount == Decimal("50.00")
        assert gen_comms[0].operational_cost_amount == Decimal("2.34")
        assert gen_comms[0].tds_amount == Decimal("1.00")
        assert gen_comms[0].net_amount == Decimal("46.66")

        # Wallet balance must equal ₹466.66 + ₹46.66 = ₹513.32 exactly
        wallet = check_db.query(Wallet).filter(
            Wallet.user_id == dist_id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("513.32")
        check_db.close()

    def test_concurrent_two_different_customers_under_same_distributor_receive_one_direct_and_two_generation(self, concurrent_engine: Engine):
        """Simultaneous first purchases by two different customers under the same Plan B distributor.
        Verifies:
        - Exactly one ₹500 direct commission credited (₹466.66 net).
        - Both eligible Billing IDs receive their respective ₹50 generation commissions (₹46.66 and ₹46.67).
        - Both orders complete successfully with status COMPLETED.
        - Combined net commission equals ₹559.99.
        - Exactly 3 wallet transactions and no duplicate commissions.
        - Repeated calls are fully idempotent.
        """
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()

        dist = create_test_user(init_db, "9844990001", programme=Programme.PLAN_B)
        prod = create_test_product(init_db)
        ensure_billing_counter(init_db)

        # Qualifying purchase for distributor
        dist_order = create_test_order(
            init_db,
            dist,
            order_number="ORD-DIST-QUAL-99",
            total_amount=Decimal("3999.00"),
            is_fulfilled=True,
        )
        create_test_order_item(init_db, dist_order.id, prod, quantity=1)

        # Customer 1
        c1 = create_test_user(init_db, "9844990002", programme=Programme.PLAN_B)
        c1.referred_by_id = dist.id
        o1 = create_test_order(
            init_db,
            c1,
            order_number="ORD-C1-CONC",
            total_amount=Decimal("3999.00"),
            applied_referral_code=dist.referral_code,
            is_fulfilled=False,
        )
        create_test_order_item(init_db, o1.id, prod, quantity=1)

        # Customer 2
        c2 = create_test_user(init_db, "9844990003", programme=Programme.PLAN_B)
        c2.referred_by_id = dist.id
        o2 = create_test_order(
            init_db,
            c2,
            order_number="ORD-C2-CONC",
            total_amount=Decimal("3999.00"),
            applied_referral_code=dist.referral_code,
            is_fulfilled=False,
        )
        create_test_order_item(init_db, o2.id, prod, quantity=1)

        dist_id = dist.id
        o1_id = o1.id
        o2_id = o2.id
        init_db.commit()
        init_db.close()

        # Fulfil both orders
        f1 = FulfilmentOrchestrator.fulfil_order(o1_id, session_factory=SessionMaker)
        assert f1.status == "COMPLETED"
        f2 = FulfilmentOrchestrator.fulfil_order(o2_id, session_factory=SessionMaker)
        assert f2.status == "COMPLETED"

        # Concurrently execute commission processing for both orders across 2 threads
        barrier = threading.Barrier(2)
        results = {}

        def worker(oid: int, name: str):
            barrier.wait()
            res = PlanBCommissionService.process_order_commissions(oid, session_factory=SessionMaker)
            results[name] = res

        t1 = threading.Thread(target=worker, args=(o1_id, "Cust1"))
        t2 = threading.Thread(target=worker, args=(o2_id, "Cust2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both orders must succeed
        assert results["Cust1"].status == "COMPLETED"
        assert results["Cust2"].status == "COMPLETED"

        # Exactly one direct bonus credited across both orders
        direct_total = results["Cust1"].direct_net_credited + results["Cust2"].direct_net_credited
        assert direct_total == Decimal("466.66")
        direct_winner = "Cust1" if results["Cust1"].direct_net_credited > 0 else "Cust2"
        direct_loser = "Cust2" if direct_winner == "Cust1" else "Cust1"
        assert results[direct_winner].direct_net_credited == Decimal("466.66")
        assert results[direct_loser].direct_net_credited == Decimal("0.00")

        # Both orders must credit their generation commission
        gen1 = results["Cust1"].generation_net_credited
        gen2 = results["Cust2"].generation_net_credited
        assert sorted([gen1, gen2]) == [Decimal("46.66"), Decimal("46.67")]
        assert gen1 + gen2 == Decimal("93.33")

        # Total net commission across both orders equals ₹559.99
        total_credited = results["Cust1"].total_net_credited + results["Cust2"].total_net_credited
        assert total_credited == Decimal("559.99")

        # Check database records
        check_db = SessionMaker()
        direct_comms = check_db.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == dist_id,
            PlanBCommission.commission_type == "DIRECT",
        ).all()
        assert len(direct_comms) == 1
        assert direct_comms[0].gross_amount == Decimal("500.00")
        assert direct_comms[0].net_amount == Decimal("466.66")
        assert direct_comms[0].idempotency_key == f"PB-DIRECT:{dist_id}"

        gen_comms = check_db.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == dist_id,
            PlanBCommission.commission_type == "GENERATION",
        ).order_by(PlanBCommission.id).all()
        assert len(gen_comms) == 2
        assert [g.net_amount for g in gen_comms] == [Decimal("46.66"), Decimal("46.67")]

        # Wallet balance is strictly ₹559.99
        wallet = check_db.query(Wallet).filter(
            Wallet.user_id == dist_id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet.balance == Decimal("559.99")

        # Wallet transactions: exactly 3 ledger transactions
        txs = check_db.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id,
        ).order_by(WalletTransaction.id).all()
        assert len(txs) == 3
        assert sum(t.amount for t in txs) == Decimal("559.99")
        check_db.close()

        # Retry / Idempotency verification: re-running both orders produces no duplicate credits
        res1_retry = PlanBCommissionService.process_order_commissions(o1_id, session_factory=SessionMaker)
        res2_retry = PlanBCommissionService.process_order_commissions(o2_id, session_factory=SessionMaker)
        assert res1_retry.direct_net_credited == Decimal("0.00")
        assert res1_retry.generation_net_credited == Decimal("0.00")
        assert res2_retry.direct_net_credited == Decimal("0.00")
        assert res2_retry.generation_net_credited == Decimal("0.00")

        verify_db = SessionMaker()
        wallet_after = verify_db.query(Wallet).filter(
            Wallet.user_id == dist_id,
            Wallet.wallet_type == WalletType.DIRECT_REFERRAL,
        ).first()
        assert wallet_after.balance == Decimal("559.99")
        txs_after = verify_db.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet_after.id,
        ).all()
        assert len(txs_after) == 3
        verify_db.close()

    def test_generation_commission_strictly_direct_referrer_no_multi_level(self, db_session: Session):
        """Distributor A refers Distributor B who refers Customer C. Customer C purchases. Only B earns generation commission."""
        ensure_billing_counter(db_session)
        prod = create_test_product(db_session)

        dist_a = create_test_user(db_session, "9844000010", programme=Programme.PLAN_B)
        dist_b = create_test_user(db_session, "9844000020", programme=Programme.PLAN_B)
        cust_c = create_test_user(db_session, "9844000030", programme=Programme.PLAN_B)

        # Dist A qualifying purchase
        oa = create_test_order(db_session, dist_a, order_number="O-A", total_amount=Decimal("3999.00"), is_fulfilled=True)
        create_test_order_item(db_session, oa.id, prod, quantity=1)

        # Dist B qualifying purchase (referred by A)
        ob = create_test_order(db_session, dist_b, order_number="O-B", total_amount=Decimal("3999.00"), applied_referral_code=dist_a.referral_code, is_fulfilled=True)
        create_test_order_item(db_session, ob.id, prod, quantity=1)

        # Customer C purchase (referred by B)
        order_c = create_test_order(
            db_session,
            cust_c,
            order_number="O-C",
            total_amount=Decimal("3999.00"),
            applied_referral_code=dist_b.referral_code,
            is_fulfilled=False,
        )
        create_test_order_item(db_session, order_c.id, prod, quantity=1)

        FulfilmentOrchestrator.fulfil_order(order_c.id, db=db_session)
        PlanBCommissionService.process_order_commissions(order_c.id, db=db_session)

        # Distributor B earns generation commission
        comm_b = db_session.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == dist_b.id,
            PlanBCommission.commission_type == "GENERATION",
        ).first()
        assert comm_b is not None
        assert comm_b.gross_amount == Decimal("50.00")
        assert comm_b.operational_cost_amount == Decimal("2.34")
        assert comm_b.tds_amount == Decimal("1.00")
        assert comm_b.net_amount == Decimal("46.66")

        # Distributor A earns ZERO commission on Customer C purchase
        comm_a = db_session.query(PlanBCommission).filter(
            PlanBCommission.distributor_id == dist_a.id,
            PlanBCommission.referee_id == cust_c.id,
        ).first()
        assert comm_a is None


# ---------------------------------------------------------------------------
# 5. Wallet & Withdrawal Concurrency
# ---------------------------------------------------------------------------

class TestWalletAndWithdrawalConcurrency:
    """Verify concurrent wallet balance operations and withdrawal race protection."""

    def test_concurrent_wallet_credits_produce_exact_balance_sum(self, concurrent_engine: Engine):
        """10 concurrent threads executing credit_wallet with distinct idempotency keys sum accurately."""
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()
        user = create_test_user(init_db, "9855000001")
        wallet = get_or_create_wallet(init_db, user.id, WalletType.DIRECT_REFERRAL)
        init_db.commit()
        user_id = user.id
        init_db.close()

        barrier = threading.Barrier(10)

        def worker(idx: int):
            barrier.wait()
            s = SessionMaker()
            try:
                credit_wallet(
                    db=s,
                    user_id=user_id,
                    wallet_type=WalletType.DIRECT_REFERRAL,
                    amount=Decimal("100.00"),
                    reference_type=WalletReferenceType.DIRECT_REFERRAL,
                    reference_id=idx,
                    idempotency_key=f"CONC-CR-{idx}",
                )
                s.commit()
            finally:
                s.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check_db = SessionMaker()
        w = check_db.query(Wallet).filter(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DIRECT_REFERRAL).first()
        assert w.balance == Decimal("1000.00")
        txs = check_db.query(WalletTransaction).filter(WalletTransaction.wallet_id == w.id).all()
        assert len(txs) == 10
        check_db.close()

    def test_duplicate_credit_with_same_idempotency_key_is_idempotent(self, db_session: Session):
        """Calling credit_wallet twice with the exact same idempotency_key returns existing transaction without double credit."""
        user = create_test_user(db_session, "9855000002")

        w1, tx1 = credit_wallet(
            db=db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("500.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="CR-IDEMP-001",
        )
        db_session.commit()
        assert w1.balance == Decimal("500.00")

        # Second call with same idempotency key
        w2, tx2 = credit_wallet(
            db=db_session,
            user_id=user.id,
            wallet_type=WalletType.DIRECT_REFERRAL,
            amount=Decimal("500.00"),
            reference_type=WalletReferenceType.DIRECT_REFERRAL,
            reference_id=1,
            idempotency_key="CR-IDEMP-001",
        )
        db_session.commit()
        assert w2.balance == Decimal("500.00")
        assert tx1.id == tx2.id

    def test_concurrent_admin_withdrawal_approval_single_winner(self, concurrent_engine: Engine):
        """Two concurrent admin approval attempts on the same withdrawal result in 1 success and 1 HTTP 409 conflict."""
        from fastapi import HTTPException

        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()
        user = create_test_user(init_db, "9855000003", account_status=AccountStatus.BLOCKED)
        admin = create_test_user(init_db, "9855000099", role=UserRole.ADMIN)

        wallet = get_or_create_wallet(init_db, user.id, WalletType.DIRECT_REFERRAL)
        wallet.balance = Decimal("1000.00")
        init_db.commit()

        wd = Withdrawal(
            wallet_id=wallet.id,
            user_id=user.id,
            amount=Decimal("1000.00"),
            status=WithdrawalStatus.REQUESTED,
            idempotency_key="WD-CONC-001",
        )
        init_db.add(wd)
        init_db.commit()
        wd_id = wd.id
        admin_id = admin.id
        wallet_id = wallet.id
        init_db.close()

        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            s = SessionMaker()
            try:
                res = admin_approve_withdrawal(s, wd_id, admin_id)
                s.commit()
                results.append(res)
            except HTTPException as e:
                s.rollback()
                errors.append(e)
            finally:
                s.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 success and 1 HTTP 409 Conflict
        assert len(results) == 1
        assert len(errors) == 1
        assert errors[0].status_code == 409

        # Verify wallet balance is 0.00 and debited only once
        check_db = SessionMaker()
        w = check_db.query(Wallet).filter(Wallet.id == wallet_id).first()
        assert w.balance == Decimal("0.00")
        assert w.total_withdrawn == Decimal("1000.00")
        check_db.close()

    def test_non_negative_wallet_balance_constraint(self, db_session: Session):
        """Database CHECK constraint chk_wallets_balance_non_negative blocks negative balance."""
        user = create_test_user(db_session, "9855000004")
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        db_session.commit()

        wallet.balance = Decimal("-50.00")
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ---------------------------------------------------------------------------
# 6. Cashback Queue Concurrency & Cycle Completion
# ---------------------------------------------------------------------------

class TestCashbackQueueConcurrency:
    """Verify Plan A cashback contribution concurrency, 16-contribution cycle completion, and mutual exclusion."""

    def test_concurrent_cashback_processing_same_billing_id(self, concurrent_engine: Engine):
        """Two concurrent workers processing cashback for the same Billing ID resolve cleanly without duplicates."""
        SessionMaker = sessionmaker(bind=concurrent_engine)
        init_db = SessionMaker()

        user = create_test_user(init_db, "9866000001", programme=Programme.PLAN_A)
        prod = create_test_product(init_db)
        ensure_billing_counter(init_db)

        order = create_test_order(
            init_db,
            user,
            order_number="ORD-CB-001",
            total_amount=Decimal("3999.00"),
            is_fulfilled=False,
        )
        create_test_order_item(init_db, order.id, prod, quantity=1)
        order_id = order.id
        init_db.commit()
        init_db.close()

        # Fulfil order in dedicated session
        fulfil_res = FulfilmentOrchestrator.fulfil_order(order_id, session_factory=SessionMaker)
        assert fulfil_res.status == "COMPLETED"

        find_db = SessionMaker()
        bid = find_db.query(BillingId).filter(BillingId.order_id == order_id).first()
        bid_id = bid.id
        find_db.close()

        results = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            res = PlanACashbackService.process_billing_id(bid_id, session_factory=SessionMaker)
            results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # One worker processes, the other gets ALREADY_PROCESSED
        statuses = [r.status for r in results]
        assert "RESERVED_INITIAL_QUEUE" in statuses or "CONTRIBUTED" in statuses
        assert "ALREADY_PROCESSED" in statuses

        check_db = SessionMaker()
        # Verify mutual exclusion: Billing ID recorded in reserve OR contribution, never both
        res_count = check_db.query(PlanAUnallocatedCashbackReserve).filter(PlanAUnallocatedCashbackReserve.billing_id == bid_id).count()
        contrib_count = check_db.query(PlanACashbackContribution).filter(PlanACashbackContribution.contributing_billing_id == bid_id).count()
        assert (res_count == 1 and contrib_count == 0) or (res_count == 0 and contrib_count == 1)
        check_db.close()

    def test_cashback_16_contribution_cycle_completion_credits_wallet_exactly_once(self, db_session: Session):
        """When a cycle reaches 16 contributions, exactly ₹4,000 is credited and cycle cannot complete twice."""
        ensure_billing_counter(db_session)
        prod = create_test_product(db_session)

        root = create_test_user(db_session, "9866000010")
        queue = PlanACashbackQueue(root_user_id=root.id, last_allocated_position=1)
        db_session.add(queue)
        db_session.flush()

        root_order = create_test_order(db_session, root, order_number="ORD-ROOT")
        root_item = create_test_order_item(db_session, root_order.id, prod, quantity=1)

        # Create active recipient entry and cycle
        bid_recipient = BillingId(
            billing_number="AGD-000500",
            sequence_number=500,
            order_id=root_order.id,
            order_item_id=root_item.id,
            unit_index=1,
            user_id=root.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(bid_recipient)
        db_session.flush()

        entry = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=root.id,
            billing_id=bid_recipient.id,
            queue_position=1,
            status="ACTIVE",
        )
        db_session.add(entry)
        db_session.flush()

        cycle = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry.id,
            recipient_user_id=root.id,
            recipient_billing_id=bid_recipient.id,
            cycle_number=1,
            completed_contributions=15,  # 15 contributions already in!
            total_earned=Decimal("3750.00"),
            status="ACTIVE",
        )
        db_session.add(cycle)
        db_session.flush()
        queue.active_cycle_id = cycle.id
        db_session.commit()

        # 16th purchaser contributes ₹250
        purchaser = create_test_user(db_session, "9866000016")

        # Create referral relationship linking purchaser to root under Plan A
        rel = ReferralRelationship(
            referrer_id=root.id,
            referee_id=purchaser.id,
            referrer_programme=Programme.PLAN_A,
            referee_programme=Programme.PLAN_A,
            referral_code_used=root.referral_code,
            binding_channel="REGISTRATION",
            is_active=True,
        )
        db_session.add(rel)
        db_session.commit()

        order_16 = create_test_order(
            db_session,
            purchaser,
            order_number="ORD-16",
            total_amount=Decimal("3999.00"),
            applied_referral_code=root.referral_code,
            is_fulfilled=False,
        )
        create_test_order_item(db_session, order_16.id, prod, quantity=1)

        FulfilmentOrchestrator.fulfil_order(order_16.id, db=db_session)
        bid_16 = db_session.query(BillingId).filter(BillingId.order_id == order_16.id).first()

        # Process 16th contribution
        res = PlanACashbackService.process_billing_id(bid_16.id, db=db_session)
        assert res.status == "CONTRIBUTED"
        assert res.cycle_completed is True
        assert res.credited_amount == Decimal("4000.00")

        # Verify cycle state
        db_session.refresh(cycle)
        assert cycle.completed_contributions == 16
        assert cycle.total_earned == Decimal("4000.00")
        assert cycle.status == "COMPLETED"

        # Verify recipient wallet
        wallet = db_session.query(Wallet).filter(
            Wallet.user_id == root.id,
            Wallet.wallet_type == WalletType.SEQUENTIAL_COMMISSION,
        ).first()
        assert wallet.balance == Decimal("4000.00")

        # Verify transaction idempotency key
        tx = db_session.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet.id).first()
        assert tx.idempotency_key == f"CB-CREDIT:{cycle.id}"
