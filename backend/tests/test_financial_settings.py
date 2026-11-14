from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.core.database import Base
from app.core.money import Money
from app.models.enums import Programme, SettingAction, UserRole
from app.models.financial_settings import FinancialSetting, FinancialSettingHistory
from app.models.user import User


@pytest.mark.unit
class TestFinancialSettingsModelUnit:
    """Unit tests for FinancialSetting and FinancialSettingHistory ORM definitions."""

    def test_model_fields_and_money_helpers(self) -> None:
        """Verify model fields, exact precision preservation, and Money conversion helpers."""
        setting = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="OP_COST_RATE",
            setting_value=Decimal("0.046667"),
            currency="INR",
            description="Operational Cost deduction rate for Plan A",
            version=1,
            effective_from=datetime(2026, 1, 1, 0, 0, 0),
            effective_to=None,
            is_active=True,
        )

        assert setting.programme == Programme.PLAN_A
        assert setting.setting_key == "OP_COST_RATE"
        assert setting.setting_value == Decimal("0.046667")
        assert setting.currency == "INR"
        assert setting.version == 1
        assert setting.as_rate() == Decimal("0.046667")

        # Money helper converts without silent rounding
        setting_money = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            setting_value=Decimal("750.000000"),
            currency="INR",
            version=1,
            effective_from=datetime(2026, 1, 1, 0, 0, 0),
        )
        m = setting_money.as_money()
        assert isinstance(m, Money)
        assert m.amount == Decimal("750.000000")
        assert m.currency == "INR"
        assert setting_money.money == Money("750.00", "INR")

        # Setter updates both value and currency
        setting_money.money = Money("800.50", "INR")
        assert setting_money.setting_value == Decimal("800.50")
        assert setting_money.currency == "INR"

        with pytest.raises(TypeError, match="Expected a Money instance"):
            setting_money.money = Decimal("800.50")  # type: ignore

    def test_setting_history_model_fields(self) -> None:
        """Verify FinancialSettingHistory audit model fields."""
        history = FinancialSettingHistory(
            setting_id=1,
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            old_value=Decimal("750.000000"),
            new_value=Decimal("800.000000"),
            version=2,
            action=SettingAction.UPDATED,
            reason="Annual commission rate update",
            changed_by_id=10,
        )

        assert history.setting_id == 1
        assert history.programme == Programme.PLAN_A
        assert history.setting_key == "COMMISSION_GROSS"
        assert history.old_value == Decimal("750.000000")
        assert history.new_value == Decimal("800.000000")
        assert history.version == 2
        assert history.action == SettingAction.UPDATED
        assert history.reason == "Annual commission rate update"


