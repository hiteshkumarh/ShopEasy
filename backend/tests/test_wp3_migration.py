"""Automated upgrade and downgrade lifecycle tests for WP-3 Migration A (79b742f969d6).

Validates:
  1. Upgrade test:
     - Starts from the schema immediately before Migration A (revision 2270de96fe73).
     - Applies Migration A (revision 79b742f969d6) in an isolated test database.
     - Verifies all expected columns, tables, indexes, foreign keys, defaults, and constraints.
     - Verifies existing users receive LEGACY and ACTIVE defaults.
     - Verifies existing tables and records remain intact.
  2. Downgrade test:
     - Downgrades only Migration A back to 2270de96fe73.
     - Verifies all four WP-3 tables are dropped.
     - Verifies the two new users columns and three new indexes are removed.
     - Verifies pre-existing users columns, tables, and records remain intact.
     - Verifies the Alembic revision returns to 2270de96fe73.
  3. Re-upgrade test:
     - Re-applies Migration A to 79b742f969d6.
     - Verifies the schema is restored cleanly.
  4. Test safety & isolation:
     - Uses isolated in-memory SQLite engine for comprehensive unit tests.
     - Uses isolated MySQL 8 test database (via TEST_MYSQL_URL) for MySQL DDL behavior in CI.
     - Never touches TiDB Cloud, production, or application databases.
"""

import os
from pathlib import Path
import re
from typing import Generator
import urllib.parse
import uuid
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Engine,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.pool import StaticPool
from tests.conftest import validate_test_mysql_url


def _get_migration_revision(revision_id: str):
    """Load Alembic ScriptDirectory and retrieve the specified revision object."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision(revision_id)
    assert rev is not None, f"Revision {revision_id} not found in migration history"
    return rev


def _create_pre_wp3_sqlite_schema(engine: Engine) -> None:
    """Create the pre-WP-3 baseline schema (as of 2270de96fe73) with a legacy user."""
    with engine.begin() as conn:
        # 1. alembic_version table initialized to 2270de96fe73
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('2270de96fe73')")
        )

        # 2. Pre-WP-3 users table
        conn.execute(
            text(
                """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name VARCHAR(100) NOT NULL,
                phone VARCHAR(15) NOT NULL,
                password_hash VARCHAR(255),
                role VARCHAR(20) NOT NULL,
                referral_code VARCHAR(20),
                referred_by_id INTEGER,
                is_active BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_users_phone UNIQUE (phone),
                CONSTRAINT uq_users_referral_code UNIQUE (referral_code),
                FOREIGN KEY (referred_by_id) REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT
            )
            """
            )
        )

        # 3. Pre-WP-3 financial_settings table (created in 2270de96fe73)
        conn.execute(
            text(
                """
            CREATE TABLE financial_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                programme VARCHAR(20) NOT NULL,
                setting_key VARCHAR(64) NOT NULL,
                setting_value NUMERIC(18, 6) NOT NULL,
                currency VARCHAR(3) NOT NULL DEFAULT 'INR',
                description VARCHAR(255),
                version INTEGER NOT NULL,
                effective_from DATETIME NOT NULL,
                effective_to DATETIME,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_by_id INTEGER,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE RESTRICT ON UPDATE CASCADE
            )
            """
            )
        )

        # 4. Insert baseline data: an existing user and an existing financial setting
        conn.execute(
            text(
                """
            INSERT INTO users (full_name, phone, role, referral_code, is_active)
            VALUES ('Pre-Existing Legacy Customer', '9876500001', 'customer', 'LEGACY_REF_01', 1)
            """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO financial_settings (programme, setting_key, setting_value, version, effective_from, is_active)
            VALUES ('LEGACY', 'PLATFORM_FEE_PERCENT', 5.000000, 1, CURRENT_TIMESTAMP, 1)
            """
            )
        )


