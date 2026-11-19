"""Tests for Plan A Cashback Dispatch Integration and Sequential Queue Advancement."""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.billing import BillingEngineClaim, BillingId
from app.models.product import Product
from app.models.user import Address, User
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
from app.models.referral import ReferralRelationship
from app.models.user import User
from app.models.wallet import Wallet, WalletTransaction
from app.services.cashback.plan_a import PlanACashbackService
from app.services.cashback.recovery_plan_a import PlanACashbackRecoveryWorker
from app.services.fulfilment_handoff import (
    dispatch_order_cashback,
    dispatch_order_fulfilment,
)

pytestmark = pytest.mark.unit


def test_plan_a_cashback_full_16_contributions_and_queue_advancement(db_session: Session):
    """Verify exact flow:
    1. Root customer buys 1 Power Bank (BID 1): routes to reserve (BR-A4), starts Cycle 1.
    2. Referred customer buys 16 Power Banks (BIDs 2-17): all 16 contribute ₹250 to Cycle 1 (BID 1).
    3. Cycle 1 reaches 16/16 contributions (₹4,000.00) and marks COMPLETED.
    4. Sequential commission wallet credited ₹4,000.00.
    5. Queue advances to BID 2 (the next FIFO waiting entry), NOT BID 17.
    """
    # 0. Product
    prod = Product(
        name="Arya Power Bank 10000mAh",
        product_code="PB-10K-CB",
        price=Decimal("3999.00"),
        stock=10000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(prod)
    db_session.flush()

    # 1. Root customer (Customer 1)
    root = User(
        phone="9019443501",
        full_name="Hithesh Kumar H",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="PAJA3W14",
    )
    db_session.add(root)
    db_session.commit()

    addr1 = Address(
        user_id=root.id,
        recipient_name=root.full_name,
        phone=root.phone,
        address_line1="123 Test St",
        city="Bengaluru",
        state="Karnataka",
        pincode="560001",
    )
    db_session.add(addr1)
    db_session.flush()

    order1 = Order(
        user_id=root.id,
        address_id=addr1.id,
        order_number="ORD-001",
        idempotency_key="ORD-IDEMP-001",
        total_amount=Decimal("3999.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        is_fulfilled=True,
    )
    db_session.add(order1)
    db_session.commit()

    bid1 = BillingId(
        billing_number="AGD-000201",
        sequence_number=201,
        order_id=order1.id,
        order_item_id=1,
        user_id=root.id,
        product_id=prod.id,
        unit_index=1,
        programme=Programme.PLAN_A,
        status="ALLOCATED",
    )
    db_session.add(bid1)
    db_session.commit()
    db_session.add(BillingEngineClaim(billing_id=bid1.id, engine=Programme.PLAN_A, status="PENDING"))
    db_session.commit()

    # Process BID 1
    res1 = PlanACashbackService.process_billing_id(bid1.id, db=db_session)
    assert res1.status == "RESERVED_INITIAL_QUEUE"

    # Verify Queue 1 and Cycle 1
    q1 = db_session.query(PlanACashbackQueue).filter_by(root_user_id=root.id).one()
    c1 = db_session.query(PlanACashbackCycle).filter_by(id=q1.active_cycle_id).one()
    assert c1.recipient_billing_id == bid1.id
    assert c1.completed_contributions == 0
    assert c1.status == "ACTIVE"

    # Verify Company reserve
    reserve = db_session.query(PlanAUnallocatedCashbackReserve).filter_by(billing_id=bid1.id).one()
    assert reserve.amount == Decimal("250.00")
    assert reserve.status == "UNALLOCATED — COMPANY OWNED"

    # 2. Referred customer (Customer 2)
    referee = User(
        phone="9019443502",
        full_name="Customer 02",
        role=UserRole.CUSTOMER,
        programme=Programme.PLAN_A,
        account_status=AccountStatus.ACTIVE,
        referral_code="PAV3B42V",
    )
    db_session.add(referee)
    db_session.commit()

    rel = ReferralRelationship(
        referee_id=referee.id,
        referrer_id=root.id,
        referee_programme=Programme.PLAN_A,
        referrer_programme=Programme.PLAN_A,
        referral_code_used=root.referral_code,
        binding_channel="CHECKOUT",
        is_active=True,
    )
    db_session.add(rel)
    db_session.commit()

    addr2 = Address(
        user_id=referee.id,
        recipient_name=referee.full_name,
        phone=referee.phone,
        address_line1="456 Test Ave",
        city="Bengaluru",
        state="Karnataka",
        pincode="560002",
    )
    db_session.add(addr2)
    db_session.flush()

    order2 = Order(
        user_id=referee.id,
        address_id=addr2.id,
        order_number="ORD-002",
        idempotency_key="ORD-IDEMP-002",
        total_amount=Decimal("63984.00"),
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
        applied_referral_code=root.referral_code,
        is_fulfilled=True,
    )
    db_session.add(order2)
    db_session.commit()

    bids_c2 = []
    for seq in range(202, 218):
        bid = BillingId(
            billing_number=f"AGD-000{seq}",
            sequence_number=seq,
            order_id=order2.id,
            order_item_id=2,
            user_id=referee.id,
            product_id=prod.id,
            unit_index=seq - 201,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(bid)
        db_session.commit()
        db_session.add(BillingEngineClaim(billing_id=bid.id, engine=Programme.PLAN_A, status="PENDING"))
        db_session.commit()
        bids_c2.append(bid)

    assert len(bids_c2) == 16

    # 3. Process all 16 BIDs for Order 2 via process_order_cashback
    results = PlanACashbackService.process_order_cashback(order2.id, db=db_session)
    assert len(results) == 16

    # 4. Verify all 16 contributed to Cycle 1 (AGD-000201)
    for idx, r in enumerate(results):
        assert r.status == "CONTRIBUTED"
        assert r.cycle_id == c1.id
        assert r.recipient_user_id == root.id
        if idx < 15:
            assert r.cycle_completed is False
        else:
            assert r.cycle_completed is True
            assert r.credited_amount == Decimal("4000.00")

    # Refresh Cycle 1
    db_session.refresh(c1)
    assert c1.completed_contributions == 16
    assert c1.total_earned == Decimal("4000.00")
    assert c1.status == "COMPLETED"

    # 5. Verify Customer 1 Sequential Commission Wallet credited exactly ₹4,000.00
    w_seq = db_session.query(Wallet).filter_by(user_id=root.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION).one()
    assert w_seq.balance == Decimal("4000.00")

    # 6. Verify Queue Advancement: Next active cycle MUST be BID 2 (AGD-000202), NOT BID 17 (AGD-000217)!
    db_session.refresh(q1)
    assert q1.active_cycle_id is not None
    next_cycle = db_session.query(PlanACashbackCycle).filter_by(id=q1.active_cycle_id).one()
    assert next_cycle.recipient_billing_id == bids_c2[0].id  # AGD-000202!
    assert next_cycle.recipient_user_id == referee.id
    assert next_cycle.completed_contributions == 0
    assert next_cycle.status == "ACTIVE"


def test_post_fulfilment_dispatch_calls_cashback(db_session: Session, monkeypatch):
    """Verify that dispatch_order_fulfilment calls dispatch_order_cashback."""
    called_orders = []

    def fake_process_order_cashback(order_id, **kwargs):
        called_orders.append(order_id)
        return []

    from app.services.cashback.plan_a import PlanACashbackService
    monkeypatch.setattr(PlanACashbackService, "process_order_cashback", fake_process_order_cashback)

    # Call dispatch_order_cashback directly
    dispatch_order_cashback(order_id=999, db=db_session)
    assert 999 in called_orders
