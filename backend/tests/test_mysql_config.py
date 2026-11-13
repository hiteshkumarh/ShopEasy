import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.conftest import validate_test_mysql_url


@pytest.mark.unit
def test_registered_pytest_markers(pytestconfig) -> None:
    """1. Verify that 'unit', 'integration', and 'mysql' markers are properly registered in pytest.ini."""
    markers = pytestconfig.getini("markers")
    marker_names = [m.split(":")[0].strip() for m in markers]
    assert "unit" in marker_names
    assert "integration" in marker_names
    assert "mysql" in marker_names


@pytest.mark.mysql
def test_mysql_tests_skip_cleanly_when_no_url() -> None:
    """2. Verify that tests marked with 'mysql' skip cleanly when TEST_MYSQL_URL is absent."""
    # If TEST_MYSQL_URL is absent, conftest's skip_mysql_if_not_configured fixture
    # intercepts this test and skips before this body is executed.
    # If TEST_MYSQL_URL happens to be set, assert it is a valid test environment.
    assert os.getenv("TEST_MYSQL_URL") is not None


@pytest.mark.unit
def test_validator_accepts_valid_local_mysql_url() -> None:
    """3. Verify a valid local MySQL test URL (127.0.0.1) is accepted by the validator."""
    # Should not raise any exception
    validate_test_mysql_url("mysql+pymysql://testuser:testpass@127.0.0.1:3306/shopeasy_test_local")
    validate_test_mysql_url("mysql://testuser:testpass@127.0.0.1:3307/shopeasy_test_local")


@pytest.mark.unit
def test_validator_accepts_valid_ci_mysql_url() -> None:
    """4. Verify a valid CI-local MySQL test URL (localhost and ::1) is accepted by the validator."""
    validate_test_mysql_url("mysql+pymysql://root:root@localhost:3306/shopeasy_test_ci")
    validate_test_mysql_url("mysql+pymysql://root:root@[::1]:3306/shopeasy_test_ci")


@pytest.mark.unit
def test_validator_rejects_tidb_cloud_host() -> None:
    """5. Verify any TiDB Cloud hostname is strictly rejected."""
    tidb_urls = [
        "mysql+pymysql://user:pass@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/shopeasy_test_cloud",
        "mysql+pymysql://user:pass@tidbcloud.com:4000/shopeasy_test_cloud",
        "mysql+pymysql://user:pass@mycluster.tidbcloud.com:4000/shopeasy_test_cloud",
    ]
    for url in tidb_urls:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            validate_test_mysql_url(url)


@pytest.mark.unit
def test_validator_rejects_shopeasy_arya() -> None:
    """6. Verify targeting the live database shopeasy_arya is strictly rejected."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        validate_test_mysql_url("mysql+pymysql://root:pass@127.0.0.1:3306/shopeasy_arya")


@pytest.mark.unit
def test_validator_rejects_shopeasy_app() -> None:
    """7. Verify targeting the production database shopeasy_app is strictly rejected."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        validate_test_mysql_url("mysql+pymysql://root:pass@127.0.0.1:3306/shopeasy_app")


@pytest.mark.unit
@pytest.mark.parametrize("disallowed_db", ["shopeasy_dev", "sys", "test", "mysql", "information_schema"])
def test_validator_rejects_disallowed_databases(disallowed_db: str) -> None:
    """8. Verify shopeasy_dev, sys, test, and system databases are strictly rejected."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        validate_test_mysql_url(f"mysql+pymysql://root:pass@localhost:3306/{disallowed_db}")


@pytest.mark.unit
@pytest.mark.parametrize("remote_host", ["192.168.1.100", "10.0.0.5", "db.example.com", "remote-db.internal"])
def test_validator_rejects_remote_non_tidb_hosts(remote_host: str) -> None:
    """9. Verify non-local remote hosts are strictly rejected."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        validate_test_mysql_url(f"mysql+pymysql://root:pass@{remote_host}:3306/shopeasy_test_db")


