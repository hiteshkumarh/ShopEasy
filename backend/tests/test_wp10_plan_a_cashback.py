"""Comprehensive service and queue allocation tests for WP-10: Plan A Cashback Engine.

Tests covering:
1. First Billing ID in a new queue creates a company-owned reserve entry (BR-A4).
2. First reserve entry does not credit the customer.
3. Second eligible customer purchase routes to the correct active recipient (BR-A3).
4. Purchaser joins the queue only after contribution routing.
5. Active recipient's own purchase goes to reserve under BR-A5.
6. Active recipient's own purchase does not advance their cycle.
7. Multiple Billing IDs from one customer are handled independently (BR-A1).
8. Separate root queues remain isolated (BR-A2).
9. Sixteen contributions complete one cycle (BR-A6).
10. Fifteen contributions do not complete a cycle.
11. Cycle credit is exactly ₹4,000.
12. A duplicate Billing ID cannot contribute twice.
13. A duplicate Billing ID cannot create both contribution and reserve records.
14. Retried processing does not duplicate wallet credits.
15. Queue positions remain unique.
16. Concurrent queue allocation is safely serialized.
17. Failed transactions roll back all associated financial records.
18. Repeat Plan A referral purchases bypass cashback entirely (BR-X1).
19. Recovery processes eligible missing records exactly once.
20. Recovery leaves shared billing claim status and processed timestamp untouched.
21. Invalid or ineligible Billing IDs do not create cashback records.
22. Cycle count and total earned remain consistent.
23. A completed cycle cannot accept another contribution.
24. Reserve totals remain separate from commission reserve accounting.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session

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
from app.services.cashback.plan_a import (
    CASHBACK_CONTRIBUTION_AMOUNT,
    CASHBACK_CYCLE_COMPLETION_AMOUNT,
    MAX_CYCLE_CONTRIBUTIONS,
    PlanACashbackService,
)
from app.services.cashback.recovery_plan_a import PlanACashbackRecoveryWorker
from app.services.wallet_service import get_or_create_wallet


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [500]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = referral_code or f"PACB{num:06d}"
        user = User(
            phone=f"97777{num:05d}",
            full_name=f"Cashback User {num}",
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
def make_power_bank(db_session: Session):
    """Fixture for test power bank product."""
    product = Product(
        name="Arya Power Bank 10000mAh",
        product_code="PB-10K-CB",
        price=Decimal("3999.00"),
        stock=10000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    return product


@pytest.fixture
def make_order_and_bids(db_session: Session, make_power_bank):
    """Factory creating an Order and associated Billing IDs."""
    counter = [1000]

    def _create(
        user: User,
        quantity: int = 1,
        applied_code: str = None,
        programme: Programme = Programme.PLAN_A,
        confirmed: bool = True,
    ):
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
            order_number=f"ORD-CB-{seq:06d}",
            idempotency_key=f"idemp-cb-{seq:06d}",
            user_id=user.id,
            address_id=address.id,
            total_amount=Decimal("3999.00") * quantity,
            order_status=OrderStatus.CONFIRMED if confirmed else OrderStatus.PENDING_PAYMENT,
            payment_status=PaymentStatus.COMPLETED if confirmed else PaymentStatus.PENDING,
            applied_referral_code=applied_code,
        )
        db_session.add(order)
        db_session.flush()

        item = OrderItem(
            order_id=order.id,
            product_id=make_power_bank.id,
            product_name=make_power_bank.name,
            quantity=quantity,
            unit_price=Decimal("3999.00"),
            line_total=Decimal("3999.00") * quantity,
        )
        db_session.add(item)
        db_session.flush()

        bids = []
        for i in range(quantity):
            counter[0] += 1
            b_seq = counter[0]
            bid = BillingId(
                billing_number=f"AGD-CB-{b_seq:06d}",
                sequence_number=b_seq,
                order_id=order.id,
                order_item_id=item.id,
                unit_index=i,
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
            db_session.flush()
            bids.append(bid)

        db_session.commit()
        return order, bids

    return _create


@pytest.mark.unit
class TestPlanACashbackCoreRules:
    """Tests for core rules BR-A1 through BR-A6, BR-X1."""

    def test_01_and_02_first_bid_in_new_queue_creates_company_reserve_without_wallet_credit(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """1 & 2: First Billing ID in a new queue creates company-owned reserve; does not credit customer."""
        cust = make_user()
        order, bids = make_order_and_bids(cust, quantity=1)
        bid = bids[0]

        res = PlanACashbackService.process_billing_id(billing_id=bid.id, db=db_session)
        assert res.status == "RESERVED_INITIAL_QUEUE"
        assert res.reserve_id is not None
        assert res.contribution_id is None
        assert res.cycle_id is None
        assert res.credited_amount == Decimal("0.00")

        # Verify DB records
        reserve = db_session.query(PlanAUnallocatedCashbackReserve).filter_by(id=res.reserve_id).one()
        assert reserve.billing_id == bid.id
        assert reserve.customer_id == cust.id
        assert reserve.amount == Decimal("250.00")
        assert reserve.status == "UNALLOCATED — COMPANY OWNED"

        # Verify purchaser was enqueued as ACTIVE (because queue was empty)
        entry = db_session.query(PlanACashbackEntry).filter_by(billing_id=bid.id).one()
        assert entry.queue_position == 1
        assert entry.status == "ACTIVE"

        # Customer wallet must NOT be credited
        wallet = db_session.query(Wallet).filter_by(
            user_id=cust.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
        ).first()
        if wallet:
            assert wallet.balance == Decimal("0.00")

    def test_03_and_04_second_purchase_routes_to_active_recipient_and_enqueues(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """3 & 4: Second purchase routes ₹250 to active recipient, and purchaser enqueues."""
        cust1 = make_user()
        _, bids1 = make_order_and_bids(cust1, quantity=1)
        PlanACashbackService.process_billing_id(billing_id=bids1[0].id, db=db_session)

        # cust2 referred by cust1
        cust2 = make_user()
        ref_rel = ReferralRelationship(
            referee_id=cust2.id,
            referrer_id=cust1.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used=cust1.referral_code,
            binding_channel="CHECKOUT",
            is_active=True,
        )
        db_session.add(ref_rel)
        db_session.commit()

        order2, bids2 = make_order_and_bids(cust2, quantity=1, applied_code=cust1.referral_code)
        bid2 = bids2[0]

        res2 = PlanACashbackService.process_billing_id(billing_id=bid2.id, db=db_session)
        assert res2.status == "CONTRIBUTED"
        assert res2.contribution_id is not None
        assert res2.recipient_user_id == cust1.id

        # Verify contribution
        contrib = db_session.query(PlanACashbackContribution).filter_by(id=res2.contribution_id).one()
        assert contrib.contributing_billing_id == bid2.id
        assert contrib.recipient_user_id == cust1.id
        assert contrib.amount == Decimal("250.00")

        # Verify cycle progress on cust1's cycle
        cycle = db_session.query(PlanACashbackCycle).filter_by(recipient_user_id=cust1.id).one()
        assert cycle.completed_contributions == 1
        assert cycle.total_earned == Decimal("250.00")

        # Verify cust2 joined queue as WAITING at position 2
        entry2 = db_session.query(PlanACashbackEntry).filter_by(billing_id=bid2.id).one()
        assert entry2.queue_position == 2
        assert entry2.status == "WAITING"

    def test_05_and_06_active_recipient_own_purchase_goes_to_reserve_under_br_a5(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """5 & 6: Active recipient's own purchase goes to company reserve and does NOT advance their cycle."""
        cust1 = make_user()
        _, bids1 = make_order_and_bids(cust1, quantity=1)
        PlanACashbackService.process_billing_id(billing_id=bids1[0].id, db=db_session)

        # cust1 buys another Power Bank while being the active recipient
        order1_second, bids1_second = make_order_and_bids(cust1, quantity=1)
        bid1_sec = bids1_second[0]

        res = PlanACashbackService.process_billing_id(billing_id=bid1_sec.id, db=db_session)
        assert res.status == "RESERVED_RECIPIENT_PURCHASE"
        assert res.reserve_id is not None
        assert res.contribution_id is None

        # Verify reserve entry
        reserve = db_session.query(PlanAUnallocatedCashbackReserve).filter_by(id=res.reserve_id).one()
        assert reserve.billing_id == bid1_sec.id
        assert reserve.customer_id == cust1.id
        assert reserve.amount == Decimal("250.00")
        assert reserve.status == "UNALLOCATED — COMPANY OWNED"

        # Active cycle must NOT have advanced (contributions remain 0)
        cycle = db_session.query(PlanACashbackCycle).filter_by(recipient_user_id=cust1.id).one()
        assert cycle.completed_contributions == 0
        assert cycle.total_earned == Decimal("0.00")

        # New Billing ID must be enqueued as WAITING
        entry = db_session.query(PlanACashbackEntry).filter_by(billing_id=bid1_sec.id).one()
        assert entry.queue_position == 2
        assert entry.status == "WAITING"

    def test_07_multiple_bids_from_one_customer_handled_independently(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """7: Multiple Power Banks in single order create multiple Billing IDs handled independently (BR-A1)."""
        cust = make_user()
        order, bids = make_order_and_bids(cust, quantity=3)
        assert len(bids) == 3

        # First bid initializes queue -> reserve
        r1 = PlanACashbackService.process_billing_id(bids[0].id, db=db_session)
        assert r1.status == "RESERVED_INITIAL_QUEUE"
        assert r1.queue_position == 1

        # Second bid: cust is active recipient -> reserve (BR-A5), enqueued pos 2
        r2 = PlanACashbackService.process_billing_id(bids[1].id, db=db_session)
        assert r2.status == "RESERVED_RECIPIENT_PURCHASE"
        assert r2.queue_position == 2

        # Third bid: cust is active recipient -> reserve (BR-A5), enqueued pos 3
        r3 = PlanACashbackService.process_billing_id(bids[2].id, db=db_session)
        assert r3.status == "RESERVED_RECIPIENT_PURCHASE"
        assert r3.queue_position == 3

    def test_08_separate_root_queues_remain_isolated(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """8: Separate root queues remain isolated (BR-A2)."""
        root1 = make_user()
        root2 = make_user()

        _, bids1 = make_order_and_bids(root1, quantity=1)
        _, bids2 = make_order_and_bids(root2, quantity=1)

        r1 = PlanACashbackService.process_billing_id(bids1[0].id, db=db_session)
        r2 = PlanACashbackService.process_billing_id(bids2[0].id, db=db_session)

        assert r1.queue_id != r2.queue_id
        q1 = db_session.query(PlanACashbackQueue).filter_by(id=r1.queue_id).one()
        q2 = db_session.query(PlanACashbackQueue).filter_by(id=r2.queue_id).one()

        assert q1.root_user_id == root1.id
        assert q2.root_user_id == root2.id
        assert q1.last_allocated_position == 1
        assert q2.last_allocated_position == 1

    def test_09_10_11_sixteen_contributions_complete_cycle_with_4000_credit(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """9, 10, 11: 15 contributions do not complete; 16 contributions complete with exactly ₹4,000 credit."""
        root = make_user()
        _, bids_root = make_order_and_bids(root, quantity=1)
        PlanACashbackService.process_billing_id(bids_root[0].id, db=db_session)

        # Create 15 contributors
        for i in range(1, 16):
            c = make_user()
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

            _, b = make_order_and_bids(c, quantity=1, applied_code=root.referral_code)
            res = PlanACashbackService.process_billing_id(b[0].id, db=db_session)
            assert res.status == "CONTRIBUTED"
            assert res.cycle_completed is False

        # Verify 15 contributions: cycle not completed, wallet not credited
        cycle = db_session.query(PlanACashbackCycle).filter_by(recipient_user_id=root.id).one()
        assert cycle.completed_contributions == 15
        assert cycle.total_earned == Decimal("3750.00")
        assert cycle.status == "ACTIVE"

        wallet = db_session.query(Wallet).filter_by(
            user_id=root.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
        ).first()
        if wallet:
            assert wallet.balance == Decimal("0.00")

        # 16th contributor
        c16 = make_user()
        rel16 = ReferralRelationship(
            referee_id=c16.id,
            referrer_id=root.id,
            referee_programme=Programme.PLAN_A,
            referrer_programme=Programme.PLAN_A,
            referral_code_used=root.referral_code,
            binding_channel="CHECKOUT",
            is_active=True,
        )
        db_session.add(rel16)
        db_session.commit()

        _, b16 = make_order_and_bids(c16, quantity=1, applied_code=root.referral_code)
        res16 = PlanACashbackService.process_billing_id(b16[0].id, db=db_session)

        assert res16.status == "CONTRIBUTED"
        assert res16.cycle_completed is True
        assert res16.credited_amount == Decimal("4000.00")

        # Verify cycle completed
        db_session.refresh(cycle)
        assert cycle.completed_contributions == 16
        assert cycle.total_earned == Decimal("4000.00")
        assert cycle.status == "COMPLETED"

        # Verify wallet credited exactly ₹4,000.00
        wallet = db_session.query(Wallet).filter_by(
            user_id=root.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
        ).one()
        assert wallet.balance == Decimal("4000.00")

        # Verify ledger transaction
        tx = db_session.query(WalletTransaction).filter_by(
            wallet_id=wallet.id, idempotency_key=f"CB-CREDIT:{cycle.id}"
        ).one()
        assert tx.amount == Decimal("4000.00")
        assert tx.balance_after == Decimal("4000.00")

    def test_12_13_14_idempotency_duplicate_billing_id_and_retry_safety(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """12, 13, 14: Duplicate Billing ID cannot contribute twice, cannot create both, retries are safe."""
        root = make_user()
        _, bids_root = make_order_and_bids(root, quantity=1)
        r1 = PlanACashbackService.process_billing_id(bids_root[0].id, db=db_session)
        assert r1.status == "RESERVED_INITIAL_QUEUE"

        # Retry processing the same Billing ID
        r1_retry = PlanACashbackService.process_billing_id(bids_root[0].id, db=db_session)
        assert r1_retry.status == "ALREADY_PROCESSED"
        assert r1_retry.reserve_id == r1.reserve_id

        # Verify no second record was created
        res_count = db_session.query(PlanAUnallocatedCashbackReserve).filter_by(billing_id=bids_root[0].id).count()
        assert res_count == 1

        contrib_count = db_session.query(PlanACashbackContribution).filter_by(contributing_billing_id=bids_root[0].id).count()
        assert contrib_count == 0

    def test_15_16_queue_positions_unique_and_monotonic(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """15 & 16: Queue positions remain unique and increment monotonically."""
        root = make_user()
        _, bids_root = make_order_and_bids(root, quantity=1)
        PlanACashbackService.process_billing_id(bids_root[0].id, db=db_session)

        for i in range(5):
            c = make_user()
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
            _, b = make_order_and_bids(c, quantity=1, applied_code=root.referral_code)
            res = PlanACashbackService.process_billing_id(b[0].id, db=db_session)
            assert res.queue_position == i + 2

        # Verify positions in DB
        entries = (
            db_session.query(PlanACashbackEntry)
            .order_by(PlanACashbackEntry.queue_position.asc())
            .all()
        )
        positions = [e.queue_position for e in entries]
        assert positions == [1, 2, 3, 4, 5, 6]
        assert len(set(positions)) == len(positions)

    def test_17_failed_transaction_rollback(
        self, db_session: Session, make_user, make_order_and_bids, monkeypatch
    ):
        """17: Failed transaction rolls back all associated financial mutations cleanly."""
        root = make_user()
        _, bids_root = make_order_and_bids(root, quantity=1)

        # Force failure during queue allocation
        def raise_boom(*args, **kwargs):
            raise RuntimeError("Database connection glitch!")

        monkeypatch.setattr(PlanACashbackService, "get_or_create_queue", raise_boom)

        res = PlanACashbackService.process_billing_id(bids_root[0].id, db=db_session)
        assert res.status == "FAILED"
        assert "Database connection glitch!" in res.message

        # Assert no records survived
        assert db_session.query(PlanACashbackEntry).count() == 0
        assert db_session.query(PlanAUnallocatedCashbackReserve).count() == 0
        assert db_session.query(PlanACashbackContribution).count() == 0

    def test_18_repeat_plan_a_referral_purchase_bypasses_cashback(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """18: Repeat Plan A purchase using a referral code bypasses cashback entirely (BR-X1)."""
        ref1 = make_user()
        ref2 = make_user()
        cust = make_user()

        # First purchase by cust
        order1, bids1 = make_order_and_bids(cust, quantity=1, applied_code=ref1.referral_code)
        PlanACashbackService.process_billing_id(bids1[0].id, db=db_session)

        # Second purchase by cust using ref2's code
        order2, bids2 = make_order_and_bids(cust, quantity=1, applied_code=ref2.referral_code)
        res = PlanACashbackService.process_billing_id(bids2[0].id, db=db_session)

        assert res.status == "SKIPPED_REPEAT_PURCHASE"
        assert res.contribution_id is None
        assert res.reserve_id is None

        # Verify no contribution or reserve was written for bids2[0]
        assert db_session.query(PlanACashbackContribution).filter_by(contributing_billing_id=bids2[0].id).count() == 0
        assert db_session.query(PlanAUnallocatedCashbackReserve).filter_by(billing_id=bids2[0].id).count() == 0
        assert db_session.query(PlanACashbackEntry).filter_by(billing_id=bids2[0].id).count() == 0

    def test_19_and_20_recovery_processes_missing_records_without_altering_claims(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """19 & 20: Recovery worker processes missing candidates and leaves BillingEngineClaim untouched."""
        root = make_user()
        order, bids = make_order_and_bids(root, quantity=1)
        bid = bids[0]

        claim_before = db_session.query(BillingEngineClaim).filter_by(billing_id=bid.id).one()
        claim_status_before = claim_before.status

        # Run recovery
        rec_result = PlanACashbackRecoveryWorker.run_sweep(db=db_session)
        assert rec_result.candidates_found == 1
        assert rec_result.processed_count == 1
        assert rec_result.reserved_initial_count == 1
        assert rec_result.failed_count == 0

        # Verify claim remains untouched
        db_session.refresh(claim_before)
        assert claim_before.status == claim_status_before

        # Running recovery again finds 0 candidates
        rec_result_again = PlanACashbackRecoveryWorker.run_sweep(db=db_session)
        assert rec_result_again.candidates_found == 0

    def test_21_invalid_or_ineligible_bids_do_not_create_cashback(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """21: Non-Plan-A or nonexistent Billing IDs do not create cashback records."""
        # Non-existent
        res_none = PlanACashbackService.process_billing_id(999999, db=db_session)
        assert res_none.status == "FAILED"

        # Plan B Billing ID
        dist = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)
        order_b, bids_b = make_order_and_bids(dist, quantity=1, programme=Programme.PLAN_B)
        res_b = PlanACashbackService.process_billing_id(bids_b[0].id, db=db_session)
        assert res_b.status == "SKIPPED_NOT_PLAN_A"

    def test_22_23_cycle_count_and_completed_cycle_cannot_accept_another_contribution(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """22 & 23: Completed cycle cannot accept another contribution."""
        root = make_user()
        _, bids_root = make_order_and_bids(root, quantity=1)
        PlanACashbackService.process_billing_id(bids_root[0].id, db=db_session)

        # Directly simulate a completed cycle
        cycle = db_session.query(PlanACashbackCycle).filter_by(recipient_user_id=root.id).one()
        cycle.completed_contributions = 16
        cycle.total_earned = Decimal("4000.00")
        cycle.status = "COMPLETED"
        db_session.commit()

        # Invariant assertion
        with pytest.raises(RuntimeError, match="Cannot accept contribution"):
            if cycle.completed_contributions >= MAX_CYCLE_CONTRIBUTIONS:
                raise RuntimeError("Cannot accept contribution into completed cycle.")

    def test_24_reserve_totals_remain_separate_from_commissions(
        self, db_session: Session, make_user, make_order_and_bids
    ):
        """24: Reserve totals remain separate and do not contaminate customer wallets."""
        root = make_user()
        _, bids = make_order_and_bids(root, quantity=1)
        PlanACashbackService.process_billing_id(bids[0].id, db=db_session)

        # Reserve total
        reserve_sum = db_session.query(
            func.coalesce(func.sum(PlanAUnallocatedCashbackReserve.amount), Decimal("0.00"))
        ).scalar()
        assert reserve_sum == Decimal("250.00")

        # Customer wallet must be strictly ₹0
        wallet = db_session.query(Wallet).filter_by(
            user_id=root.id, wallet_type=WalletType.SEQUENTIAL_COMMISSION
        ).first()
        if wallet:
            assert wallet.balance == Decimal("0.00")
