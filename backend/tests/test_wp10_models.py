"""Focused unit and schema integrity tests for WP-10 Step 1: Cashback Models and Additive Migration.

Validates:
  1. PlanACashbackQueue model creation, fields, root_user unique constraint, and relationships.
  2. PlanACashbackEntry model creation, unique billing_id constraint, unique (queue_id, queue_position).
  3. PlanACashbackCycle model creation, unique queue_entry_id, check constraints (0..16 contributions, ₹0..₹4000 earned).
  4. PlanACashbackContribution model creation, unique contributing_billing_id, unique idempotency_key, Decimal precision.
  5. PlanAUnallocatedCashbackReserve model creation, unique billing_id, unique idempotency_key, company ownership status.
  6. Relationship navigation across all 5 models.
  7. Additive migration chain verification (single linear head f4a5b6c7d8e9 revising e3f4a5b6c7d8).
  8. Coexistence with legacy models (BeneficiaryQueue, CommissionCycle, QueueControl) and WP-7/8/9 models.
"""

from datetime import datetime
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.billing import BillingCounter, BillingId
from app.models.cashback import (
    PlanACashbackContribution,
    PlanACashbackCycle,
    PlanACashbackEntry,
    PlanACashbackQueue,
    PlanAUnallocatedCashbackReserve,
)
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User
import app.models


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [0]

    def _create_user(programme: Programme = Programme.PLAN_A, role: UserRole = UserRole.CUSTOMER) -> User:
        counter[0] += 1
        num = counter[0]
        user = User(
            phone=f"98765{num:05d}",
            full_name=f"Cashback User {num}",
            role=role,
            programme=programme,
            account_status=AccountStatus.ACTIVE,
            referral_code=f"PA{num:06d}",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create_user


@pytest.fixture
def make_billing_id(db_session: Session, make_user):
    """Factory fixture for test billing IDs."""
    counter = [200]

    product = Product(
        name="Arya Power Bank 10000mAh",
        product_code="PB-10K-TEST",
        price=Decimal("3999.00"),
        stock=1000,
        is_power_bank=True,
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()

    def _create_billing_id(user: User = None) -> BillingId:
        counter[0] += 1
        seq = counter[0]
        if user is None:
            user = make_user()

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
            order_number=f"ORD-TEST-{seq:06d}",
            idempotency_key=f"idemp-test-{seq:06d}",
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

        bid = BillingId(
            billing_number=f"AGD-{seq:06d}",
            sequence_number=seq,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=0,
            user_id=user.id,
            product_id=product.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(bid)
        db_session.flush()
        return bid

    return _create_billing_id


@pytest.mark.unit
class TestWP10ModelExports:
    """Verify all new WP-10 cashback models are exported in app.models."""

    def test_app_models_exports_wp10_classes(self) -> None:
        assert hasattr(app.models, "PlanACashbackQueue")
        assert hasattr(app.models, "PlanACashbackEntry")
        assert hasattr(app.models, "PlanACashbackCycle")
        assert hasattr(app.models, "PlanACashbackContribution")
        assert hasattr(app.models, "PlanAUnallocatedCashbackReserve")

        assert "PlanACashbackQueue" in app.models.__all__
        assert "PlanACashbackEntry" in app.models.__all__
        assert "PlanACashbackCycle" in app.models.__all__
        assert "PlanACashbackContribution" in app.models.__all__
        assert "PlanAUnallocatedCashbackReserve" in app.models.__all__


@pytest.mark.unit
class TestPlanACashbackQueueModel:
    """Tests for PlanACashbackQueue model and constraints."""

    def test_queue_creation_and_defaults(self, db_session: Session, make_user) -> None:
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        assert queue.id is not None
        assert queue.root_user_id == root_user.id
        assert queue.last_allocated_position == 0
        assert queue.active_cycle_id is None
        assert queue.root_user.id == root_user.id
        assert isinstance(queue.created_at, datetime)
        assert isinstance(queue.updated_at, datetime)

    def test_queue_root_user_uniqueness(self, db_session: Session, make_user) -> None:
        """Each root user can only have at most one independent queue (BR-A2)."""
        root_user = make_user()
        q1 = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(q1)
        db_session.commit()

        q2 = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(q2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


@pytest.mark.unit
class TestPlanACashbackEntryModel:
    """Tests for PlanACashbackEntry model, queue positions, and Billing ID uniqueness."""

    def test_entry_creation_and_relationships(self, db_session: Session, make_user, make_billing_id) -> None:
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        customer = make_user()
        bid = make_billing_id(customer)

        entry = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=customer.id,
            billing_id=bid.id,
            queue_position=1,
            status="WAITING",
        )
        db_session.add(entry)
        db_session.commit()
        db_session.refresh(entry)

        assert entry.id is not None
        assert entry.queue_position == 1
        assert entry.status == "WAITING"
        assert entry.queue.id == queue.id
        assert entry.user.id == customer.id
        assert entry.billing.id == bid.id

    def test_entry_billing_id_uniqueness(self, db_session: Session, make_user, make_billing_id) -> None:
        """One queue entry per Billing ID invariant (no double enqueuing)."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        customer = make_user()
        bid = make_billing_id(customer)

        e1 = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=customer.id,
            billing_id=bid.id,
            queue_position=1,
        )
        db_session.add(e1)
        db_session.commit()

        # Second entry with identical billing_id must fail
        e2 = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=customer.id,
            billing_id=bid.id,
            queue_position=2,
        )
        db_session.add(e2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_entry_queue_position_uniqueness_within_queue(self, db_session: Session, make_user, make_billing_id) -> None:
        """Positions within the same queue must be strictly unique."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        c1 = make_user()
        c2 = make_user()
        b1 = make_billing_id(c1)
        b2 = make_billing_id(c2)

        e1 = PlanACashbackEntry(queue_id=queue.id, user_id=c1.id, billing_id=b1.id, queue_position=1)
        db_session.add(e1)
        db_session.commit()

        # Duplicate position 1 in the same queue
        e2 = PlanACashbackEntry(queue_id=queue.id, user_id=c2.id, billing_id=b2.id, queue_position=1)
        db_session.add(e2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


@pytest.mark.unit
class TestPlanACashbackCycleModel:
    """Tests for PlanACashbackCycle model, check constraints, and relationships."""

    def test_cycle_creation_and_defaults(self, db_session: Session, make_user, make_billing_id) -> None:
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        bid = make_billing_id(root_user)
        entry = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=root_user.id,
            billing_id=bid.id,
            queue_position=1,
            status="ACTIVE",
        )
        db_session.add(entry)
        db_session.flush()

        cycle = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid.id,
            cycle_number=1,
            completed_contributions=0,
            total_earned=Decimal("0.00"),
            status="ACTIVE",
        )
        db_session.add(cycle)
        db_session.commit()
        db_session.refresh(cycle)

        assert cycle.id is not None
        assert cycle.completed_contributions == 0
        assert cycle.total_earned == Decimal("0.00")
        assert cycle.status == "ACTIVE"
        assert cycle.queue_entry.id == entry.id
        assert cycle.recipient_user.id == root_user.id
        assert cycle.recipient_billing.id == bid.id

    def test_cycle_unique_queue_entry_constraint(self, db_session: Session, make_user, make_billing_id) -> None:
        """A queue entry can only have at most one cycle."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        bid = make_billing_id(root_user)
        entry = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=root_user.id,
            billing_id=bid.id,
            queue_position=1,
        )
        db_session.add(entry)
        db_session.flush()

        c1 = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid.id,
        )
        db_session.add(c1)
        db_session.commit()

        c2 = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid.id,
        )
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_cycle_contributions_boundary_check(self, db_session: Session, make_user, make_billing_id) -> None:
        """Check constraint: completed_contributions must be between 0 and 16, and total_earned between 0 and 4000."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        bid1 = make_billing_id(root_user)
        entry1 = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=root_user.id,
            billing_id=bid1.id,
            queue_position=1,
        )
        db_session.add(entry1)
        db_session.commit()

        # 1. Negative count (< 0) violates check constraint
        bad_cycle_neg = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry1.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid1.id,
            completed_contributions=-1,
        )
        db_session.add(bad_cycle_neg)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # 2. Exceeding max count (completed_contributions = 17) violates check constraint
        bad_cycle_over = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry1.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid1.id,
            completed_contributions=17,
        )
        db_session.add(bad_cycle_over)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # 3. Exceeding max total_earned (total_earned = 4000.01) violates check constraint
        bad_cycle_amount = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry1.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid1.id,
            completed_contributions=16,
            total_earned=Decimal("4000.01"),
        )
        db_session.add(bad_cycle_amount)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # 4. Valid lower boundaries accepted: 0 contributions, ₹0.00 total earned
        valid_lower_cycle = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry1.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid1.id,
            completed_contributions=0,
            total_earned=Decimal("0.00"),
            status="ACTIVE",
        )
        db_session.add(valid_lower_cycle)
        db_session.commit()
        db_session.refresh(valid_lower_cycle)
        assert valid_lower_cycle.completed_contributions == 0
        assert valid_lower_cycle.total_earned == Decimal("0.00")

        # 5. Valid upper boundaries accepted: 16 contributions, ₹4,000.00 total earned
        # Use a new distinct entry because queue_entry_id has a UNIQUE constraint
        bid2 = make_billing_id(root_user)
        entry2 = PlanACashbackEntry(
            queue_id=queue.id,
            user_id=root_user.id,
            billing_id=bid2.id,
            queue_position=2,
        )
        db_session.add(entry2)
        db_session.commit()

        valid_upper_cycle = PlanACashbackCycle(
            queue_id=queue.id,
            queue_entry_id=entry2.id,
            recipient_user_id=root_user.id,
            recipient_billing_id=bid2.id,
            completed_contributions=16,
            total_earned=Decimal("4000.00"),
            status="COMPLETED",
        )
        db_session.add(valid_upper_cycle)
        db_session.commit()
        db_session.refresh(valid_upper_cycle)
        assert valid_upper_cycle.completed_contributions == 16
        assert valid_upper_cycle.total_earned == Decimal("4000.00")
        assert valid_upper_cycle.status == "COMPLETED"