@pytest.mark.unit
@pytest.mark.parametrize("unsupported_url", [
    "sqlite:///:memory:",
    "sqlite:///test.db",
    "postgresql://user:pass@localhost:5432/shopeasy_test_db",
    "oracle://user:pass@localhost:1521/shopeasy_test_db",
    "",
    "   ",
])
def test_validator_rejects_sqlite_and_unsupported_dialects(unsupported_url: str) -> None:
    """10. Verify SQLite and unsupported database dialects are strictly rejected."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        validate_test_mysql_url(unsupported_url)


@pytest.mark.unit
def test_invalid_urls_cannot_reach_connection_stage() -> None:
    """11. Verify unapproved MySQL URLs are stopped by the do_connect guard before opening sockets."""
    # Even if an engine was created directly, the do_connect guard must block it
    engine = create_engine("mysql+pymysql://user:pass@127.0.0.1:3306/shopeasy_dev")
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*prohibited database"):
        engine.connect()


@pytest.mark.unit
def test_existing_sqlite_fixtures_and_guard_intact(db_session: Session) -> None:
    """12. Verify default SQLite fixtures and connection guard continue functioning properly."""
    assert db_session is not None
    # Verify live TiDB Cloud host is blocked on connect
    fake_tidb = create_engine("mysql+pymysql://user:pass@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/shopeasy_test_db")
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*live TiDB Cloud host"):
        fake_tidb.connect()


@pytest.mark.unit
def test_ci_service_hostname_accepted_in_github_actions(monkeypatch) -> None:
    """13. Verify hostname 'mysql' is accepted in GitHub Actions for shopeasy_test_ci."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    validate_test_mysql_url("mysql+pymysql://root:root@mysql:3306/shopeasy_test_ci")


@pytest.mark.unit
def test_ci_service_hostname_rejected_for_other_db_in_github_actions(monkeypatch) -> None:
    """14. Verify hostname 'mysql' is rejected in GitHub Actions if DB is not shopeasy_test_ci."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for db in ("shopeasy_test_local", "shopeasy_arya", "shopeasy_app", "shopeasy_dev"):
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            validate_test_mysql_url(f"mysql+pymysql://root:root@mysql:3306/{db}")


@pytest.mark.unit
def test_ci_service_hostname_rejected_outside_github_actions(monkeypatch) -> None:
    """15. Verify hostname 'mysql' is strictly rejected when GITHUB_ACTIONS is not true."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        validate_test_mysql_url("mysql+pymysql://root:root@mysql:3306/shopeasy_test_ci")


@pytest.mark.unit
def test_ci_service_guard_blocks_unauthorized_connections(monkeypatch) -> None:
    """16. Verify do_connect guard blocks hostname 'mysql' outside GitHub Actions before connect."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    engine = create_engine("mysql+pymysql://root:root@mysql:3306/shopeasy_test_ci")
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*unauthorized MySQL host"):
        engine.connect()


@pytest.mark.unit
def test_alembic_cart_items_timestamp_migration_linear_and_valid() -> None:
    """17. Verify Alembic migration history is linear and timestamp alignment migration is valid."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.dialects import mysql

    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "4bed57dc0ac3"

    rev = script.get_revision("4bed57dc0ac3")
    assert rev.down_revision == "c895961fa0f1"

    # Verify upgrade and downgrade execute valid DDL for MySQL dialect in dry-run mode
    ctx = MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True})
    with Operations.context(ctx):
        rev.module.upgrade()
        rev.module.downgrade()


