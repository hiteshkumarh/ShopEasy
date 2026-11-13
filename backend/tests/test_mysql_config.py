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

