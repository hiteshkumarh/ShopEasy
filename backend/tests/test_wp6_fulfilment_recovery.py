"""Focused tests for WP-6.4 Fulfilment Recovery Worker & Scheduler."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import os
import threading
from typing import List
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.main import app
from app.models.billing import BillingCounter, BillingEngineClaim, BillingId
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.payment import PaymentAttempt
from app.models.product import Product
from app.models.user import Address, User
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator
from app.services.fulfilment.recovery import (
    FulfilmentRecoveryResult,
    FulfilmentRecoveryWorker,
)
from app.services.fulfilment.scheduler import (
    FulfilmentRecoveryScheduler,
    recovery_scheduler,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def seed_counter(db: Session, start_val: int = 200) -> BillingCounter:
    counter = db.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=start_val)
        db.add(counter)
        db.commit()
        db.refresh(counter)
    else:
        counter.current_value = start_val
        db.commit()
        db.refresh(counter)
    return counter


def make_user(
    db: Session,
    phone: str = "9876543211",
    programme: Programme = Programme.PLAN_A,
    referral_code: str = "PAREC01",
) -> User:
    user = User(
        phone=phone,
        password_hash="hashed_pw",
        full_name="Recovery Test User",
        role=UserRole.CUSTOMER,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=referral_code,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_product(
    db: Session,
    name: str = "Arya Smart Tracker",
    price: Decimal = Decimal("2999.00"),
    stock: int = 50,
) -> Product:
    product = Product(
        name=name,
        description="Test tracker",
        price=price,
        stock=stock,
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def make_address(db: Session, user: User) -> Address:
    address = Address(
        user_id=user.id,
        recipient_name=user.full_name,
        phone=user.phone,
        address_line1="100 Recovery Ave",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


def make_order_with_items(
    db: Session,
    user: User,
    quantities: List[int],
    order_status: OrderStatus = OrderStatus.CONFIRMED,
    payment_status: PaymentStatus = PaymentStatus.COMPLETED,
    is_fulfilled: bool = False,
    order_number: str = "ORD-REC-001",
    idempotency_key: str = "idemp-rec-001",
) -> tuple[Order, List[OrderItem], Product]:
    product = make_product(db, name=f"Product for {order_number}")
    address = make_address(db, user)

    total_amount = sum(Decimal(q) * product.price for q in quantities)
    order = Order(
        order_number=order_number,
        idempotency_key=idempotency_key,
        user_id=user.id,
        address_id=address.id,
        total_amount=total_amount,
        order_status=order_status,
        payment_status=payment_status,
        is_fulfilled=is_fulfilled,
        fulfilled_at=datetime.now(timezone.utc) if is_fulfilled else None,
    )
    db.add(order)
    db.flush()

    items = []
    for q in quantities:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=q,
            line_total=product.price * q,
        )
        db.add(item)
        items.append(item)

    db.commit()
    db.refresh(order)
    for it in items:
        db.refresh(it)
    return order, items, product


# ---------------------------------------------------------------------------
# Recovery Worker Unit & Lifecycle Tests
# ---------------------------------------------------------------------------

class TestFulfilmentRecoveryWorker:
    """Test suite for FulfilmentRecoveryWorker candidate selection and execution."""

    def test_finds_only_confirmed_completed_unfulfilled_orders(self, db_session):
        """Worker identifies only orders that are CONFIRMED, COMPLETED, and unfulfilled."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000001", programme=Programme.PLAN_A, referral_code="PAREC101")

        # 1. Eligible candidate
        order_eligible, _, _ = make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            is_fulfilled=False,
            order_number="ORD-ELIGIBLE",
            idempotency_key="idemp-el-1",
        )

        # 2. Ineligible: PENDING_PAYMENT
        order_pending, _, _ = make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            is_fulfilled=False,
            order_number="ORD-PENDING",
            idempotency_key="idemp-pend-1",
        )

        # 3. Ineligible: FAILED
        order_failed, _, _ = make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.FAILED,
            payment_status=PaymentStatus.FAILED,
            is_fulfilled=False,
            order_number="ORD-FAILED",
            idempotency_key="idemp-fail-1",
        )

        # 4. Ineligible: Already fulfilled
        order_fulfilled, _, _ = make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            is_fulfilled=True,
            order_number="ORD-ALREADY-FUL",
            idempotency_key="idemp-ful-1",
        )

        result = FulfilmentRecoveryWorker.run_sweep(db=db_session)

        assert result.candidates_found == 1
        assert result.orders_fulfilled == 1
        assert result.orders_failed == 0
        assert result.processed_order_ids == [order_eligible.id]

        db_session.refresh(order_eligible)
        assert order_eligible.is_fulfilled is True
        assert order_eligible.fulfilled_at is not None

        # Verify only 1 BillingId exists
        assert db_session.query(BillingId).count() == 1
        assert db_session.query(BillingId).filter_by(order_id=order_eligible.id).count() == 1

    def test_ignores_pending_failed_expired_unpaid_and_already_fulfilled(self, db_session):
        """Worker produces 0 candidates when only non-eligible orders exist."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000002", programme=Programme.PLAN_B, referral_code="PBREC102")

        # Create only non-eligible orders
        make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            is_fulfilled=False,
            order_number="ORD-IGN-1",
            idempotency_key="idemp-ign-1",
        )
        make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.FAILED,
            payment_status=PaymentStatus.FAILED,
            is_fulfilled=False,
            order_number="ORD-IGN-2",
            idempotency_key="idemp-ign-2",
        )
        make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,  # Unpaid confirmed order
            is_fulfilled=False,
            order_number="ORD-IGN-3",
            idempotency_key="idemp-ign-3",
        )
        make_order_with_items(
            db_session, user, [1],
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            is_fulfilled=True,  # Already fulfilled
            order_number="ORD-IGN-4",
            idempotency_key="idemp-ign-4",
        )

        result = FulfilmentRecoveryWorker.run_sweep(db=db_session)

        assert result.candidates_found == 0
        assert result.orders_fulfilled == 0
        assert result.orders_already_fulfilled == 0
        assert result.orders_failed == 0
        assert db_session.query(BillingId).count() == 0

    def test_successfully_retries_previously_failed_fulfilment(self, db_session):
        """Worker successfully retries and fulfills an order left unfulfilled by earlier crash."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000003", programme=Programme.PLAN_A, referral_code="PAREC103")

        # Simulate order confirmed during payment where synchronous handoff raised an exception
        order, items, prod = make_order_with_items(
            db_session, user, [2],
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.COMPLETED,
            is_fulfilled=False,
            order_number="ORD-RETRY-1",
            idempotency_key="idemp-ret-1",
        )

        # Worker sweeps and fulfills
        result = FulfilmentRecoveryWorker.run_sweep(db=db_session)

        assert result.candidates_found == 1
        assert result.orders_fulfilled == 1
        assert result.orders_failed == 0

        db_session.refresh(order)
        assert order.is_fulfilled is True
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 2
        assert db_session.query(BillingEngineClaim).count() == 2

    def test_one_failed_order_does_not_prevent_processing_rest_of_batch(self, db_session, monkeypatch):
        """If one order in a batch encounters an exception, other orders in the batch are still fulfilled."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000004", programme=Programme.PLAN_A, referral_code="PAREC104")

        order1, _, _ = make_order_with_items(
            db_session, user, [1], order_number="ORD-BATCH-1", idempotency_key="idemp-b-1"
        )
        order2, _, _ = make_order_with_items(
            db_session, user, [1], order_number="ORD-BATCH-2", idempotency_key="idemp-b-2"
        )
        order3, _, _ = make_order_with_items(
            db_session, user, [1], order_number="ORD-BATCH-3", idempotency_key="idemp-b-3"
        )

        orig_fulfil = FulfilmentOrchestrator.fulfil_order

        def failing_fulfil(order_id, *args, **kwargs):
            if order_id == order2.id:
                raise RuntimeError(f"Simulated transient error on order #{order_id}")
            return orig_fulfil(order_id, *args, **kwargs)

        monkeypatch.setattr(FulfilmentOrchestrator, "fulfil_order", failing_fulfil)

        result = FulfilmentRecoveryWorker.run_sweep(db=db_session)

        assert result.candidates_found == 3
        assert result.orders_fulfilled == 2
        assert result.orders_failed == 1
        assert result.failed_order_ids == [order2.id]
        assert len(result.errors) == 1

        db_session.refresh(order1)
        db_session.refresh(order2)
        db_session.refresh(order3)

        assert order1.is_fulfilled is True
        assert order2.is_fulfilled is False  # Failed order remains eligible for next sweep
        assert order3.is_fulfilled is True

    def test_repeated_recovery_runs_are_idempotent(self, db_session):
        """Repeated sweeps do not duplicate records or perform unnecessary re-allocations."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000005", programme=Programme.PLAN_A, referral_code="PAREC105")

        order, _, _ = make_order_with_items(
            db_session, user, [2], order_number="ORD-IDEMP-REC", idempotency_key="idemp-rec-dup"
        )

        # First run: fulfills the order
        res1 = FulfilmentRecoveryWorker.run_sweep(db=db_session)
        assert res1.candidates_found == 1
        assert res1.orders_fulfilled == 1

        # Second run: order is already is_fulfilled=True, not returned by candidate query
        res2 = FulfilmentRecoveryWorker.run_sweep(db=db_session)
        assert res2.candidates_found == 0
        assert res2.orders_fulfilled == 0

        # Billing IDs count remains 2
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 2

    def test_bounded_batch_size_is_respected(self, db_session):
        """Batch size limit is respected; remaining candidates are picked up in subsequent sweeps."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000006", programme=Programme.PLAN_A, referral_code="PAREC106")

        for i in range(5):
            make_order_with_items(
                db_session, user, [1], order_number=f"ORD-LIMIT-{i}", idempotency_key=f"idemp-lim-{i}"
            )

        # Sweep with batch_size=2
        res1 = FulfilmentRecoveryWorker.run_sweep(db=db_session, batch_size=2)
        assert res1.candidates_found == 2
        assert res1.orders_fulfilled == 2

        # Sweep with batch_size=2 (picks up next 2)
        res2 = FulfilmentRecoveryWorker.run_sweep(db=db_session, batch_size=2)
        assert res2.candidates_found == 2
        assert res2.orders_fulfilled == 2

        # Sweep with batch_size=2 (picks up last 1)
        res3 = FulfilmentRecoveryWorker.run_sweep(db=db_session, batch_size=2)
        assert res3.candidates_found == 1
        assert res3.orders_fulfilled == 1

        # Final sweep: 0 candidates
        res4 = FulfilmentRecoveryWorker.run_sweep(db=db_session, batch_size=2)
        assert res4.candidates_found == 0

    def test_independent_worker_sessions_are_closed(self, db_session):
        """Worker deterministically closes all sessions it instantiates."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000007", programme=Programme.PLAN_A, referral_code="PAREC107")
        order, _, _ = make_order_with_items(
            db_session, user, [1], order_number="ORD-SESS-CLOSE", idempotency_key="idemp-sess-close"
        )

        close_count = 0
        bind = db_session.get_bind()
        RealSession = sessionmaker(bind=bind, autocommit=False, autoflush=False)

        class TrackedSession(Session):
            def close(self):
                nonlocal close_count
                close_count += 1
                super().close()

        TrackedFactory = sessionmaker(bind=bind, class_=TrackedSession, autocommit=False, autoflush=False)

        result = FulfilmentRecoveryWorker.run_sweep(session_factory=TrackedFactory)
        assert result.orders_fulfilled == 1
        # At least 2 sessions opened and closed: 1 read session + 1 fulfilment orchestrator session
        assert close_count >= 2

    def test_crash_before_commit_leaves_order_eligible_for_retry(self, db_session, monkeypatch):
        """If a crash occurs before transaction commit, uncommitted mutations are rolled back and order is retryable."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000008", programme=Programme.PLAN_A, referral_code="PAREC108")
        order, _, _ = make_order_with_items(
            db_session, user, [1], order_number="ORD-CRASH-PRE", idempotency_key="idemp-crash-pre"
        )

        orig_flush = Session.flush
        flush_count = 0

        def failing_flush(session_self, *args, **kwargs):
            nonlocal flush_count
            flush_count += 1
            if flush_count == 2:
                raise RuntimeError("Simulated crash before commit during claim flush")
            return orig_flush(session_self, *args, **kwargs)

        monkeypatch.setattr(Session, "flush", failing_flush)

        # Sweep 1: Fails
        res1 = FulfilmentRecoveryWorker.run_sweep(db=db_session)
        assert res1.orders_failed == 1

        db_session.refresh(order)
        assert order.is_fulfilled is False
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 0

        # Restore normal flush
        monkeypatch.setattr(Session, "flush", orig_flush)

        # Sweep 2: Retries and succeeds
        res2 = FulfilmentRecoveryWorker.run_sweep(db=db_session)
        assert res2.orders_fulfilled == 1

        db_session.refresh(order)
        assert order.is_fulfilled is True
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 1

    def test_crash_after_commit_creates_no_duplicates_on_retry(self, db_session, monkeypatch):
        """If a crash occurs after commit, order remains fulfilled and retry creates no duplicate records."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9830000010", programme=Programme.PLAN_A, referral_code="PAREC110")
        order, _, _ = make_order_with_items(
            db_session, user, [2], order_number="ORD-CRASH-POST", idempotency_key="idemp-crash-post"
        )

        orig_fulfil = FulfilmentOrchestrator.fulfil_order
        first_call = True

        def crashing_after_commit(order_id, *args, **kwargs):
            nonlocal first_call
            res = orig_fulfil(order_id, *args, **kwargs)
            if first_call:
                first_call = False
                # Simulate caller/network crash immediately after orchestrator committed
                raise RuntimeError("Simulated crash immediately after commit")
            return res

        monkeypatch.setattr(FulfilmentOrchestrator, "fulfil_order", crashing_after_commit)

        # First sweep: orchestrator commits order, but crash happens during worker loop
        res1 = FulfilmentRecoveryWorker.run_sweep(db=db_session)
        assert res1.orders_failed == 1

        # In DB: order is durably fulfilled because orchestrator committed before the crash
        db_session.refresh(order)
        assert order.is_fulfilled is True
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 2

        # Second sweep: candidate query sees is_fulfilled=True, so it finds 0 candidates
        res2 = FulfilmentRecoveryWorker.run_sweep(db=db_session)
        assert res2.candidates_found == 0
        assert res2.orders_fulfilled == 0

        # Billing IDs remain exactly 2 (no duplicates)
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 2

    @pytest.mark.skipif(
        not os.getenv("TEST_MYSQL_URL"),
        reason="Row-locking concurrency test requires MySQL 8 (TEST_MYSQL_URL); SQLite does not support SELECT FOR UPDATE.",
    )
    @pytest.mark.mysql
    def test_concurrent_recovery_workers_do_not_duplicate(self):
        """Concurrent workers executing on the same candidate orders serialize safely via row locking."""
        mysql_url = os.getenv("TEST_MYSQL_URL")
        engine = create_engine(mysql_url, pool_pre_ping=True)
        Base.metadata.create_all(bind=engine)
        SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        with SessionMaker() as init_db:
            seed_counter(init_db, start_val=200)
            user = make_user(init_db, phone="9830000009", programme=Programme.PLAN_A, referral_code="PAREC109")
            order, _, _ = make_order_with_items(
                init_db, user, [2], order_number="ORD-CONC-REC", idempotency_key="idemp-conc-rec"
            )
            order_id = order.id

        results: List[FulfilmentRecoveryResult] = []
        lock = threading.Lock()

        def worker():
            res = FulfilmentRecoveryWorker.run_sweep(
                session_factory=SessionMaker,
                batch_size=10,
            )
            with lock:
                results.append(res)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 2
        total_fulfilled = sum(r.orders_fulfilled for r in results)
        total_already = sum(r.orders_already_fulfilled for r in results)

        # Exactly 1 worker fulfilled the order; the other worker either found 0 candidates or saw ALREADY_FULFILLED
        assert total_fulfilled == 1

        with SessionMaker() as verify_db:
            db_order = verify_db.query(Order).filter_by(id=order_id).first()
            assert db_order.is_fulfilled is True
            # Exactly 2 Billing IDs created (for quantity 2)
            assert verify_db.query(BillingId).filter_by(order_id=order_id).count() == 2
            assert verify_db.query(BillingEngineClaim).count() == 2