@pytest.mark.unit
def test_alembic_mysql_impl_compare_server_default_reconciles_timestamps() -> None:
    """18. Verify MySQLImpl.compare_server_default accurately normalizes MySQL timestamps.

    Confirms:
    - Scoped context manager restores the original comparator on exit and exception.
    - Repeated or nested execution does not repeatedly wrap the comparator.
    - DATETIME now() versus CURRENT_TIMESTAMP is treated as equivalent (returns False).
    - TIMESTAMP now() versus CURRENT_TIMESTAMP is treated as equivalent (returns False).
    - Variations in casing and harmless parentheses are correctly handled.
    - An explicit spy test proves the original comparator is called with preserved arguments
      and return values for:
        * Missing inspector column (inspector is None).
        * Missing metadata column (metadata is None).
        * Both columns missing (both are None).
        * Integer defaults (0 vs 1, 100 vs 100).
        * String and Enum defaults ('admin' vs 'customer', 'active' vs 'active').
        * Genuine timestamp differences (fixed timestamp vs now).
        * Mismatched column types (DateTime vs Integer).
        * Defaults with ON UPDATE differences.
    - SQLite and PostgreSQL comparators remain completely untouched.
    - Alembic autogenerate pipeline exercises real column comparison on Computed columns
      (beneficiary_queue.active_flag) without triggering AttributeError.
    """
    import importlib.util
    from pathlib import Path
    from unittest.mock import MagicMock
    from sqlalchemy import Column, Integer, String, DateTime, TIMESTAMP, Enum, Computed, MetaData, Table
    from sqlalchemy.dialects import mysql
    from alembic.ddl.mysql import MySQLImpl
    from alembic.autogenerate.api import AutogenContext
    from alembic.autogenerate.compare import server_defaults as sd
    from alembic.autogenerate.compare.tables import _compare_columns
    from alembic.operations.ops import AlterColumnOp, ModifyTableOps
    from alembic.runtime.migration import MigrationContext
    from alembic.util import PriorityDispatchResult

    backend_dir = Path(__file__).resolve().parent.parent
    env_path = backend_dir / "alembic" / "env.py"
    spec = importlib.util.spec_from_file_location("alembic_env", env_path)
    env_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env_mod)

    # 1. Scoped execution and restoration verification
    unwrapped_fn = getattr(
        MySQLImpl, "_unwrapped_compare_server_default", MySQLImpl.compare_server_default
    )

    # Before scoped execution: ensure class comparator is original unwrapped and no leftover attr
    MySQLImpl.compare_server_default = unwrapped_fn
    if hasattr(MySQLImpl, "_unwrapped_compare_server_default"):
        delattr(MySQLImpl, "_unwrapped_compare_server_default")
    assert MySQLImpl.compare_server_default is unwrapped_fn
    assert not hasattr(MySQLImpl, "_unwrapped_compare_server_default")

    # Inside scoped execution: comparator is wrapped and temporary unwrapped attr is tracked
    with env_mod.scoped_mysql_compare_server_default():
        assert MySQLImpl.compare_server_default is not unwrapped_fn
        assert hasattr(MySQLImpl, "_unwrapped_compare_server_default")
        # Nested scoped execution does not double-wrap
        with env_mod.scoped_mysql_compare_server_default():
            assert MySQLImpl.compare_server_default is not unwrapped_fn
            assert hasattr(MySQLImpl, "_unwrapped_compare_server_default")

    # After scoped execution exits: original comparator is restored and attribute cleaned up
    assert MySQLImpl.compare_server_default is unwrapped_fn
    assert not hasattr(MySQLImpl, "_unwrapped_compare_server_default")

    # Scoped execution restores original comparator and cleans up attribute even if an exception occurs
    try:
        with env_mod.scoped_mysql_compare_server_default():
            assert hasattr(MySQLImpl, "_unwrapped_compare_server_default")
            raise RuntimeError("forced scope error")
    except RuntimeError:
        pass
    assert MySQLImpl.compare_server_default is unwrapped_fn
    assert not hasattr(MySQLImpl, "_unwrapped_compare_server_default")

    # Verify concurrent usage across threads is safely serialized without attribute corruption
    import threading
    concurrency_errors = []

    def worker():
        try:
            for _ in range(10):
                with env_mod.scoped_mysql_compare_server_default():
                    assert MySQLImpl.compare_server_default is not unwrapped_fn
                    assert hasattr(MySQLImpl, "_unwrapped_compare_server_default")
        except Exception as exc:
            concurrency_errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not concurrency_errors
    assert MySQLImpl.compare_server_default is unwrapped_fn
    assert not hasattr(MySQLImpl, "_unwrapped_compare_server_default")

    impl = MySQLImpl(
        dialect=MagicMock(),
        connection=MagicMock(),
        as_sql=False,
        transactional_ddl=False,
        output_buffer=MagicMock(),
        context_opts={},
    )

    col_dt = Column("created_at", DateTime)
    col_ts = Column("created_at", TIMESTAMP)
    col_int = Column("quantity", Integer)
    col_str = Column("full_name", String(50))
    col_enum = Column("role", Enum("customer", "admin"))

    with env_mod.scoped_mysql_compare_server_default():
        # 2. DATETIME now() versus CURRENT_TIMESTAMP treated as equivalent (returns False)
        equiv_pairs = [
            ("now()", "CURRENT_TIMESTAMP"),
            ("CURRENT_TIMESTAMP", "now()"),
            ("now()", "(CURRENT_TIMESTAMP)"),
            ("NOW()", "CURRENT_TIMESTAMP()"),
            ("CURRENT_TIMESTAMP", "(now())"),
            ("((current_timestamp()))", "((NOW()))"),
        ]
        for met, ins in equiv_pairs:
            res = impl.compare_server_default(col_dt, col_dt, met, ins)
            assert res is False, f"MySQL DATETIME failed for ({met}, {ins}): got {res}"

        # 3. TIMESTAMP column equivalents are also treated as equivalent (returns False)
        assert impl.compare_server_default(col_ts, col_ts, "now()", "CURRENT_TIMESTAMP") is False
        assert impl.compare_server_default(col_ts, col_ts, "CURRENT_TIMESTAMP", "now()") is False
        assert impl.compare_server_default(col_dt, col_ts, "now()", "CURRENT_TIMESTAMP") is False

        # 4. Explicit spy verification: prove original MySQL comparator is invoked with exact args
        spy_orig = MagicMock(return_value="sentinel_drift_result")
        MySQLImpl._unwrapped_compare_server_default = spy_orig
        try:
            # A. Missing inspector column (inspector is None)
            res_none_ins = impl.compare_server_default(None, col_dt, "now()", "CURRENT_TIMESTAMP")
            assert res_none_ins == "sentinel_drift_result"
            spy_orig.assert_called_once_with(impl, None, col_dt, "now()", "CURRENT_TIMESTAMP")

            # B. Missing metadata column (metadata is None)
            spy_orig.reset_mock()
            res_none_met = impl.compare_server_default(col_dt, None, "now()", "CURRENT_TIMESTAMP")
            assert res_none_met == "sentinel_drift_result"
            spy_orig.assert_called_once_with(impl, col_dt, None, "now()", "CURRENT_TIMESTAMP")

            # C. Both columns missing (both are None)
            spy_orig.reset_mock()
            res_both_none = impl.compare_server_default(None, None, "now()", "CURRENT_TIMESTAMP")
            assert res_both_none == "sentinel_drift_result"
            spy_orig.assert_called_once_with(impl, None, None, "now()", "CURRENT_TIMESTAMP")

            # D. Integer defaults
            spy_orig.reset_mock()
            spy_orig.return_value = True
            res_int_diff = impl.compare_server_default(col_int, col_int, "1", "0")
            assert res_int_diff is True
            spy_orig.assert_called_once_with(impl, col_int, col_int, "1", "0")

            spy_orig.reset_mock()
            spy_orig.return_value = False
            res_int_same = impl.compare_server_default(col_int, col_int, "100", "100")
            assert res_int_same is False
            spy_orig.assert_called_once_with(impl, col_int, col_int, "100", "100")

            # E. String and Enum defaults
            spy_orig.reset_mock()
            spy_orig.return_value = True
            res_str_diff = impl.compare_server_default(col_str, col_str, "'admin'", "'customer'")
            assert res_str_diff is True
            spy_orig.assert_called_once_with(impl, col_str, col_str, "'admin'", "'customer'")

            spy_orig.reset_mock()
            res_enum_diff = impl.compare_server_default(col_enum, col_enum, "'admin'", "'customer'")
            assert res_enum_diff is True
            spy_orig.assert_called_once_with(impl, col_enum, col_enum, "'admin'", "'customer'")

            # F. Genuine timestamp differences
            spy_orig.reset_mock()
            res_dt_diff = impl.compare_server_default(col_dt, col_dt, "'2026-01-01 00:00:00'", "CURRENT_TIMESTAMP")
            assert res_dt_diff is True
            spy_orig.assert_called_once_with(impl, col_dt, col_dt, "'2026-01-01 00:00:00'", "CURRENT_TIMESTAMP")

            # G. Mismatched column types
            spy_orig.reset_mock()
            res_mismatch = impl.compare_server_default(col_dt, col_int, "now()", "CURRENT_TIMESTAMP")
            assert res_mismatch is True
            spy_orig.assert_called_once_with(impl, col_dt, col_int, "now()", "CURRENT_TIMESTAMP")

            # H. Defaults with ON UPDATE differences
            spy_orig.reset_mock()
            res_onupdate = impl.compare_server_default(
                col_dt, col_dt, "now()", "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
            )
            assert res_onupdate is True
            spy_orig.assert_called_once_with(impl, col_dt, col_dt, "now()", "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")

            # I. Reconciled timestamp synonyms must NOT call the original comparator
            spy_orig.reset_mock()
            res_reconciled = impl.compare_server_default(col_dt, col_dt, "now()", "CURRENT_TIMESTAMP")
            assert res_reconciled is False
            spy_orig.assert_not_called()

        finally:
            MySQLImpl._unwrapped_compare_server_default = unwrapped_fn

    assert MySQLImpl.compare_server_default is unwrapped_fn
    assert not hasattr(MySQLImpl, "_unwrapped_compare_server_default")

    # 5. Dialect isolation: verify SQLite and PostgreSQL comparators remain unchanged
    from alembic.ddl.impl import DefaultImpl
    from alembic.ddl.sqlite import SQLiteImpl
    from alembic.ddl.postgresql import PostgresqlImpl

    assert getattr(DefaultImpl, "compare_server_default", None) is not MySQLImpl.compare_server_default
    assert getattr(SQLiteImpl, "compare_server_default", None) is not MySQLImpl.compare_server_default
    assert getattr(PostgresqlImpl, "compare_server_default", None) is not MySQLImpl.compare_server_default

    # 6. Unit check: comparator-level handling of Computed column active_flag
    col_comp = Column(
        "active_flag",
        Integer,
        Computed("CASE WHEN status = 'active' THEN 1 ELSE NULL END", persisted=True),
    )
    op = AlterColumnOp("beneficiary_queue", "active_flag")
    ctx_mock = MagicMock()
    ctx_mock.migration_context._user_compare_server_default = None

    # Verify _user_compare_server_default safely returns CONTINUE without accessing .arg.text
    res_user = sd._user_compare_server_default(
        ctx_mock, op, None, "beneficiary_queue", "active_flag", col_comp, col_comp
    )
    assert res_user == PriorityDispatchResult.CONTINUE

    # Verify _compare_computed_default handles the Computed column and stops
    ctx_mock.dialect.name = "mysql"
    res_comp = sd._compare_computed_default(
        ctx_mock, op, None, "beneficiary_queue", "active_flag", col_comp, col_comp
    )
    assert res_comp == PriorityDispatchResult.STOP

    # 7. Real autogenerate pipeline integration test with Computed column
    # Exercises Alembic's actual _compare_columns generator on a simulated schema
    expr = "CASE WHEN status = 1 THEN 1 ELSE NULL END"
    md_meta = MetaData()
    t_meta = Table(
        "beneficiary_queue",
        md_meta,
        Column("id", Integer, primary_key=True),
        Column("active_flag", Integer, Computed(expr, persisted=True)),
    )
    md_conn = MetaData()
    t_conn = Table(
        "beneficiary_queue",
        md_conn,
        Column("id", Integer, primary_key=True),
        Column("active_flag", Integer, Computed(expr, persisted=True)),
    )

    mig_ctx = MigrationContext(mysql.dialect(), None, {"autogenerate": True})
    autogen_ctx = AutogenContext(mig_ctx, md_meta)
    modify_ops = ModifyTableOps("beneficiary_queue", [])
    mock_inspector = MagicMock()

    # Must complete without raising AttributeError: 'Computed' object has no attribute 'arg'
    with _compare_columns(None, "beneficiary_queue", t_conn, t_meta, modify_ops, autogen_ctx, mock_inspector):
        pass

    assert len(modify_ops.ops) == 0, f"Expected 0 diff ops for identical computed columns, got {modify_ops.ops}"