def _create_pre_wp3_mysql_schema(engine: Engine) -> None:
    """Create the pre-WP-3 baseline schema (as of revision 2270de96fe73) on isolated MySQL 8."""
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('2270de96fe73')")
        )
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    full_name VARCHAR(100) NOT NULL,
                    phone VARCHAR(15) NOT NULL,
                    password_hash VARCHAR(255) NULL,
                    role ENUM('customer', 'admin') NOT NULL DEFAULT 'customer',
                    referral_code VARCHAR(20) NULL,
                    referred_by_id INT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    CONSTRAINT uq_users_phone UNIQUE (phone),
                    CONSTRAINT uq_users_referral_code UNIQUE (referral_code),
                    CONSTRAINT fk_users_referred_by FOREIGN KEY (referred_by_id) REFERENCES users(id) ON UPDATE RESTRICT ON DELETE RESTRICT
                ) ENGINE=InnoDB
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE financial_settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    programme ENUM('PLAN_A', 'PLAN_B', 'LEGACY') NOT NULL,
                    setting_key VARCHAR(64) NOT NULL,
                    setting_value DECIMAL(18, 6) NOT NULL,
                    currency VARCHAR(3) NOT NULL DEFAULT 'INR',
                    description VARCHAR(255) NULL,
                    version INT NOT NULL,
                    effective_from DATETIME NOT NULL,
                    effective_to DATETIME NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_by_id INT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    CONSTRAINT fk_fin_settings_created_by FOREIGN KEY (created_by_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT
                ) ENGINE=InnoDB
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, full_name, phone, role, referral_code, is_active)
                VALUES (101, 'MySQL Baseline User', '+919999900101', 'customer', 'REF_MYSQL_101', 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO financial_settings (programme, setting_key, setting_value, version, effective_from, is_active)
                VALUES ('LEGACY', 'PLATFORM_FEE_PERCENT', 5.000000, 1, CURRENT_TIMESTAMP, 1)
                """
            )
        )


@pytest.mark.unit
class TestWP3MigrationLifecycleSQLite:
    """End-to-end upgrade, downgrade, and re-upgrade tests on isolated SQLite."""

    def test_migration_upgrade_downgrade_reupgrade_sqlite(self) -> None:
        """Verify full lifecycle: baseline -> upgrade -> downgrade -> re-upgrade on isolated SQLite."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        # Establish baseline schema as of 2270de96fe73
        _create_pre_wp3_sqlite_schema(engine)
        rev = _get_migration_revision("79b742f969d6")

        # ------------------------------------------------------------------
        # 1. UPGRADE PHASE
        # ------------------------------------------------------------------
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.upgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = '79b742f969d6'")
            )

        # Verify alembic_version is 79b742f969d6
        with engine.connect() as conn:
            current_version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            assert current_version == "79b742f969d6"

        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        # Verify all four WP-3 tables exist
        wp3_tables = {
            "account_status_history",
            "referral_relationships",
            "audit_logs",
            "notifications",
        }
        for tbl in wp3_tables:
            assert tbl in table_names, f"Table {tbl} was not created during upgrade"

        # Verify existing tables remained intact
        assert "users" in table_names
        assert "financial_settings" in table_names

        # Verify columns added to users table
        user_columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert "programme" in user_columns, "Column 'programme' missing from users"
        assert "account_status" in user_columns, "Column 'account_status' missing from users"

        # Verify existing user received server defaults
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT full_name, phone, role, referral_code, programme, account_status, is_active "
                    "FROM users WHERE id = 1"
                )
            ).fetchone()
            assert row is not None
            assert row[0] == "Pre-Existing Legacy Customer"
            assert row[1] == "9876500001"
            assert row[2] == "customer"
            assert row[3] == "LEGACY_REF_01"
            assert row[4] == "LEGACY", "Existing user did not receive default programme='LEGACY'"
            assert row[5] == "ACTIVE", "Existing user did not receive default account_status='ACTIVE'"
            assert row[6] == 1

            # Verify existing financial setting was untouched
            fs_row = conn.execute(
                text("SELECT setting_key, setting_value FROM financial_settings WHERE id = 1")
            ).fetchone()
            assert fs_row is not None
            assert fs_row[0] == "PLATFORM_FEE_PERCENT"

        # Verify indexes created on users table
        user_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("users")}
        assert "idx_users_programme" in user_indexes
        assert user_indexes["idx_users_programme"] == ["programme"]
        assert "idx_users_account_status" in user_indexes
        assert user_indexes["idx_users_account_status"] == ["account_status"]
        assert "idx_users_prog_role" in user_indexes
        assert user_indexes["idx_users_prog_role"] == ["programme", "role"]

        # Verify indexes created on new tables
        rel_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("referral_relationships")}
        assert "idx_ref_rel_referrer" in rel_indexes
        assert "idx_ref_rel_code" in rel_indexes

        audit_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("audit_logs")}
        assert "idx_audit_logs_entity" in audit_indexes
        assert "idx_audit_logs_actor" in audit_indexes
        assert "idx_audit_logs_action" in audit_indexes
        assert "idx_audit_logs_created" in audit_indexes

        notif_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("notifications")}
        assert "idx_notifications_user_read" in notif_indexes
        assert "idx_notifications_user_prog" in notif_indexes

        hist_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("account_status_history")}
        assert "idx_account_status_hist_user" in hist_indexes
        assert "idx_account_status_hist_changed_by" in hist_indexes

        # Verify foreign keys on new tables
        hist_fks = inspector.get_foreign_keys("account_status_history")
        hist_fk_targets = {fk["referred_table"]: fk["referred_columns"] for fk in hist_fks}
        assert "users" in hist_fk_targets

        rel_fks = inspector.get_foreign_keys("referral_relationships")
        rel_fk_targets = {fk["referred_table"]: fk["referred_columns"] for fk in rel_fks}
        assert "users" in rel_fk_targets

        # ------------------------------------------------------------------
        # 2. DOWNGRADE PHASE
        # ------------------------------------------------------------------
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.downgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = '2270de96fe73'")
            )

        # Verify alembic_version is reverted to 2270de96fe73
        with engine.connect() as conn:
            reverted_version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            assert reverted_version == "2270de96fe73"

        inspector_downgrade = inspect(engine)
        table_names_downgrade = set(inspector_downgrade.get_table_names())

        # Verify all four WP-3 tables are dropped
        for tbl in wp3_tables:
            assert tbl not in table_names_downgrade, f"Table {tbl} was not dropped during downgrade"

        # Verify users and financial_settings remain
        assert "users" in table_names_downgrade
        assert "financial_settings" in table_names_downgrade

        # Verify columns removed from users table
        user_columns_downgrade = {c["name"] for c in inspector_downgrade.get_columns("users")}
        assert "programme" not in user_columns_downgrade
        assert "account_status" not in user_columns_downgrade
        assert "phone" in user_columns_downgrade
        assert "full_name" in user_columns_downgrade
        assert "is_active" in user_columns_downgrade

        # Verify indexes removed from users table
        user_indexes_downgrade = {i["name"] for i in inspector_downgrade.get_indexes("users")}
        assert "idx_users_programme" not in user_indexes_downgrade
        assert "idx_users_account_status" not in user_indexes_downgrade
        assert "idx_users_prog_role" not in user_indexes_downgrade

        # Verify pre-existing data is preserved after downgrade
        with engine.connect() as conn:
            row_downgrade = conn.execute(
                text("SELECT full_name, phone, role, referral_code, is_active FROM users WHERE id = 1")
            ).fetchone()
            assert row_downgrade is not None
            assert row_downgrade[0] == "Pre-Existing Legacy Customer"
            assert row_downgrade[1] == "9876500001"
            assert row_downgrade[4] == 1

        # ------------------------------------------------------------------
        # 3. RE-UPGRADE PHASE
        # ------------------------------------------------------------------
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.upgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = '79b742f969d6'")
            )

        inspector_re = inspect(engine)
        table_names_re = set(inspector_re.get_table_names())
        for tbl in wp3_tables:
            assert tbl in table_names_re, f"Table {tbl} was not restored during re-upgrade"

        user_columns_re = {c["name"] for c in inspector_re.get_columns("users")}
        assert "programme" in user_columns_re
        assert "account_status" in user_columns_re

        with engine.connect() as conn:
            final_version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            assert final_version == "79b742f969d6"
            user_re = conn.execute(
                text("SELECT programme, account_status FROM users WHERE id = 1")
            ).fetchone()
            assert user_re[0] == "LEGACY"
            assert user_re[1] == "ACTIVE"