# ---------------------------------------------------------------------------
# Scheduler Unit & Lifecycle Tests
# ---------------------------------------------------------------------------

class TestFulfilmentRecoveryScheduler:
    """Test suite for FulfilmentRecoveryScheduler asyncio lifecycle."""

    def test_disabled_scheduler_does_not_start(self, monkeypatch):
        """When FULFILMENT_RECOVERY_ENABLED is False (the default), start() returns False and starts no task."""
        monkeypatch.setattr(settings, "FULFILMENT_RECOVERY_ENABLED", False)

        scheduler = FulfilmentRecoveryScheduler()
        started = scheduler.start()

        assert started is False
        assert scheduler.is_running is False

    def test_configurable_interval_and_batch_size_applied(self, monkeypatch):
        """Custom interval and batch size settings are correctly exposed and applied."""
        monkeypatch.setattr(settings, "FULFILMENT_RECOVERY_INTERVAL_SECONDS", 120)
        monkeypatch.setattr(settings, "FULFILMENT_RECOVERY_BATCH_SIZE", 25)

        # Default initialization reads from settings
        scheduler_default = FulfilmentRecoveryScheduler()
        assert scheduler_default.interval_seconds == 120
        assert scheduler_default.batch_size == 25

        # Explicit initialization overrides settings
        scheduler_explicit = FulfilmentRecoveryScheduler(interval_seconds=15, batch_size=10)
        assert scheduler_explicit.interval_seconds == 15
        assert scheduler_explicit.batch_size == 10

    @pytest.mark.anyio
    async def test_graceful_shutdown_works(self, monkeypatch):
        """Scheduler starts asyncio task and stops cleanly upon stop() signal."""
        monkeypatch.setattr(settings, "FULFILMENT_RECOVERY_ENABLED", True)

        scheduler = FulfilmentRecoveryScheduler(interval_seconds=10)
        started = scheduler.start()

        assert started is True
        assert scheduler.is_running is True

        # Second start call is a no-op
        assert scheduler.start() is False

        # Graceful stop
        await scheduler.stop()
        assert scheduler.is_running is False

    def test_scheduler_startup_does_not_block_application_startup(self, monkeypatch):
        """Application startup with lifespan completes smoothly without blocking HTTP requests."""
        monkeypatch.setattr(settings, "FULFILMENT_RECOVERY_ENABLED", True)

        with TestClient(app) as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json() == {"message": "ShopEasy backend is running"}


