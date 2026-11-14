"""Focused tests for WP-6.2 Billing ID Allocator Service."""

from decimal import Decimal
import os
import threading
from typing import List
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.billing import BillingCounter, BillingId
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User
from app.services.billing.allocator import (
    BillingAllocationError,
    BillingAllocatorService,
    IneligibleOrderError,
    InvalidOrderItemsError,
    MissingBillingCounterError,
    ProgrammeResolutionError,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def seed_billing_counter(db: Session, start_value: int = 200) -> BillingCounter:
    """Ensure the standard global counter row exists with the specified starting value."""
    counter = db.query(BillingCounter).filter(BillingCounter.sequence_name == "GLOBAL_BILLING_ID").first()
    if not counter:
        counter = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=start_value)
        db.add(counter)
        db.commit()
        db.refresh(counter)
    else:
        counter.current_value = start_value
        db.commit()
        db.refresh(counter)
    return counter


def create_user(
    db: Session,
    phone: str = "9876543210",
    programme: Programme = Programme.PLAN_A,
    referral_code: str = "PAALLOC01",
) -> User:
    user = User(
        phone=phone,
        password_hash="hashed_pw",
        full_name="Allocator Test User",
        role=UserRole.CUSTOMER,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=referral_code,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_product(
    db: Session,
    name: str = "Arya Power Bank",
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


def create_address(db: Session, user: User) -> Address:
    address = Address(
        user_id=user.id,
        recipient_name=user.full_name,
        phone=user.phone,
        address_line1="456 Main St",
        city="Pune",
        state="Maharashtra",
        pincode="411001",
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


def create_order(
    db: Session,
    user: User,
    order_status: OrderStatus = OrderStatus.CONFIRMED,
    payment_status: PaymentStatus = PaymentStatus.COMPLETED,
    order_number: str = "ORD-ALLOC-001",
    idempotency_key: str = "idemp-alloc-001",
) -> Order:
    address = create_address(db, user)
    order = Order(
        order_number=order_number,
        idempotency_key=idempotency_key,
        user_id=user.id,
        address_id=address.id,
        total_amount=Decimal("3999.00"),
        order_status=order_status,
        payment_status=payment_status,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def add_order_item(
    db: Session,
    order: Order,
    product: Product,
    quantity: int = 1,
) -> OrderItem:
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        unit_price=product.price,
        quantity=quantity,
        line_total=product.price * quantity,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    db.refresh(order)
    return item


# ---------------------------------------------------------------------------
# Unit and Invariant Tests
# ---------------------------------------------------------------------------

class TestBillingAllocatorService:
    """Test suite for BillingAllocatorService."""

    def test_confirmed_completed_order_allocates_billing_ids_quantity_1(self, db_session):
        """Confirmed and completed order with quantity 1 allocates exactly one Billing ID starting at AGD-000201."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000001", programme=Programme.PLAN_A, referral_code="PAAL01")
        product = create_product(db_session, name="PB-1")
        order = create_order(db_session, user, order_number="ORD-Q1", idempotency_key="idemp-q1")
        item = add_order_item(db_session, order, product, quantity=1)

        billing_ids = BillingAllocatorService.allocate_for_order(db_session, order)
        db_session.commit()

        assert len(billing_ids) == 1
        b = billing_ids[0]
        assert b.sequence_number == 201
        assert b.billing_number == "AGD-000201"
        assert b.order_id == order.id
        assert b.order_item_id == item.id
        assert b.unit_index == 1
        assert b.user_id == user.id
        assert b.product_id == product.id
        assert b.programme == Programme.PLAN_A
        assert b.status == "ALLOCATED"

        # Verify counter was updated to 201
        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 201

    def test_quantity_greater_than_1_produces_exact_number_and_contiguous_sequence(self, db_session):
        """Order item with quantity 3 allocates exactly 3 Billing IDs with contiguous sequence numbers."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000002", programme=Programme.PLAN_A, referral_code="PAAL02")
        product = create_product(db_session, name="PB-2")
        order = create_order(db_session, user, order_number="ORD-Q3", idempotency_key="idemp-q3")
        item = add_order_item(db_session, order, product, quantity=3)

        billing_ids = BillingAllocatorService.allocate_for_order(db_session, order)
        db_session.commit()

        assert len(billing_ids) == 3
        assert [b.sequence_number for b in billing_ids] == [201, 202, 203]
        assert [b.billing_number for b in billing_ids] == ["AGD-000201", "AGD-000202", "AGD-000203"]
        assert [b.unit_index for b in billing_ids] == [1, 2, 3]

        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 203

    def test_multiple_order_items_allocates_correct_total_number(self, db_session):
        """Order with two items (qty 2 and qty 3) allocates exactly 5 Billing IDs in contiguous order."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000003", programme=Programme.PLAN_B, referral_code="PBAL03")
        prod1 = create_product(db_session, name="PB-Multi-1")
        prod2 = create_product(db_session, name="PB-Multi-2")
        order = create_order(db_session, user, order_number="ORD-MULTI", idempotency_key="idemp-multi")
        item1 = add_order_item(db_session, order, prod1, quantity=2)
        item2 = add_order_item(db_session, order, prod2, quantity=3)

        billing_ids = BillingAllocatorService.allocate_for_order(db_session, order)
        db_session.commit()

        assert len(billing_ids) == 5
        assert [b.sequence_number for b in billing_ids] == [201, 202, 203, 204, 205]
        assert [b.billing_number for b in billing_ids] == [
            "AGD-000201", "AGD-000202", "AGD-000203", "AGD-000204", "AGD-000205"
        ]
        # Item 1 has unit_index 1, 2; Item 2 has unit_index 1, 2, 3
        item1_bids = [b for b in billing_ids if b.order_item_id == item1.id]
        item2_bids = [b for b in billing_ids if b.order_item_id == item2.id]
        assert len(item1_bids) == 2
        assert [b.unit_index for b in item1_bids] == [1, 2]
        assert len(item2_bids) == 3
        assert [b.unit_index for b in item2_bids] == [1, 2, 3]
        # All have PLAN_B programme
        assert all(b.programme == Programme.PLAN_B for b in billing_ids)

    def test_repeated_allocation_is_idempotent(self, db_session):
        """Calling allocate_for_order repeatedly returns existing Billing IDs without allocating new ones."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000004", programme=Programme.PLAN_A, referral_code="PAAL04")
        product = create_product(db_session, name="PB-Idemp")
        order = create_order(db_session, user, order_number="ORD-IDEMP", idempotency_key="idemp-idemp")
        add_order_item(db_session, order, product, quantity=2)

        # First allocation
        first_bids = BillingAllocatorService.allocate_for_order(db_session, order)
        db_session.commit()
        assert len(first_bids) == 2
        assert [b.sequence_number for b in first_bids] == [201, 202]

        counter_after_first = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first().current_value
        assert counter_after_first == 202

        # Second allocation (identical order)
        second_bids = BillingAllocatorService.allocate_for_order(db_session, order)
        db_session.commit()

        assert len(second_bids) == 2
        assert [b.id for b in second_bids] == [b.id for b in first_bids]
        assert [b.billing_number for b in second_bids] == ["AGD-000201", "AGD-000202"]

        # Counter must NOT have incremented
        counter_after_second = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first().current_value
        assert counter_after_second == 202

        # Overall total rows in billing_ids table must remain 2
        total_rows = db_session.query(BillingId).count()
        assert total_rows == 2

    def test_pending_order_is_rejected_without_allocating(self, db_session):
        """Order in PENDING_PAYMENT status must raise IneligibleOrderError without altering counter."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000005", programme=Programme.PLAN_A, referral_code="PAAL05")
        product = create_product(db_session, name="PB-Pending")
        order = create_order(
            db_session,
            user,
            order_status=OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.PENDING,
            order_number="ORD-PEND",
            idempotency_key="idemp-pend",
        )
        add_order_item(db_session, order, product, quantity=1)

        with pytest.raises(IneligibleOrderError) as exc_info:
            BillingAllocatorService.allocate_for_order(db_session, order)
        assert "is ineligible for Billing ID allocation" in str(exc_info.value)

        # Verify counter is still 200
        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 200

        # Verify no BillingId was created
        assert db_session.query(BillingId).count() == 0

    def test_failed_or_unpaid_order_is_rejected(self, db_session):
        """Order in FAILED status must raise IneligibleOrderError without altering counter."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000006", programme=Programme.PLAN_A, referral_code="PAAL06")
        product = create_product(db_session, name="PB-Failed")
        order = create_order(
            db_session,
            user,
            order_status=OrderStatus.FAILED,
            payment_status=PaymentStatus.FAILED,
            order_number="ORD-FAIL",
            idempotency_key="idemp-fail",
        )
        add_order_item(db_session, order, product, quantity=1)

        with pytest.raises(IneligibleOrderError) as exc_info:
            BillingAllocatorService.allocate_for_order(db_session, order)
        assert "is ineligible for Billing ID allocation" in str(exc_info.value)

        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 200
        assert db_session.query(BillingId).count() == 0

    def test_missing_global_counter_raises_error_without_silent_creation(self, db_session):
        """Missing GLOBAL_BILLING_ID row raises MissingBillingCounterError and does not create an unauthorized counter."""
        # Ensure counter does NOT exist
        db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").delete()
        db_session.commit()

        user = create_user(db_session, phone="9800000007", programme=Programme.PLAN_A, referral_code="PAAL07")
        product = create_product(db_session, name="PB-MissingCounter")
        order = create_order(db_session, user, order_number="ORD-NOCNT", idempotency_key="idemp-nocnt")
        add_order_item(db_session, order, product, quantity=1)

        with pytest.raises(MissingBillingCounterError) as exc_info:
            BillingAllocatorService.allocate_for_order(db_session, order)
        assert "Required billing counter sequence 'GLOBAL_BILLING_ID' not found" in str(exc_info.value)

        # Verify no counter was silently added
        assert db_session.query(BillingCounter).count() == 0

    def test_order_with_no_items_raises_invalid_order_items_error(self, db_session):
        """Order with zero order items raises InvalidOrderItemsError."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000008", programme=Programme.PLAN_A, referral_code="PAAL08")
        order = create_order(db_session, user, order_number="ORD-EMPTY", idempotency_key="idemp-empty")
        # Do not add items

        with pytest.raises(InvalidOrderItemsError) as exc_info:
            BillingAllocatorService.allocate_for_order(db_session, order)
        assert "has no order items" in str(exc_info.value)

    def test_transaction_ownership_caller_rollback_restores_state(self, db_session):
        """Allocator is transaction-neutral: caller can roll back and verify zero changes remain in DB."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000009", programme=Programme.PLAN_A, referral_code="PAAL09")
        product = create_product(db_session, name="PB-Rollback")
        order = create_order(db_session, user, order_number="ORD-ROLL", idempotency_key="idemp-roll")
        add_order_item(db_session, order, product, quantity=2)

        # Call allocator
        allocated = BillingAllocatorService.allocate_for_order(db_session, order)
        assert len(allocated) == 2

        # Caller explicitly decides to rollback instead of commit
        db_session.rollback()

        # Verify counter was NOT durably incremented
        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 200

        # Verify zero BillingId rows exist
        assert db_session.query(BillingId).filter_by(order_id=order.id).count() == 0

    def test_sequential_orders_allocate_contiguous_monotonic_ranges(self, db_session):
        """Sequential orders allocate contiguous, non-overlapping sequence numbers."""
        seed_billing_counter(db_session, start_value=200)
        user = create_user(db_session, phone="9800000010", programme=Programme.PLAN_A, referral_code="PAAL10")
        product = create_product(db_session, name="PB-Seq")

        # Order 1 (qty 2)
        order1 = create_order(db_session, user, order_number="ORD-S1", idempotency_key="idemp-s1")
        add_order_item(db_session, order1, product, quantity=2)
        bids1 = BillingAllocatorService.allocate_for_order(db_session, order1)
        db_session.commit()

        # Order 2 (qty 3)
        order2 = create_order(db_session, user, order_number="ORD-S2", idempotency_key="idemp-s2")
        add_order_item(db_session, order2, product, quantity=3)
        bids2 = BillingAllocatorService.allocate_for_order(db_session, order2)
        db_session.commit()

        assert [b.sequence_number for b in bids1] == [201, 202]
        assert [b.billing_number for b in bids1] == ["AGD-000201", "AGD-000202"]

        assert [b.sequence_number for b in bids2] == [203, 204, 205]
        assert [b.billing_number for b in bids2] == ["AGD-000203", "AGD-000204", "AGD-000205"]

        counter = db_session.query(BillingCounter).filter_by(sequence_name="GLOBAL_BILLING_ID").first()
        assert counter.current_value == 205