@pytest.fixture
def isolated_mysql_migration_engine() -> Generator[Engine, None, None]:
    """Provide a uniquely named, validated, and strictly isolated MySQL 8 test database.

    Ownership & Safety Rules:
      1. Validates base TEST_MYSQL_URL cannot target remote hosts, TiDB, or non-test databases.
      2. Generates an isolated, uniquely suffixed database name: shopeasy_test_wp3_<hex>.
      3. Validates the generated database name with strict regex and validate_test_mysql_url.
      4. Executes CREATE DATABASE without IF NOT EXISTS; fails safely if name already exists.
      5. Tracks explicit creation ownership. Only drops the database in finally if this run created it.
      6. Safely validates and quotes the database identifier (`{db_name}`).
    """
    test_mysql_url = os.getenv("TEST_MYSQL_URL")
    if not test_mysql_url or not test_mysql_url.strip():
        pytest.skip("Skipping MySQL test: TEST_MYSQL_URL not configured")

    validate_test_mysql_url(test_mysql_url)

    # Generate a unique database name satisfying the shopeasy_test_ prefix
    db_suffix = uuid.uuid4().hex[:12]
    db_name = f"shopeasy_test_wp3_{db_suffix}"
    if not re.fullmatch(r"shopeasy_test_[a-z0-9_]{1,40}", db_name):
        raise RuntimeError(f"SAFETY VIOLATION: Malformed database identifier: {db_name}")

    parsed = urllib.parse.urlsplit(test_mysql_url.strip())
    isolated_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{db_name}", parsed.query, parsed.fragment)
    )
    validate_test_mysql_url(isolated_url)

    base_engine = create_engine(test_mysql_url.strip(), pool_pre_ping=True)
    created_by_this_run = False
    migration_engine = None

    try:
        # Create database without IF NOT EXISTS to guarantee exclusive ownership
        with base_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE `{db_name}`"))
            conn.commit()
        created_by_this_run = True

        migration_engine = create_engine(isolated_url, pool_pre_ping=True)
        _create_pre_wp3_mysql_schema(migration_engine)

        yield migration_engine
    finally:
        if migration_engine is not None:
            migration_engine.dispose()

        if created_by_this_run:
            with base_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE `{db_name}`"))
                conn.commit()

        base_engine.dispose()