# ---------------------------------------------------------------------------
# CLI Recovery Worker Tests
# ---------------------------------------------------------------------------

class TestFulfilmentRecoveryCLI:
    """Test suite for FulfilmentRecoveryWorker CLI entry point and exit code handling."""

    def test_cli_exits_zero_on_successful_sweep(self, monkeypatch):
        """CLI returns exit code 0 when a sweep succeeds with no errors or failed orders."""
        from app.services.fulfilment.recovery import main

        def mock_sweep():
            return FulfilmentRecoveryResult(
                candidates_found=1,
                orders_fulfilled=1,
                orders_failed=0,
                errors=[],
            )

        monkeypatch.setattr(FulfilmentRecoveryWorker, "run_sweep", mock_sweep)
        exit_code = main()
        assert exit_code == 0

    def test_cli_exits_nonzero_on_failed_orders(self, monkeypatch):
        """CLI returns exit code 1 when one or more orders fail during sweep."""
        from app.services.fulfilment.recovery import main

        def mock_sweep():
            return FulfilmentRecoveryResult(
                candidates_found=2,
                orders_fulfilled=1,
                orders_failed=1,
                failed_order_ids=[99],
                errors=["Order #99 failed: Database lock timeout"],
            )

        monkeypatch.setattr(FulfilmentRecoveryWorker, "run_sweep", mock_sweep)
        exit_code = main()
        assert exit_code == 1

    def test_cli_exits_nonzero_on_candidate_query_database_failure(self, monkeypatch):
        """CLI returns exit code 1 when candidate query fails due to database exception."""
        from app.services.fulfilment.recovery import main

        # Simulate database failure during candidate query
        def mock_sweep():
            return FulfilmentRecoveryResult(
                candidates_found=0,
                orders_fulfilled=0,
                orders_failed=0,
                errors=["Failed to query candidate orders: (pymysql.err.OperationalError) (2003, Can't connect)"],
            )

        monkeypatch.setattr(FulfilmentRecoveryWorker, "run_sweep", mock_sweep)
        exit_code = main()
        assert exit_code == 1