# ---------------------------------------------------------------------------
# MySQL 8 Concurrency Test (Executed if TEST_MYSQL_URL is available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("TEST_MYSQL_URL"),
    reason="MySQL concurrency test requires TEST_MYSQL_URL targeting a local or CI MySQL instance."
)
def test_mysql_concurrent_billing_allocation():
    """Verify that concurrent independent database sessions allocate contiguous, collision-free Billing IDs."""
    mysql_url = os.getenv("TEST_MYSQL_URL")
    engine = create_engine(mysql_url, pool_pre_ping=True)
    SessionMaker = sessionmaker(bind=engine)

    orders: List[int] = []
    try:
        # Initialize counter in DB
        with SessionMaker() as init_session:
            seed_billing_counter(init_session, start_value=500)
            user = create_user(init_session, phone="9911223344", programme=Programme.PLAN_A, referral_code="PAMYSQL1")
            prod = create_product(init_session, name="PB-MySQL")
            for i in range(5):
                ord_i = create_order(init_session, user, order_number=f"ORD-CONC-{i}", idempotency_key=f"idemp-conc-{i}")
                orders.append(ord_i.id)
                add_order_item(init_session, ord_i, prod, quantity=2)

        errors = []
        all_allocated_numbers = []
        lock = threading.Lock()

        def worker(order_id: int):
            session = SessionMaker()
            try:
                order = session.query(Order).filter_by(id=order_id).first()
                bids = BillingAllocatorService.allocate_for_order(session, order)
                session.commit()
                with lock:
                    all_allocated_numbers.extend([b.sequence_number for b in bids])
            except Exception as e:
                session.rollback()
                with lock:
                    errors.append(e)
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(oid,)) for oid in orders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent allocation encountered errors: {errors}"
        assert len(all_allocated_numbers) == 10  # 5 orders * 2 units each = 10 IDs
        assert len(set(all_allocated_numbers)) == 10  # Zero duplicate sequence numbers!
        assert sorted(all_allocated_numbers) == list(range(501, 511))  # Contiguous from 501 to 510!
    finally:
        if orders:
            with SessionMaker() as cleanup_session:
                # Clean up only the exact orders created by this allocator test to prevent leaking unfulfilled orders
                cleanup_session.query(BillingId).filter(BillingId.order_id.in_(orders)).delete(synchronize_session=False)
                cleanup_session.query(OrderItem).filter(OrderItem.order_id.in_(orders)).delete(synchronize_session=False)
                cleanup_session.query(Order).filter(Order.id.in_(orders)).delete(synchronize_session=False)
                cleanup_session.commit()