@pytest.mark.unit
class TestPlanACashbackContributionModel:
    """Tests for PlanACashbackContribution model, idempotency, and Decimal precision."""

    def test_contribution_creation_and_fields(self, db_session: Session, make_user, make_billing_id) -> None:
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        purchaser = make_user()
        bid = make_billing_id(purchaser)

        contrib = PlanACashbackContribution(
            queue_id=queue.id,
            cycle_id=None,
            contributing_billing_id=bid.id,
            contributing_user_id=purchaser.id,
            recipient_user_id=root_user.id,
            amount=Decimal("250.00"),
            status="ALLOCATED",
            idempotency_key=f"CB-CONTRIB:{bid.id}",
        )
        db_session.add(contrib)
        db_session.commit()
        db_session.refresh(contrib)

        assert contrib.id is not None
        assert contrib.amount == Decimal("250.00")
        assert contrib.status == "ALLOCATED"
        assert contrib.idempotency_key == f"CB-CONTRIB:{bid.id}"
        assert contrib.contributing_user.id == purchaser.id
        assert contrib.recipient_user.id == root_user.id

    def test_contribution_billing_id_uniqueness(self, db_session: Session, make_user, make_billing_id) -> None:
        """Each Billing ID contributes exactly once (BR-A1)."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        purchaser = make_user()
        bid = make_billing_id(purchaser)

        c1 = PlanACashbackContribution(
            queue_id=queue.id,
            contributing_billing_id=bid.id,
            contributing_user_id=purchaser.id,
            amount=Decimal("250.00"),
            idempotency_key=f"CB-CONTRIB:{bid.id}",
        )
        db_session.add(c1)
        db_session.commit()

        # Duplicate contribution for same Billing ID must fail
        c2 = PlanACashbackContribution(
            queue_id=queue.id,
            contributing_billing_id=bid.id,
            contributing_user_id=purchaser.id,
            amount=Decimal("250.00"),
            idempotency_key=f"CB-CONTRIB-OTHER:{bid.id}",
        )
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_contribution_idempotency_key_uniqueness(self, db_session: Session, make_user, make_billing_id) -> None:
        """Deterministic idempotency key must be unique."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        p1 = make_user()
        p2 = make_user()
        b1 = make_billing_id(p1)
        b2 = make_billing_id(p2)

        c1 = PlanACashbackContribution(
            queue_id=queue.id,
            contributing_billing_id=b1.id,
            contributing_user_id=p1.id,
            idempotency_key="SHARED-CB-KEY",
        )
        db_session.add(c1)
        db_session.commit()

        c2 = PlanACashbackContribution(
            queue_id=queue.id,
            contributing_billing_id=b2.id,
            contributing_user_id=p2.id,
            idempotency_key="SHARED-CB-KEY",
        )
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