# ---------------------------------------------------------------------------
# MySQL 8 Concurrency Test (Activated when TEST_MYSQL_URL is set)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("TEST_MYSQL_URL"),
    reason="MySQL concurrency test requires TEST_MYSQL_URL targeting a local or CI MySQL instance."
)
@pytest.mark.mysql
def test_mysql_concurrent_recovery_workers():
    """Verify that multiple concurrent recovery workers safely coordinate using MySQL row-level locks."""
    mysql_url = os.getenv("TEST_MYSQL_URL")
    engine = create_engine(mysql_url, pool_pre_ping=True)
    SessionMaker = sessionmaker(bind=engine)

    with SessionMaker() as init_session:
        seed_counter(init_session, start_val=800)
        user = make_user(init_session, phone="9933445566", programme=Programme.PLAN_A, referral_code="PARECMY1")
        order, items, prod = make_order_with_items(
            init_session, user, quantities=[2], order_number="ORD-CONC-REC-MY", idempotency_key="idemp-conc-rec-my"
        )
        order_id = order.id

    results = []
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            res = FulfilmentRecoveryWorker.run_sweep(
                session_factory=SessionMaker,
                batch_size=10,
            )
            with lock:
                results.append(res)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent recovery errors: {errors}"
    total_fulfilled = sum(r.orders_fulfilled for r in results)
    assert total_fulfilled == 1

    with SessionMaker() as verify_session:
        db_order = verify_session.query(Order).filter_by(id=order_id).first()
        assert db_order.is_fulfilled is True
        assert verify_session.query(BillingId).filter_by(order_id=order_id).count() == 2
        assert verify_session.query(BillingEngineClaim).count() == 2