@pytest.mark.unit
class TestFinancialSettingsDatabaseInvariants:
    """Tests executing against the isolated test database session (in-memory SQLite)."""

    def test_crud_and_relationship_with_user(self, db_session: Session) -> None:
        """Verify persistence, retrieval, and created_by relationship navigation."""
        admin = User(
            full_name="Financial Admin",
            phone="9876543210",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db_session.add(admin)
        db_session.flush()

        t_start = datetime(2026, 1, 1, 0, 0, 0)
        setting = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            setting_value=Decimal("750.000000"),
            currency="INR",
            description="Gross commission benchmark for Plan A",
            version=1,
            effective_from=t_start,
            effective_to=None,
            is_active=True,
            created_by_id=admin.id,
        )
        db_session.add(setting)
        db_session.flush()

        audit = FinancialSettingHistory(
            setting_id=setting.id,
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            old_value=None,
            new_value=Decimal("750.000000"),
            version=1,
            action=SettingAction.CREATED,
            reason="Initial system seed",
            changed_by_id=admin.id,
        )
        db_session.add(audit)
        db_session.flush()

        # Query and verify relationships
        saved = db_session.get(FinancialSetting, setting.id)
        assert saved is not None
        assert saved.created_by is not None
        assert saved.created_by.id == admin.id
        assert len(saved.history) == 1
        assert saved.history[0].action == SettingAction.CREATED

    def test_unique_constraint_enforces_version_uniqueness(self, db_session: Session) -> None:
        """Verify database UniqueConstraint('programme', 'setting_key', 'version') rejects duplicate version inserts."""
        t_start = datetime(2026, 1, 1, 0, 0, 0)
        s1 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="TDS_RATE",
            setting_value=Decimal("0.020000"),
            version=1,
            effective_from=t_start,
        )
        db_session.add(s1)
        db_session.flush()

        # Attempt to insert identical version 1 for the same programme and key
        s2 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="TDS_RATE",
            setting_value=Decimal("0.025000"),
            version=1,
            effective_from=t_start,
        )
        db_session.add(s2)

        with pytest.raises(IntegrityError):
            db_session.flush()

        db_session.rollback()

    def test_independent_sessions_unique_constraint_and_retry_simulation(self, test_engine: Engine) -> None:
        """Verify independent sessions enforce unique constraint and simulate the Step 2.3 rollback/retry flow."""
        SessionMaker = sessionmaker(bind=test_engine)
        session1 = SessionMaker()
        session2 = SessionMaker()
        try:
            t_start = datetime(2026, 1, 1, 0, 0, 0)
            s1 = FinancialSetting(
                programme=Programme.PLAN_A,
                setting_key="OPERATIONAL_COST_RATE",
                setting_value=Decimal("0.050000"),
                version=1,
                effective_from=t_start,
            )
            session1.add(s1)
            session1.commit()

            # Session 2 attempts duplicate version 1 insert
            s2_duplicate = FinancialSetting(
                programme=Programme.PLAN_A,
                setting_key="OPERATIONAL_COST_RATE",
                setting_value=Decimal("0.060000"),
                version=1,
                effective_from=t_start,
            )
            session2.add(s2_duplicate)
            with pytest.raises(IntegrityError):
                session2.commit()

            session2.rollback()

            # Planned Step 2.3 retry mechanics after rollback:
            # Query the newly committed record, determine next version, and insert safely
            existing = (
                session2.execute(
                    select(FinancialSetting)
                    .where(
                        FinancialSetting.programme == Programme.PLAN_A,
                        FinancialSetting.setting_key == "OPERATIONAL_COST_RATE",
                    )
                    .order_by(FinancialSetting.version.desc())
                )
                .scalars()
                .first()
            )
            assert existing is not None
            assert existing.version == 1

            s2_next = FinancialSetting(
                programme=Programme.PLAN_A,
                setting_key="OPERATIONAL_COST_RATE",
                setting_value=Decimal("0.060000"),
                version=existing.version + 1,
                effective_from=datetime(2026, 2, 1, 0, 0, 0),
            )
            session2.add(s2_next)
            session2.commit()

            assert s2_next.version == 2
        finally:
            session1.close()
            session2.close()

    def test_historical_settings_resolution_includes_inactive_superseded_versions(self, db_session: Session) -> None:
        """Verify historical transactions resolve by timestamp even if is_active is now False (Safeguard 1).

        Confirms exact effective-date interval semantics:
          - effective_from is INCLUSIVE (<=).
          - effective_to is EXCLUSIVE (>).
          - A transaction at the exact boundary timestamp switches to the new version with zero overlap.
        """
        t_v1_start = datetime(2026, 1, 1, 0, 0, 0)
        t_v2_start = datetime(2026, 2, 1, 0, 0, 0)

        # Version 1 was active in January, then superseded on Feb 1
        v1 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            setting_value=Decimal("700.000000"),
            version=1,
            effective_from=t_v1_start,
            effective_to=t_v2_start,
            is_active=False,  # Marked False because version 2 is now current
        )

        # Version 2 took effect Feb 1 onwards
        v2 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            setting_value=Decimal("750.000000"),
            version=2,
            effective_from=t_v2_start,
            effective_to=None,
            is_active=True,
        )
        db_session.add_all([v1, v2])
        db_session.flush()

        def resolve_setting(target_time: datetime) -> FinancialSetting | None:
            stmt = (
                select(FinancialSetting)
                .where(
                    FinancialSetting.programme == Programme.PLAN_A,
                    FinancialSetting.setting_key == "COMMISSION_GROSS",
                    FinancialSetting.effective_from <= target_time,
                    (FinancialSetting.effective_to.is_(None) | (FinancialSetting.effective_to > target_time)),
                )
                .order_by(FinancialSetting.effective_from.desc(), FinancialSetting.version.desc())
                .limit(1)
            )
            return db_session.execute(stmt).scalars().first()

        # 1. Query for a transaction that occurred on Jan 15 (during v1's effective window)
        # Invariant: Must resolve v1 (₹700.00), despite is_active == False
        resolved_jan = resolve_setting(datetime(2026, 1, 15, 12, 0, 0))
        assert resolved_jan is not None
        assert resolved_jan.version == 1
        assert resolved_jan.setting_value == Decimal("700.000000")
        assert resolved_jan.is_active is False

        # 2. Inclusive lower bound of Version 1: exact start at 2026-01-01 00:00:00
        resolved_boundary_v1 = resolve_setting(t_v1_start)
        assert resolved_boundary_v1 is not None
        assert resolved_boundary_v1.version == 1

        # 3. Exact boundary handoff at 2026-02-01 00:00:00:
        # v1.effective_to is 2026-02-01 00:00:00 (exclusive, so effective_to > t is False for v1).
        # v2.effective_from is 2026-02-01 00:00:00 (inclusive, so effective_from <= t is True for v2).
        # Must resolve Version 2!
        resolved_handoff = resolve_setting(t_v2_start)
        assert resolved_handoff is not None
        assert resolved_handoff.version == 2
        assert resolved_handoff.setting_value == Decimal("750.000000")

        # 4. Query for a transaction that occurred on Feb 15 (during v2's effective window)
        resolved_feb = resolve_setting(datetime(2026, 2, 15, 12, 0, 0))
        assert resolved_feb is not None
        assert resolved_feb.version == 2
        assert resolved_feb.setting_value == Decimal("750.000000")
        assert resolved_feb.is_active is True

        # 5. Query for a timestamp before Version 1 inception: resolves None
        resolved_before = resolve_setting(datetime(2025, 12, 31, 23, 59, 59))
        assert resolved_before is None

    def test_equal_effective_dates_produce_empty_interval(self, db_session: Session) -> None:
        """Verify that setting effective_to equal to effective_from produces an empty valid window [t, t)."""
        t_point = datetime(2026, 6, 1, 0, 0, 0)
        zero_window = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="ZERO_WINDOW_RATE",
            setting_value=Decimal("0.100000"),
            version=1,
            effective_from=t_point,
            effective_to=t_point,  # Equal dates: [t_point, t_point) is an empty set
            is_active=False,
        )
        db_session.add(zero_window)
        db_session.flush()

        stmt = (
            select(FinancialSetting)
            .where(
                FinancialSetting.programme == Programme.PLAN_A,
                FinancialSetting.setting_key == "ZERO_WINDOW_RATE",
                FinancialSetting.effective_from <= t_point,
                (FinancialSetting.effective_to.is_(None) | (FinancialSetting.effective_to > t_point)),
            )
        )
        res = db_session.execute(stmt).scalars().first()
        # Because effective_to > t_point evaluates to False, no record matches
        assert res is None

    def test_programme_isolation_plan_a_and_plan_b(self, db_session: Session) -> None:
        """Verify setting keys with the same name are strictly isolated across programmes."""
        t_start = datetime(2026, 1, 1, 0, 0, 0)
        sa = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_GROSS",
            setting_value=Decimal("750.000000"),
            version=1,
            effective_from=t_start,
        )
        sb = FinancialSetting(
            programme=Programme.PLAN_B,
            setting_key="COMMISSION_GROSS",
            setting_value=Decimal("500.000000"),
            version=1,
            effective_from=t_start,
        )
        db_session.add_all([sa, sb])
        db_session.flush()

        res_a = db_session.execute(
            select(FinancialSetting).where(
                FinancialSetting.programme == Programme.PLAN_A,
                FinancialSetting.setting_key == "COMMISSION_GROSS",
            )
        ).scalar_one()
        res_b = db_session.execute(
            select(FinancialSetting).where(
                FinancialSetting.programme == Programme.PLAN_B,
                FinancialSetting.setting_key == "COMMISSION_GROSS",
            )
        ).scalar_one()

        assert res_a.setting_value == Decimal("750.000000")
        assert res_b.setting_value == Decimal("500.000000")


