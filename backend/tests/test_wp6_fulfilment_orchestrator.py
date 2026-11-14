"""Focused tests for WP-6.3 Fulfilment Orchestrator and payment handoff integration."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import threading
from typing import List
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.billing import BillingCounter, BillingEngineClaim, BillingId
from app.models.cart import CartItem
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.payment import PaymentAttempt
from app.models.product import Product
from app.models.user import Address, User
from app.services.billing.allocator import BillingAllocatorService
from app.services.fulfilment.orchestrator import FulfilmentOrchestrator, FulfilmentResult
from app.services.fulfilment_handoff import dispatch_order_fulfilment
from app.services.payment.service import PaymentService


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
    referral_code: str = "PAORCH01",
) -> User:
    user = User(
        phone=phone,
        password_hash="hashed_pw",
        full_name="Orchestrator Test User",
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
    name: str = "Arya Power Bank Pro",
    price: Decimal = Decimal("3999.00"),
    stock: int = 50,
) -> Product:
    product = Product(
        name=name,
        description="Test power bank",
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
        address_line1="789 Orchestrator Blvd",
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
    order_number: str = "ORD-ORCH-001",
    idempotency_key: str = "idemp-orch-001",
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
# Unit and Lifecycle Tests
# ---------------------------------------------------------------------------

class TestFulfilmentOrchestrator:
    """Test suite for FulfilmentOrchestrator."""

    def test_confirmed_completed_order_creates_billing_ids_and_claims(self, db_session):
        """Confirmed and completed order creates expected Billing IDs, claims, and marks order fulfilled."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000001", programme=Programme.PLAN_A, referral_code="PAOC01")
        order, items, prod = make_order_with_items(db_session, user, quantities=[1], order_number="ORD-C1", idempotency_key="idemp-c1")

        result = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)

        assert result.status == "COMPLETED"
        assert result.order_id == order.id
        assert result.billing_id_count == 1
        assert result.billing_numbers == ["AGD-000201"]
        assert result.engine_claim_count == 1

        db_session.refresh(order)
        assert order.is_fulfilled is True
        assert order.fulfilled_at is not None

        # Verify BillingId in DB
        b_id = db_session.query(BillingId).filter_by(order_id=order.id).first()
        assert b_id is not None
        assert b_id.billing_number == "AGD-000201"
        assert b_id.programme == Programme.PLAN_A

        # Verify BillingEngineClaim in DB
        claim = db_session.query(BillingEngineClaim).filter_by(billing_id=b_id.id).first()
        assert claim is not None
        assert claim.engine == Programme.PLAN_A
        assert claim.status == "PENDING"
        assert claim.claimed_at is not None

    def test_quantity_n_creates_n_billing_ids_and_claims(self, db_session):
        """Order with multiple items totaling 4 units creates 4 Billing IDs and 4 engine claims."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000002", programme=Programme.PLAN_B, referral_code="PBOC02")
        order, items, prod = make_order_with_items(db_session, user, quantities=[1, 3], order_number="ORD-QN", idempotency_key="idemp-qn")

        result = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)

        assert result.status == "COMPLETED"
        assert result.billing_id_count == 4
        assert result.engine_claim_count == 4
        assert result.billing_numbers == ["AGD-000201", "AGD-000202", "AGD-000203", "AGD-000204"]

        db_session.refresh(order)
        assert order.is_fulfilled is True

        claims = (
            db_session.query(BillingEngineClaim)
            .join(BillingId, BillingEngineClaim.billing_id == BillingId.id)
            .filter(BillingId.order_id == order.id)
            .all()
        )
        assert len(claims) == 4
        # Plan B user's claims must all be PLAN_B
        assert all(c.engine == Programme.PLAN_B for c in claims)

    def test_claim_engine_strictly_matches_billing_id_programme(self, db_session):
        """Claim engine cannot disagree with Billing ID programme."""
        seed_counter(db_session, start_val=200)
        user_a = make_user(db_session, phone="9810000003", programme=Programme.PLAN_A, referral_code="PAOC03")
        order_a, _, _ = make_order_with_items(db_session, user_a, quantities=[1], order_number="ORD-P-A", idempotency_key="idemp-p-a")
        res_a = FulfilmentOrchestrator.fulfil_order(order_id=order_a.id, db=db_session)
        assert res_a.status == "COMPLETED"

        claim_a = db_session.query(BillingEngineClaim).join(BillingId).filter(BillingId.order_id == order_a.id).first()
        b_a = db_session.query(BillingId).filter_by(order_id=order_a.id).first()
        assert claim_a.engine == b_a.programme == Programme.PLAN_A

    def test_pending_order_is_rejected_without_creating_records(self, db_session):
        """Order with order_status PENDING_PAYMENT returns INELIGIBLE with 0 records created."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000004", programme=Programme.PLAN_A, referral_code="PAOC04")
        order, _, _ = make_order_with_items(
            db_session,
            user,
            quantities=[1],
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            order_number="ORD-INEL-1",
            idempotency_key="idemp-inel-1",
        )

        result = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)

        assert result.status == "INELIGIBLE"
        assert result.billing_id_count == 0
        assert result.engine_claim_count == 0

        db_session.refresh(order)
        assert order.is_fulfilled is False
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 0
        assert db_session.query(BillingEngineClaim).count() == 0

    def test_failed_order_is_rejected_without_creating_records(self, db_session):
        """Order with order_status FAILED returns INELIGIBLE with 0 records created."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000005", programme=Programme.PLAN_A, referral_code="PAOC05")
        order, _, _ = make_order_with_items(
            db_session,
            user,
            quantities=[1],
            order_status=OrderStatus.FAILED,
            payment_status=PaymentStatus.FAILED,
            order_number="ORD-INEL-2",
            idempotency_key="idemp-inel-2",
        )

        result = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)

        assert result.status == "INELIGIBLE"
        assert result.billing_id_count == 0
        db_session.refresh(order)
        assert order.is_fulfilled is False

    def test_repeated_orchestrator_call_is_idempotent(self, db_session):
        """Calling fulfil_order twice on the same order returns ALREADY_FULFILLED without duplicating rows."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000006", programme=Programme.PLAN_A, referral_code="PAOC06")
        order, _, _ = make_order_with_items(db_session, user, quantities=[2], order_number="ORD-REP", idempotency_key="idemp-rep")

        # First call
        res1 = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)
        assert res1.status == "COMPLETED"
        assert res1.billing_id_count == 2
        assert res1.engine_claim_count == 2

        # Second call
        res2 = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)
        assert res2.status == "ALREADY_FULFILLED"
        assert res2.billing_id_count == 2
        assert res2.billing_numbers == res1.billing_numbers
        assert res2.engine_claim_count == 2

        # Verify exact DB row counts
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 2
        claims = (
            db_session.query(BillingEngineClaim)
            .join(BillingId)
            .filter(BillingId.order_id == order.id)
            .count()
        )
        assert claims == 2

        # Counter value is 202, NOT incremented to 204
        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 202

    def test_failure_during_claim_creation_rolls_back_entire_fulfilment(self, db_session, monkeypatch):
        """If claim creation fails midway, all Billing IDs, claims, counter increment, and fulfilment flags are rolled back."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000007", programme=Programme.PLAN_A, referral_code="PAOC07")
        order, _, _ = make_order_with_items(db_session, user, quantities=[2], order_number="ORD-FAIL-TX", idempotency_key="idemp-fail-tx")

        # Mock BillingEngineClaim creation to simulate an unexpected error on flush
        orig_flush = Session.flush
        flush_call_count = 0

        def failing_flush(session_self, *args, **kwargs):
            nonlocal flush_call_count
            flush_call_count += 1
            # BillingAllocatorService flushes once (flush_call_count == 1)
            # The orchestrator flushes claims (flush_call_count == 2)
            if flush_call_count == 2:
                raise RuntimeError("Simulated database failure during engine claim creation")
            return orig_flush(session_self, *args, **kwargs)

        monkeypatch.setattr(Session, "flush", failing_flush)

        with pytest.raises(RuntimeError, match="Simulated database failure"):
            FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=db_session)

        # Verify atomic rollback:
        db_session.refresh(order)
        assert order.is_fulfilled is False
        assert order.fulfilled_at is None
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 0
        assert db_session.query(BillingEngineClaim).count() == 0

        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 200

    def test_dedicated_session_lifecycle_when_db_is_none(self, db_session, test_engine, monkeypatch):
        """When db is None, orchestrator opens a dedicated session and commits durably."""
        seed_counter(db_session, start_val=200)
        user = make_user(db_session, phone="9810000008", programme=Programme.PLAN_A, referral_code="PAOC08")
        order, _, _ = make_order_with_items(db_session, user, quantities=[1], order_number="ORD-DED", idempotency_key="idemp-ded")

        # Bind SessionLocal in orchestrator module to test engine session factory
        factory = sessionmaker(bind=test_engine)
        monkeypatch.setattr("app.services.fulfilment.orchestrator.SessionLocal", factory)

        # Pass db=None to invoke dedicated session lifecycle
        result = FulfilmentOrchestrator.fulfil_order(order_id=order.id, db=None)

        assert result.status == "COMPLETED"
        assert result.billing_id_count == 1

        # Query in caller session to verify durable commit
        db_session.expire_all()
        reloaded = db_session.query(Order).filter_by(id=order.id).first()
        assert reloaded.is_fulfilled is True
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 1

    def test_caller_session_with_unrelated_pending_changes_is_not_committed(self, tmp_path):
        """A caller session with unrelated pending changes is not committed when fulfilment runs."""
        db_file = tmp_path / "test_iso_commit.db"
        engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False},
            pool_recycle=300,
        )
        Base.metadata.create_all(bind=engine)
        SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        # 1. Setup confirmed order in DB
        with SessionMaker() as init_db:
            seed_counter(init_db, start_val=200)
            user = make_user(init_db, phone="9810000091", programme=Programme.PLAN_A, referral_code="PAOC91")
            order, items, prod = make_order_with_items(
                init_db, user, quantities=[1], order_number="ORD-ISO-COMMIT", idempotency_key="idemp-iso-commit"
            )
            order_id = order.id

        # 2. Open caller session with unrelated pending change
        caller_session = SessionMaker()
        unrelated = Product(
            name="Unrelated Caller Product",
            description="Pending uncommitted product",
            price=Decimal("999.00"),
            stock=5,
            is_active=True,
        )
        caller_session.add(unrelated)
        assert unrelated in caller_session.new, "Unrelated item must be pending/dirty in caller session"

        # 3. Execute fulfilment passing caller_session
        result = FulfilmentOrchestrator.fulfil_order(order_id=order_id, db=caller_session)
        assert result.status == "COMPLETED"

        # 4. Verify in a separate verification session:
        # - The order fulfilment WAS committed
        # - The unrelated caller product WAS NOT committed to the database
        with SessionMaker() as verify_session:
            db_order = verify_session.query(Order).filter_by(id=order_id).first()
            assert db_order.is_fulfilled is True
            assert verify_session.query(BillingId).filter_by(order_id=order_id).count() == 1
            assert verify_session.query(BillingEngineClaim).count() == 1

            uncommitted_prod = verify_session.query(Product).filter_by(name="Unrelated Caller Product").first()
            assert uncommitted_prod is None, "Unrelated caller entity must NOT be committed by fulfilment"

        # 5. Verify that unrelated item is STILL pending in caller_session
        assert unrelated in caller_session.new, "Unrelated entity must remain pending in caller session"
        caller_session.close()

    def test_caller_session_with_unrelated_pending_changes_is_not_rolled_back(self, tmp_path, monkeypatch):
        """A caller session with unrelated pending changes is not rolled back when fulfilment fails."""
        db_file = tmp_path / "test_iso_rollback.db"
        engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False},
            pool_recycle=300,
        )
        Base.metadata.create_all(bind=engine)
        SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        # 1. Setup confirmed order in DB
        with SessionMaker() as init_db:
            seed_counter(init_db, start_val=200)
            user = make_user(init_db, phone="9810000092", programme=Programme.PLAN_A, referral_code="PAOC92")
            order, items, prod = make_order_with_items(
                init_db, user, quantities=[1], order_number="ORD-ISO-ROLLBACK", idempotency_key="idemp-iso-rollback"
            )
            order_id = order.id

        # 2. Open caller session with unrelated pending change
        caller_session = SessionMaker()
        unrelated = Product(
            name="Unrelated Rollback Product",
            description="Pending uncommitted product",
            price=Decimal("1999.00"),
            stock=10,
            is_active=True,
        )
        caller_session.add(unrelated)
        assert unrelated in caller_session.new, "Unrelated item must be pending/dirty in caller session"

        # 3. Simulate claim flush failure
        orig_flush = Session.flush
        flush_call_count = 0

        def failing_flush(session_self, *args, **kwargs):
            nonlocal flush_call_count
            flush_call_count += 1
            if flush_call_count == 2:
                raise RuntimeError("Simulated failure during claim flush")
            return orig_flush(session_self, *args, **kwargs)

        monkeypatch.setattr(Session, "flush", failing_flush)

        # 4. Fulfilment must fail and raise
        with pytest.raises(RuntimeError, match="Simulated failure during claim flush"):
            FulfilmentOrchestrator.fulfil_order(order_id=order_id, db=caller_session)

        # 5. Verify in verification session that fulfilment mutations were rolled back
        with SessionMaker() as verify_session:
            db_order = verify_session.query(Order).filter_by(id=order_id).first()
            assert db_order.is_fulfilled is False
            assert verify_session.query(BillingId).filter_by(order_id=order_id).count() == 0
            assert verify_session.query(BillingEngineClaim).count() == 0
            counter = verify_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
            assert counter.current_value == 200

            db_prod = verify_session.query(Product).filter_by(name="Unrelated Rollback Product").first()
            assert db_prod is None

        # 6. Verify caller_session was NOT rolled back: unrelated item is STILL in caller_session.new
        assert unrelated in caller_session.new, "Unrelated entity must NOT be rolled back or evicted from caller session"
        caller_session.close()


# ---------------------------------------------------------------------------
# Payment Handoff Integration Tests
# ---------------------------------------------------------------------------

class TestPaymentHandoffIntegration:
    """Test integration between PaymentService, dispatch_order_fulfilment, and FulfilmentOrchestrator."""

    def test_payment_success_triggers_synchronous_fulfilment(self, db_session):
        """Successful payment confirmation triggers dispatch_order_fulfilment, allocating IDs and claims."""
        seed_counter(db_session, start_val=200)
        customer = make_user(db_session, phone="9820000001", programme=Programme.PLAN_A, referral_code="PAHO01")
        product = make_product(db_session, price=Decimal("3999.00"), stock=10)
        addr = make_address(db_session, customer)

        # Place Order
        order = Order(
            order_number="ORD-HANDOFF-01",
            idempotency_key="idemp-ho-01",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=2,
            line_total=Decimal("7998.00"),
        )
        db_session.add(item)
        db_session.flush()

        # Add CartItem to verify cart is cleared
        cart_item = CartItem(user_id=customer.id, product_id=product.id, quantity=2)
        db_session.add(cart_item)

        # Create PaymentAttempt
        past_time = datetime.now(timezone.utc) + datetime.resolution
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-HO-01",
            provider="simulated",
            amount=Decimal("3999.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=past_time,
        )
        db_session.add(attempt)
        db_session.commit()

        # Inbound payment.completed webhook event
        payload = {
            "event_id": "evt_handoff_success_01",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 3999.00,
            "currency": "INR",
        }
        outcome, resp = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome == "COMPLETED"

        # Verify Order state
        db_session.refresh(order)
        assert order.order_status == OrderStatus.CONFIRMED
        assert order.payment_status == PaymentStatus.COMPLETED
        assert order.is_fulfilled is True
        assert order.fulfilled_at is not None

        # Verify Billing IDs allocated (quantity 2 -> 2 Billing IDs)
        bids = db_session.query(BillingId).filter_by(order_id=order.id).order_by(BillingId.sequence_number.asc()).all()
        assert len(bids) == 2
        assert [b.sequence_number for b in bids] == [201, 202]
        assert [b.billing_number for b in bids] == ["AGD-000201", "AGD-000202"]

        # Verify Engine claims
        claims = db_session.query(BillingEngineClaim).join(BillingId).filter(BillingId.order_id == order.id).all()
        assert len(claims) == 2
        assert all(c.engine == Programme.PLAN_A for c in claims)

    def test_duplicate_payment_webhook_does_not_duplicate_fulfilment(self, db_session):
        """Duplicate webhook delivery returns DUPLICATE_IGNORED and does not re-allocate or duplicate claims."""
        seed_counter(db_session, start_val=200)
        customer = make_user(db_session, phone="9820000002", programme=Programme.PLAN_A, referral_code="PAHO02")
        product = make_product(db_session, price=Decimal("3999.00"), stock=10)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-HANDOFF-DUP",
            idempotency_key="idemp-ho-dup",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=1,
            line_total=Decimal("3999.00"),
        )
        db_session.add(item)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-HO-DUP",
            provider="simulated",
            amount=Decimal("3999.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + datetime.resolution,
        )
        db_session.add(attempt)
        db_session.commit()

        payload = {
            "event_id": "evt_handoff_dup_01",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 3999.00,
            "currency": "INR",
        }
        # First event
        outcome1, _ = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome1 == "COMPLETED"

        # Re-deliver duplicate event
        outcome2, _ = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )
        assert outcome2 == "ALREADY_PROCESSED"

        # Assert exactly 1 BillingId and 1 claim exist
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 1
        assert db_session.query(BillingEngineClaim).join(BillingId).filter(BillingId.order_id == order.id).count() == 1

    def test_payment_expiry_does_not_trigger_fulfilment(self, db_session):
        """Payment expiry worker does not trigger fulfilment or create Billing IDs."""
        seed_counter(db_session, start_val=200)
        customer = make_user(db_session, phone="9820000003", programme=Programme.PLAN_A, referral_code="PAHO03")
        product = make_product(db_session, price=Decimal("3999.00"), stock=10)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-EXP-HO",
            idempotency_key="idemp-exp-ho",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=1,
            line_total=Decimal("3999.00"),
        )
        db_session.add(item)
        past_time = datetime.now(timezone.utc) - datetime.resolution
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-EXP-HO",
            provider="simulated",
            amount=Decimal("3999.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=past_time,
        )
        db_session.add(attempt)
        db_session.commit()

        expired_count = PaymentService.expire_stale_payment_attempts(db_session)
        assert expired_count == 1

        db_session.refresh(order)
        assert order.order_status == OrderStatus.FAILED
        assert order.is_fulfilled is False
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 0
        assert db_session.query(BillingEngineClaim).count() == 0

    def test_payment_success_remains_committed_if_fulfilment_subsequently_fails(self, db_session, monkeypatch):
        """Payment success remains durably committed even if the fulfilment handoff hook fails."""
        seed_counter(db_session, start_val=200)
        customer = make_user(db_session, phone="9820000099", programme=Programme.PLAN_A, referral_code="PAFAILHO")
        product = make_product(db_session, price=Decimal("3999.00"), stock=10)
        addr = make_address(db_session, customer)

        order = Order(
            order_number="ORD-FAIL-HO",
            idempotency_key="idemp-fail-ho",
            user_id=customer.id,
            address_id=addr.id,
            total_amount=Decimal("3999.00"),
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            unit_price=product.price,
            quantity=1,
            line_total=Decimal("3999.00"),
        )
        db_session.add(item)
        attempt = PaymentAttempt(
            order_id=order.id,
            attempt_reference="SIM-ATT-FAIL-HO",
            provider="simulated",
            amount=Decimal("3999.00"),
            currency="INR",
            status=PaymentStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db_session.add(attempt)
        db_session.commit()

        # Mock dispatch_order_fulfilment to simulate unexpected orchestrator failure
        def failing_dispatch(order_id, *args, **kwargs):
            raise RuntimeError("Simulated crash inside fulfilment handoff hook")

        monkeypatch.setattr(
            "app.services.payment.service.dispatch_order_fulfilment",
            failing_dispatch,
        )

        payload = {
            "event_id": "evt_fail_handoff_001",
            "event_type": "payment.completed",
            "attempt_reference": attempt.attempt_reference,
            "amount": 3999.00,
            "currency": "INR",
        }
        outcome, resp = PaymentService.process_verified_event(
            db=db_session,
            raw_payload=json.dumps(payload).encode("utf-8"),
            headers={"X-ShopEasy-Simulated-Auth": settings.SIMULATED_PAYMENT_SECRET},
        )

        # Payment confirmation must succeed regardless of fulfilment hook failure
        assert outcome == "COMPLETED"
        assert resp["status"] == "completed"

        # Verify durable payment confirmation in DB
        db_session.refresh(order)
        db_session.refresh(attempt)
        assert order.order_status == OrderStatus.CONFIRMED
        assert order.payment_status == PaymentStatus.COMPLETED
        assert attempt.status == PaymentStatus.COMPLETED

        # Order is not fulfilled (ready for recovery worker sweep)
        assert order.is_fulfilled is False
        assert order.fulfilled_at is None
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 0
        assert db_session.query(BillingEngineClaim).count() == 0


# ---------------------------------------------------------------------------
# MySQL 8 Concurrency Test (Executed if TEST_MYSQL_URL is available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("TEST_MYSQL_URL"),
    reason="MySQL concurrency test requires TEST_MYSQL_URL targeting a local or CI MySQL instance."
)
def test_mysql_concurrent_fulfilment_same_order():
    """Verify that concurrent fulfilment attempts for the same order safely serialize via row locking."""
    mysql_url = os.getenv("TEST_MYSQL_URL")
    engine = create_engine(mysql_url, pool_pre_ping=True)
    SessionMaker = sessionmaker(bind=engine)

    with SessionMaker() as init_session:
        seed_counter(init_session, start_val=700)
        user = make_user(init_session, phone="9922334455", programme=Programme.PLAN_A, referral_code="PAORCHM1")
        order, items, prod = make_order_with_items(init_session, user, quantities=[2], order_number="ORD-CONC-SAME", idempotency_key="idemp-conc-same")
        order_id = order.id

    results = []
    errors = []
    lock = threading.Lock()

    def worker():
        session = SessionMaker()
        try:
            res = FulfilmentOrchestrator.fulfil_order(order_id=order_id, db=session)
            with lock:
                results.append(res.status)
        except Exception as e:
            with lock:
                errors.append(e)
        finally:
            session.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Concurrent fulfilment error: {errors}"
    assert len(results) == 2
    # One thread completed fulfilment, the other recognized it as already fulfilled
    assert "COMPLETED" in results
    assert "ALREADY_FULFILLED" in results