@pytest.mark.mysql
class TestWP3MigrationLifecycleMySQL:
    """Upgrade, downgrade, and re-upgrade tests on isolated MySQL 8 (activated via TEST_MYSQL_URL)."""

    def test_migration_upgrade_downgrade_reupgrade_mysql(
        self, isolated_mysql_migration_engine: Engine
    ) -> None:
        """Verify full lifecycle and MySQL 8-specific DDL/constraints on isolated test database."""
        mysql_engine = isolated_mysql_migration_engine
        rev = _get_migration_revision("79b742f969d6")

        # ------------------------------------------------------------------
        # 1. UPGRADE TO 79b742f969d6 ON MYSQL 8
        # ------------------------------------------------------------------
        with mysql_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.upgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = '79b742f969d6'")
            )

        inspector_up = inspect(mysql_engine)
        tables_up = set(inspector_up.get_table_names())

        # A. Verify all four WP-3 tables exist
        assert "account_status_history" in tables_up
        assert "referral_relationships" in tables_up
        assert "audit_logs" in tables_up
        assert "notifications" in tables_up
        assert "users" in tables_up
        assert "financial_settings" in tables_up

        # B. Verify columns added to users
        cols_up = {c["name"] for c in inspector_up.get_columns("users")}
        assert "programme" in cols_up
        assert "account_status" in cols_up

        # C. Verify existing user received server defaults and financial setting is intact
        with mysql_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT full_name, phone, role, referral_code, programme, account_status, is_active "
                    "FROM users WHERE id = 101"
                )
            ).fetchone()
            assert row is not None
            assert row[0] == "MySQL Baseline User"
            assert row[1] == "+919999900101"
            assert row[4] == "LEGACY", "Existing user did not receive default programme='LEGACY'"
            assert row[5] == "ACTIVE", "Existing user did not receive default account_status='ACTIVE'"
            assert row[6] == 1

            fin_setting_row = conn.execute(
                text(
                    "SELECT programme, setting_key, setting_value, is_active "
                    "FROM financial_settings WHERE programme = 'LEGACY' AND setting_key = 'PLATFORM_FEE_PERCENT'"
                )
            ).fetchone()
            assert fin_setting_row is not None
            assert fin_setting_row[1] == "PLATFORM_FEE_PERCENT"
            assert float(fin_setting_row[2]) == 5.0

        # D. Verify MySQL 8 native ENUM storage and definitions via information_schema
        with mysql_engine.connect() as conn:
            current_db = conn.execute(text("SELECT DATABASE()")).scalar()
            assert current_db is not None
            assert current_db.startswith("shopeasy_test_")
            assert current_db not in ("shopeasy_arya", "shopeasy_app", "shopeasy_dev", "sys", "mysql")

            enum_rows = conn.execute(
                text(
                    "SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT, DATA_TYPE "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'users' "
                    "AND COLUMN_NAME IN ('programme', 'account_status')"
                ),
                {"db": current_db},
            ).fetchall()
            enum_dict = {r[0]: (r[1], r[2], r[3]) for r in enum_rows}

            # Programme native ENUM check
            assert "programme" in enum_dict
            assert enum_dict["programme"][2].lower() == "enum"
            assert "'PLAN_A'" in enum_dict["programme"][0]
            assert "'PLAN_B'" in enum_dict["programme"][0]
            assert "'LEGACY'" in enum_dict["programme"][0]
            assert "LEGACY" in str(enum_dict["programme"][1])

            # AccountStatus native ENUM check
            assert "account_status" in enum_dict
            assert enum_dict["account_status"][2].lower() == "enum"
            assert "'ACTIVE'" in enum_dict["account_status"][0]
            assert "'BLOCKED'" in enum_dict["account_status"][0]
            assert "'DEACTIVATED'" in enum_dict["account_status"][0]
            assert "ACTIVE" in str(enum_dict["account_status"][1])

        # E. Verify BIGINT primary key on audit_logs
        with mysql_engine.connect() as conn:
            bigint_row = conn.execute(
                text(
                    "SELECT DATA_TYPE, EXTRA "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'id'"
                ),
                {"db": current_db},
            ).fetchone()
            assert bigint_row is not None
            assert bigint_row[0].lower() == "bigint"
            assert "auto_increment" in bigint_row[1].lower()

        # F. Verify Boolean server defaults on MySQL 8
        with mysql_engine.connect() as conn:
            bool_rows = conn.execute(
                text(
                    "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_DEFAULT "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = :db AND ("
                    "(TABLE_NAME = 'referral_relationships' AND COLUMN_NAME = 'is_active') OR "
                    "(TABLE_NAME = 'notifications' AND COLUMN_NAME = 'is_read'))"
                ),
                {"db": current_db},
            ).fetchall()
            bool_defaults = {f"{r[0]}.{r[1]}": str(r[2]) for r in bool_rows}
            assert "1" in bool_defaults.get("referral_relationships.is_active", "")
            assert "0" in bool_defaults.get("notifications.is_read", "")

        # G. Verify MySQL 8 indexes
        user_indexes = {i["name"]: i["column_names"] for i in inspector_up.get_indexes("users")}
        assert "idx_users_programme" in user_indexes
        assert "idx_users_account_status" in user_indexes
        assert "idx_users_prog_role" in user_indexes
        assert user_indexes["idx_users_prog_role"] == ["programme", "role"]

        # H. Verify MySQL 8 self-referral CHECK constraint
        with mysql_engine.connect() as conn:
            with pytest.raises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO referral_relationships "
                        "(referee_id, referrer_id, referee_programme, referrer_programme, referral_code_used, binding_channel) "
                        "VALUES (101, 101, 'PLAN_A', 'PLAN_A', 'SELF_REF_CODE', 'REGISTRATION')"
                    )
                )

        # I. Verify MySQL 8 single-referee unique constraint
        with mysql_engine.begin() as conn:
            # Insert a second user as referrer
            conn.execute(
                text(
                    "INSERT INTO users (id, full_name, phone, role, referral_code, is_active) "
                    "VALUES (102, 'MySQL Referrer User', '+919999900102', 'customer', 'REF_MYSQL_102', 1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO referral_relationships "
                    "(referee_id, referrer_id, referee_programme, referrer_programme, referral_code_used, binding_channel) "
                    "VALUES (101, 102, 'PLAN_A', 'PLAN_A', 'REF_MYSQL_102', 'REGISTRATION')"
                )
            )
            # Attempt duplicate referee binding must raise IntegrityError
            with pytest.raises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO referral_relationships "
                        "(referee_id, referrer_id, referee_programme, referrer_programme, referral_code_used, binding_channel) "
                        "VALUES (101, 102, 'PLAN_A', 'PLAN_A', 'REF_MYSQL_102', 'CHECKOUT')"
                    )
                )

        # J. Verify MySQL 8 foreign-key RESTRICT on account_status_history
        with mysql_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO account_status_history (user_id, new_status, reason) "
                    "VALUES (101, 'BLOCKED', 'Test foreign key restrict on MySQL 8')"
                )
            )
            # Attempting to delete user 101 must fail due to foreign key RESTRICT
            with pytest.raises(Exception):
                conn.execute(text("DELETE FROM users WHERE id = 101"))

        # K. Verify MySQL 8 foreign-key CASCADE on notifications
        with mysql_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO notifications (user_id, programme, event_type, title, message) "
                    "VALUES (102, 'PLAN_A', 'SYSTEM_ALERT', 'Test Title', 'Test Message')"
                )
            )
            # First remove any foreign key dependencies on user 102 in referral_relationships
            conn.execute(text("DELETE FROM referral_relationships WHERE referrer_id = 102"))
            # Deleting user 102 should cascade to notifications
            conn.execute(text("DELETE FROM users WHERE id = 102"))
            notif_count = conn.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = 102")
            ).scalar()
            assert notif_count == 0

        # ------------------------------------------------------------------
        # 2. DOWNGRADE TO 2270de96fe73 ON MYSQL 8
        # ------------------------------------------------------------------
        with mysql_engine.begin() as conn:
            # Clean up child rows before running downgrade
            conn.execute(text("DELETE FROM account_status_history"))
            conn.execute(text("DELETE FROM referral_relationships"))
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.downgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = '2270de96fe73'")
            )

        inspector_down = inspect(mysql_engine)
        tables_down = set(inspector_down.get_table_names())
        assert "account_status_history" not in tables_down
        assert "referral_relationships" not in tables_down
        assert "audit_logs" not in tables_down
        assert "notifications" not in tables_down

        cols_down = {c["name"] for c in inspector_down.get_columns("users")}
        assert "programme" not in cols_down
        assert "account_status" not in cols_down
        assert "full_name" in cols_down
        assert "phone" in cols_down

        # Verify pre-existing user row and financial setting preserved across downgrade
        with mysql_engine.connect() as conn:
            row_down = conn.execute(
                text("SELECT full_name, phone, referral_code FROM users WHERE id = 101")
            ).fetchone()
            assert row_down is not None
            assert row_down[0] == "MySQL Baseline User"
            assert row_down[1] == "+919999900101"

            fin_down = conn.execute(
                text(
                    "SELECT setting_value FROM financial_settings "
                    "WHERE programme = 'LEGACY' AND setting_key = 'PLATFORM_FEE_PERCENT'"
                )
            ).fetchone()
            assert fin_down is not None
            assert float(fin_down[0]) == 5.0

        # ------------------------------------------------------------------
        # 3. RE-UPGRADE TO 79b742f969d6 ON MYSQL 8
        # ------------------------------------------------------------------
        with mysql_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                rev.module.upgrade()
            conn.execute(
                text("UPDATE alembic_version SET version_num = '79b742f969d6'")
            )

        inspector_re = inspect(mysql_engine)
        tables_re = set(inspector_re.get_table_names())
        assert "account_status_history" in tables_re
        assert "referral_relationships" in tables_re
        assert "audit_logs" in tables_re
        assert "notifications" in tables_re

        cols_re = {c["name"] for c in inspector_re.get_columns("users")}
        assert "programme" in cols_re
        assert "account_status" in cols_re

        with mysql_engine.connect() as conn:
            final_version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            assert final_version == "79b742f969d6"
            user_re = conn.execute(
                text("SELECT programme, account_status FROM users WHERE id = 101")
            ).fetchone()
            assert user_re[0] == "LEGACY"
            assert user_re[1] == "ACTIVE"

            fin_re = conn.execute(
                text(
                    "SELECT setting_value FROM financial_settings "
                    "WHERE programme = 'LEGACY' AND setting_key = 'PLATFORM_FEE_PERCENT'"
                )
            ).fetchone()
            assert fin_re is not None
            assert float(fin_re[0]) == 5.0