@pytest.mark.unit
class TestFinancialSettingsAlembicMigration:
    """Verify linear migration history, single head, and DDL execution."""

    def test_alembic_financial_settings_migration_linear_and_valid(self) -> None:
        """Verify Alembic migration chain is linear, heads == 1, and dry-run DDL executes cleanly."""
        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()

        # 1. Exactly one single head
        assert len(heads) == 1
        assert heads[0] == "79b742f969d6"

        # 2. Linear down_revision chain including new WP-3 head and existing chain
        head_rev = script.get_revision("79b742f969d6")
        assert head_rev is not None
        assert head_rev.down_revision == "2270de96fe73"

        rev = script.get_revision("2270de96fe73")
        assert rev is not None
        assert rev.down_revision == "4bed57dc0ac3"

        rev_cart = script.get_revision("4bed57dc0ac3")
        assert rev_cart is not None
        assert rev_cart.down_revision == "c895961fa0f1"

        rev_cart_table = script.get_revision("c895961fa0f1")
        assert rev_cart_table is not None
        assert rev_cart_table.down_revision == "71dba0e1425f"

        rev_otp = script.get_revision("71dba0e1425f")
        assert rev_otp is not None
        assert rev_otp.down_revision == "ed2396d847bc"

        rev_root = script.get_revision("ed2396d847bc")
        assert rev_root is not None
        assert rev_root.down_revision is None

        # Verify complete linear chain without branches or altered revision IDs
        expected_chain = [
            "79b742f969d6",
            "2270de96fe73",
            "4bed57dc0ac3",
            "c895961fa0f1",
            "71dba0e1425f",
            "ed2396d847bc",
        ]
        actual_chain = [r.revision for r in script.walk_revisions()]
        assert actual_chain == expected_chain

        # 3. Dry-run DDL generation for MySQL dialect
        ctx = MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True})
        with Operations.context(ctx):
            rev.module.upgrade()
            rev.module.downgrade()

    def test_migration_upgrade_and_downgrade_on_sqlite_engine(self) -> None:
        """Verify migration upgrade and downgrade execute successfully against a live SQLite engine."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # Create prerequisite tables (excluding the tables introduced by this migration)
        prerequisite_tables = [
            t
            for name, t in Base.metadata.tables.items()
            if name not in ("financial_settings", "financial_settings_history")
        ]
        Base.metadata.create_all(bind=engine, tables=prerequisite_tables)

        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        script = ScriptDirectory.from_config(cfg)
        rev = script.get_revision("2270de96fe73")

        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                # Upgrade creates tables
                rev.module.upgrade()

                # Verify tables exist and can accept queries
                tables = conn.dialect.get_table_names(conn)
                assert "financial_settings" in tables
                assert "financial_settings_history" in tables

                # Downgrade drops tables cleanly
                rev.module.downgrade()
                tables_after = conn.dialect.get_table_names(conn)
                assert "financial_settings" not in tables_after
                assert "financial_settings_history" not in tables_after