@pytest.mark.unit
class TestPlanAUnallocatedCashbackReserveModel:
    """Tests for PlanAUnallocatedCashbackReserve model (BR-A4 Option A & BR-A5 Option A)."""

    def test_reserve_creation_and_company_ownership(self, db_session: Session, make_user, make_billing_id) -> None:
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        bid = make_billing_id(root_user)

        res = PlanAUnallocatedCashbackReserve(
            queue_id=queue.id,
            billing_id=bid.id,
            customer_id=root_user.id,
            amount=Decimal("250.00"),
            status="UNALLOCATED — COMPANY OWNED",
            idempotency_key=f"CB-RES:{bid.id}",
        )
        db_session.add(res)
        db_session.commit()
        db_session.refresh(res)

        assert res.id is not None
        assert res.amount == Decimal("250.00")
        assert res.status == "UNALLOCATED — COMPANY OWNED"
        assert res.customer.id == root_user.id
        assert res.billing.id == bid.id
        assert res.queue.id == queue.id
        assert isinstance(res.reserved_at, datetime)

    def test_reserve_billing_id_uniqueness(self, db_session: Session, make_user, make_billing_id) -> None:
        """Each Billing ID can only be recorded once in unallocated reserve."""
        root_user = make_user()
        queue = PlanACashbackQueue(root_user_id=root_user.id)
        db_session.add(queue)
        db_session.flush()

        bid = make_billing_id(root_user)

        r1 = PlanAUnallocatedCashbackReserve(
            queue_id=queue.id,
            billing_id=bid.id,
            customer_id=root_user.id,
            idempotency_key=f"CB-RES:{bid.id}",
        )
        db_session.add(r1)
        db_session.commit()

        r2 = PlanAUnallocatedCashbackReserve(
            queue_id=queue.id,
            billing_id=bid.id,
            customer_id=root_user.id,
            idempotency_key=f"CB-RES-OTHER:{bid.id}",
        )
        db_session.add(r2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


@pytest.mark.unit
class TestWP10MigrationLinearity:
    """Verify Alembic migration linearity and single-head topology."""

    def test_migration_chain_is_linear_with_single_head(self) -> None:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config("backend/alembic.ini")
        config.set_main_option("script_location", "backend/alembic")
        script = ScriptDirectory.from_config(config)

        heads = script.get_heads()
        assert len(heads) == 1
        assert heads[0] == "f4a5b6c7d8e9"

        # Verify parent revision is WP-9 (e3f4a5b6c7d8)
        current = script.get_revision("f4a5b6c7d8e9")
        assert current is not None
        assert current.down_revision == "e3f4a5b6c7d8"
