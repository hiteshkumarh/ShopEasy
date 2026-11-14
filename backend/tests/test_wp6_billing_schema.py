"""Focused schema, model, and migration tests for WP-6.1 Billing ID architecture."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.billing import BillingCounter, BillingEngineClaim, BillingId
from app.models.enums import AccountStatus, OrderStatus, PaymentStatus, Programme, UserRole
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import Address, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_user(
    db: Session,
    phone: str = "9876543299",
    role: UserRole = UserRole.CUSTOMER,
    programme: Programme = Programme.PLAN_A,
    referral_code: str = "PABILL01",
) -> User:
    user = User(
        phone=phone,
        password_hash="test-hash",
        full_name="Billing Test User",
        role=role,
        programme=programme,
        account_status=AccountStatus.ACTIVE,
        referral_code=referral_code,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_test_product(
    db: Session,
    name: str = "Test Product",
    price: Decimal = Decimal("3999.00"),
    stock: int = 20,
) -> Product:
    prod = Product(
        name=name,
        description="Test product for billing",
        price=price,
        stock=stock,
        is_active=True,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


def make_test_address(db: Session, user: User) -> Address:
    addr = Address(
        user_id=user.id,
        recipient_name="Recipient Name",
        phone=user.phone,
        address_line1="123 Test Street",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


def make_test_order_with_item(
    db: Session,
    user: User,
    quantity: int = 2,
    order_number: str = "ORD-BILL-001",
    idempotency_key: str = "idemp-bill-001",
) -> tuple[Order, OrderItem, Product]:
    prod = make_test_product(db, name=f"Product for {order_number}")
    addr = make_test_address(db, user)

    order = Order(
        order_number=order_number,
        idempotency_key=idempotency_key,
        user_id=user.id,
        address_id=addr.id,
        total_amount=prod.price * quantity,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.COMPLETED,
    )
    db.add(order)
    db.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        unit_price=prod.price,
        quantity=quantity,
        line_total=prod.price * quantity,
    )
    db.add(item)
    db.commit()
    db.refresh(order)
    db.refresh(item)
    return order, item, prod


# ---------------------------------------------------------------------------
# 1. Metadata Registration Tests
# ---------------------------------------------------------------------------

class TestBillingMetadataRegistration:
    """Verify all WP-6.1 models and fields are registered in SQLAlchemy metadata."""

    def test_all_three_models_registered_in_metadata(self):
        """BillingCounter, BillingId, and BillingEngineClaim must exist in Base.metadata.tables."""
        table_names = set(Base.metadata.tables.keys())
        assert "billing_counters" in table_names
        assert "billing_ids" in table_names
        assert "billing_engine_claims" in table_names

    def test_order_fulfilment_tracking_columns_in_metadata(self):
        """Order table in metadata must contain is_fulfilled and fulfilled_at columns."""
        orders_table = Base.metadata.tables["orders"]
        col_names = set(orders_table.columns.keys())
        assert "is_fulfilled" in col_names
        assert "fulfilled_at" in col_names
        assert orders_table.columns["is_fulfilled"].nullable is False
        assert orders_table.columns["fulfilled_at"].nullable is True


# ---------------------------------------------------------------------------
# 2. Billing Models & Constraints Tests
# ---------------------------------------------------------------------------

class TestBillingModelsAndConstraints:
    """Verify unique constraints, foreign keys, and relationships on billing models."""

    def test_billing_counter_unique_sequence_name(self, db_session):
        """BillingCounter sequence_name must be globally unique."""
        c1 = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=200)
        db_session.add(c1)
        db_session.commit()

        c2 = BillingCounter(sequence_name="GLOBAL_BILLING_ID", current_value=500)
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_billing_id_unique_billing_number(self, db_session):
        """BillingId billing_number must be unique across all rows."""
        user = make_test_user(db_session, phone="9876540001", referral_code="PABILL11")
        order, item, prod = make_test_order_with_item(db_session, user, quantity=2, order_number="ORD-BN-01", idempotency_key="idemp-bn-01")

        b1 = BillingId(
            billing_number="AGD-000201",
            sequence_number=201,
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

        b2 = BillingId(
            billing_number="AGD-000201",  # duplicate number
            sequence_number=202,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=2,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(b2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_billing_id_unique_numeric_sequence_number(self, db_session):
        """BillingId sequence_number must be unique across all rows."""
        user = make_test_user(db_session, phone="9876540002", referral_code="PABILL12")
        order, item, prod = make_test_order_with_item(db_session, user, quantity=2, order_number="ORD-SEQ-01", idempotency_key="idemp-seq-01")

        b1 = BillingId(
            billing_number="AGD-000201",
            sequence_number=201,
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

        b2 = BillingId(
            billing_number="AGD-000202",
            sequence_number=201,  # duplicate sequence
            order_id=order.id,
            order_item_id=item.id,
            unit_index=2,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(b2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_same_order_item_unit_cannot_receive_duplicate_billing_ids(self, db_session):
        """Composite constraint (order_item_id, unit_index) prevents allocating twice for the same unit."""
        user = make_test_user(db_session, phone="9876540003", referral_code="PABILL13")
        order, item, prod = make_test_order_with_item(db_session, user, quantity=2, order_number="ORD-UNIT-01", idempotency_key="idemp-unit-01")

        b1 = BillingId(
            billing_number="AGD-000201",
            sequence_number=201,
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

        # Attempt to insert another BillingId for the exact same order_item unit (unit_index=1)
        b2 = BillingId(
            billing_number="AGD-000202",
            sequence_number=202,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=1,  # duplicate unit index on same order item!
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add(b2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_different_unit_indexes_on_same_order_item_succeeds(self, db_session):
        """Item with quantity 2 receives unit_index 1 and 2 successfully."""
        user = make_test_user(db_session, phone="9876540004", referral_code="PABILL14")
        order, item, prod = make_test_order_with_item(db_session, user, quantity=2, order_number="ORD-UNIT-02", idempotency_key="idemp-unit-02")

        b1 = BillingId(
            billing_number="AGD-000201",
            sequence_number=201,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=1,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        b2 = BillingId(
            billing_number="AGD-000202",
            sequence_number=202,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=2,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        db_session.add_all([b1, b2])
        db_session.commit()

        db_session.refresh(order)
        assert len(order.billing_ids) == 2
        assert {b.unit_index for b in order.billing_ids} == {1, 2}

    def test_billing_engine_claim_unique_billing_id_constraint(self, db_session):
        """One Billing ID must have at most one engine claim (uq_billing_engine_claims_billing_id)."""
        user = make_test_user(db_session, phone="9876540005", referral_code="PABILL15")
        order, item, prod = make_test_order_with_item(db_session, user, quantity=1, order_number="ORD-CLM-01", idempotency_key="idemp-clm-01")

        b1 = BillingId(
            billing_number="AGD-000205",
            sequence_number=205,
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

        claim1 = BillingEngineClaim(
            billing_id=b1.id,
            engine=Programme.PLAN_A,
            status="PENDING",
        )
        db_session.add(claim1)
        db_session.commit()

        # Attempt to insert a second engine claim for the same billing_id
        claim2 = BillingEngineClaim(
            billing_id=b1.id,
            engine=Programme.PLAN_B,
            status="PENDING",
        )
        db_session.add(claim2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_correct_foreign_key_relationships(self, db_session):
        """Verify ORM relationships between Order, OrderItem, User, Product, BillingId, and BillingEngineClaim."""
        user = make_test_user(db_session, phone="9876540006", referral_code="PABILL16")
        order, item, prod = make_test_order_with_item(db_session, user, quantity=1, order_number="ORD-REL-01", idempotency_key="idemp-rel-01")

        b1 = BillingId(
            billing_number="AGD-000206",
            sequence_number=206,
            order_id=order.id,
            order_item_id=item.id,
            unit_index=1,
            user_id=user.id,
            product_id=prod.id,
            programme=Programme.PLAN_A,
            status="ALLOCATED",
        )
        claim = BillingEngineClaim(
            billing_id_rel=b1,
            engine=Programme.PLAN_A,
            status="PENDING",
        )
        db_session.add_all([b1, claim])
        db_session.commit()

        db_session.refresh(order)
        db_session.refresh(item)
        db_session.refresh(b1)

        assert b1 in order.billing_ids
        assert b1 in item.billing_ids
        assert b1.user.id == user.id
        assert b1.product.id == prod.id
        assert b1.engine_claim is not None
        assert b1.engine_claim.engine == Programme.PLAN_A
        assert b1.engine_claim.billing_id_rel.id == b1.id

    def test_correct_programme_values(self, db_session):
        """BillingId and BillingEngineClaim accept both PLAN_A and PLAN_B programmes."""
        user_a = make_test_user(db_session, phone="9876540007", programme=Programme.PLAN_A, referral_code="PABILL17")
        order_a, item_a, prod_a = make_test_order_with_item(db_session, user_a, quantity=1, order_number="ORD-PRG-A", idempotency_key="idemp-prg-a")

        user_b = make_test_user(db_session, phone="9876540008", programme=Programme.PLAN_B, referral_code="PBBILL18")
        order_b, item_b, prod_b = make_test_order_with_item(db_session, user_b, quantity=1, order_number="ORD-PRG-B", idempotency_key="idemp-prg-b")

        b_a = BillingId(
            billing_number="AGD-000207",
            sequence_number=207,
            order_id=order_a.id,
            order_item_id=item_a.id,
            unit_index=1,
            user_id=user_a.id,
            product_id=prod_a.id,
            programme=Programme.PLAN_A,
        )
        b_b = BillingId(
            billing_number="AGD-000208",
            sequence_number=208,
            order_id=order_b.id,
            order_item_id=item_b.id,
            unit_index=1,
            user_id=user_b.id,
            product_id=prod_b.id,
            programme=Programme.PLAN_B,
        )
        db_session.add_all([b_a, b_b])
        db_session.commit()

        db_session.refresh(b_a)
        db_session.refresh(b_b)
        assert b_a.programme == Programme.PLAN_A
        assert b_b.programme == Programme.PLAN_B

    def test_order_fulfilment_tracking_defaults_and_updates(self, db_session):
        """Order is_fulfilled defaults to False, fulfilled_at defaults to None, and updates cleanly."""
        user = make_test_user(db_session, phone="9876540009", referral_code="PABILL19")
        order, _, _ = make_test_order_with_item(db_session, user, quantity=1, order_number="ORD-FLF-01", idempotency_key="idemp-flf-01")

        db_session.refresh(order)
        assert order.is_fulfilled is False
        assert order.fulfilled_at is None

        now = datetime.now(timezone.utc)
        order.is_fulfilled = True
        order.fulfilled_at = now
        db_session.commit()

        db_session.refresh(order)
        assert order.is_fulfilled is True
        assert order.fulfilled_at is not None


# ---------------------------------------------------------------------------
# 3. Alembic Migration Lifecycle Tests
# ---------------------------------------------------------------------------

def _get_alembic_revision(revision_id: str):
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision(revision_id)
    assert rev is not None, f"Revision {revision_id} not found"
    return rev


class TestBillingMigrationLifecycleSQLite:
    """Validate Alembic migration b7f2d4e8c1a9 upgrade -> downgrade -> re-upgrade."""

    def test_migration_upgrade_downgrade_reupgrade(self):
        """Test schema migration lifecycle on an isolated SQLite database."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # 1. Create baseline schema (pre-WP-6, as of a8f5c3b1e9d2)
        # Create minimal required tables: alembic_version, users, addresses, products, orders, order_items
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('a8f5c3b1e9d2')"))
            conn.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone VARCHAR(15) NOT NULL,
                    full_name VARCHAR(100),
                    password_hash VARCHAR(255),
                    role VARCHAR(20) NOT NULL,
                    programme VARCHAR(20) NOT NULL DEFAULT 'LEGACY',
                    account_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                    referral_code VARCHAR(20),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    price NUMERIC(10, 2) NOT NULL,
                    stock INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    recipient_name VARCHAR(100) NOT NULL,
                    phone VARCHAR(15) NOT NULL,
                    address_line1 VARCHAR(255) NOT NULL,
                    city VARCHAR(100) NOT NULL,
                    state VARCHAR(100) NOT NULL,
                    postal_code VARCHAR(10) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_number VARCHAR(32) NOT NULL,
                    idempotency_key VARCHAR(64) NOT NULL,
                    user_id INTEGER NOT NULL,
                    address_id INTEGER NOT NULL,
                    total_amount NUMERIC(10, 2) NOT NULL,
                    order_status VARCHAR(32) NOT NULL DEFAULT 'pending_payment',
                    payment_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    payment_reference VARCHAR(100),
                    applied_referral_code VARCHAR(20),
                    is_first_successful_order BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    product_name VARCHAR(255) NOT NULL,
                    unit_price NUMERIC(10, 2) NOT NULL,
                    quantity INTEGER NOT NULL,
                    line_total NUMERIC(10, 2) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

        rev = _get_alembic_revision("b7f2d4e8c1a9")

        # 2. UPGRADE
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.upgrade()
            conn.execute(text("UPDATE alembic_version SET version_num = 'b7f2d4e8c1a9'"))

        # Verify tables and columns after upgrade
        insp = inspect(engine)
        table_names = insp.get_table_names()
        assert "billing_counters" in table_names
        assert "billing_ids" in table_names
        assert "billing_engine_claims" in table_names

        order_cols = {c["name"] for c in insp.get_columns("orders")}
        assert "is_fulfilled" in order_cols
        assert "fulfilled_at" in order_cols

        # Verify initial counter seeded
        with engine.begin() as conn:
            val = conn.execute(text("SELECT current_value FROM billing_counters WHERE sequence_name = 'GLOBAL_BILLING_ID'")).scalar()
            assert val == 200

        # 3. DOWNGRADE
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.downgrade()
            conn.execute(text("UPDATE alembic_version SET version_num = 'a8f5c3b1e9d2'"))

        insp = inspect(engine)
        table_names_down = insp.get_table_names()
        assert "billing_engine_claims" not in table_names_down
        assert "billing_ids" not in table_names_down
        assert "billing_counters" not in table_names_down

        order_cols_down = {c["name"] for c in insp.get_columns("orders")}
        assert "is_fulfilled" not in order_cols_down
        assert "fulfilled_at" not in order_cols_down

        # 4. RE-UPGRADE
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.upgrade()
            conn.execute(text("UPDATE alembic_version SET version_num = 'b7f2d4e8c1a9'"))

        insp = inspect(engine)
        table_names_re = insp.get_table_names()
        assert "billing_counters" in table_names_re
        assert "billing_ids" in table_names_re
        assert "billing_engine_claims" in table_names_re
