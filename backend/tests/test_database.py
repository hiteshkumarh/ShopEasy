import os
from pathlib import Path
import sys
import tempfile
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.core.database as db_module
from app.core.config import settings
from app.core.database import (
    Base,
    SessionLocal,
    create_database_engine,
    get_alembic_database_url,
    get_database_url,
    get_db,
    get_engine,
    get_session_factory,
    get_ssl_connect_args,
    reset_database_engine,
    validate_alembic_database_url,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_env_and_engine():
    """Preserve and restore environment and database engine state around each test."""
    original_env = dict(os.environ)
    original_ssl_ca = settings.DB_SSL_CA
    original_env_val = settings.ENVIRONMENT
    try:
        yield
    finally:
        for key in list(os.environ.keys()):
            if key not in original_env and not key.startswith("PYTEST_"):
                os.environ.pop(key, None)
        for key, val in original_env.items():
            os.environ[key] = val
        settings.DB_SSL_CA = original_ssl_ca
        settings.ENVIRONMENT = original_env_val
        reset_database_engine(None)


def test_sqlite_returns_empty_ssl_args():
    """Verify SQLite database URLs always return empty SSL arguments."""
    settings.DB_SSL_CA = ""
    args = get_ssl_connect_args("sqlite:///:memory:")
    assert args == {}

    # Even if DB_SSL_CA was set, SQLite must never require or receive SSL args
    settings.DB_SSL_CA = "/dummy/ca.pem"
    args = get_ssl_connect_args("sqlite:///:memory:")
    assert args == {}


def test_dev_mysql_without_ssl_ca_returns_empty_dict():
    """Verify non-production MySQL connections without DB_SSL_CA return empty connect args."""
    settings.ENVIRONMENT = "development"
    settings.DB_SSL_CA = ""
    args = get_ssl_connect_args("mysql+pymysql://user:pass@localhost:3306/db")
    assert args == {}


def test_dev_mysql_with_nonexistent_ca_raises_filenotfound():
    """Verify non-production MySQL raises FileNotFoundError if DB_SSL_CA is configured but missing."""
    settings.ENVIRONMENT = "development"
    settings.DB_SSL_CA = "/path/to/definitely/missing/ca.pem"
    with pytest.raises(FileNotFoundError, match="DB_SSL_CA certificate file does not exist"):
        get_ssl_connect_args("mysql+pymysql://user:pass@localhost:3306/db")


def test_dev_mysql_with_valid_ca_returns_verified_args():
    """Verify MySQL with a valid CA file returns strict TLS verification options."""
    settings.ENVIRONMENT = "development"
    with tempfile.NamedTemporaryFile(suffix=".pem") as f:
        settings.DB_SSL_CA = f.name
        args = get_ssl_connect_args("mysql+pymysql://user:pass@localhost:3306/db")
        assert args["ssl_ca"] == str(Path(f.name).resolve())
        assert args["ssl_verify_cert"] is True
        assert args["ssl_verify_identity"] is True


def test_production_mysql_without_ca_raises_valueerror():
    """Verify production MySQL connections strictly require DB_SSL_CA."""
    settings.ENVIRONMENT = "production"
    settings.DB_SSL_CA = ""
    with pytest.raises(ValueError, match="DB_SSL_CA must be configured for production MySQL/TiDB connections"):
        get_ssl_connect_args("mysql+pymysql://user:pass@localhost:3306/db")


def test_production_mysql_with_nonexistent_ca_raises_filenotfound():
    """Verify production MySQL fails with FileNotFoundError if CA certificate file does not exist."""
    settings.ENVIRONMENT = "production"
    settings.DB_SSL_CA = "/path/to/missing/prod-ca.pem"
    with pytest.raises(FileNotFoundError, match="DB_SSL_CA certificate file does not exist"):
        get_ssl_connect_args("mysql+pymysql://user:pass@localhost:3306/db")


def test_production_mysql_with_valid_ca_returns_verified_tls():
    """Verify production MySQL returns verified TLS options when CA file exists."""
    settings.ENVIRONMENT = "production"
    with tempfile.NamedTemporaryFile(suffix=".pem") as f:
        settings.DB_SSL_CA = f.name
        args = get_ssl_connect_args("mysql+pymysql://user:pass@localhost:3306/db")
        assert args["ssl_ca"] == str(Path(f.name).resolve())
        assert args["ssl_verify_cert"] is True
        assert args["ssl_verify_identity"] is True


def test_create_database_engine_sqlite():
    """Verify create_database_engine safely initializes a SQLite engine."""
    eng = create_database_engine("sqlite:///:memory:")
    assert str(eng.url).startswith("sqlite://")
    with eng.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_session_local_and_get_db_lifecycle():
    """Verify SessionLocal proxy and get_db dependency function properly."""
    sqlite_engine = create_database_engine("sqlite:///:memory:")
    reset_database_engine(sqlite_engine)

    # Test SessionLocal() creates an active Session bound to the current engine
    session = SessionLocal()
    try:
        assert isinstance(session, Session)
        result = session.execute(text("SELECT 42")).scalar()
        assert result == 42
    finally:
        session.close()

    # Test get_db() dependency yields and closes cleanly
    db_gen = get_db()
    db_session = next(db_gen)
    assert isinstance(db_session, Session)
    res = db_session.execute(text("SELECT 100")).scalar()
    assert res == 100
    with pytest.raises(StopIteration):
        next(db_gen)


def test_lazy_engine_module_attribute():
    """Verify db_module.engine resolves lazily and invalid attributes raise AttributeError."""
    # Reset engine to ensure fresh evaluation
    reset_database_engine(create_database_engine("sqlite:///:memory:"))

    eng = db_module.engine
    assert eng is not None
    assert str(eng.url).startswith("sqlite://")

    with pytest.raises(AttributeError, match="has no attribute 'nonexistent_attribute'"):
        _ = db_module.nonexistent_attribute


def test_alembic_guard_allows_isolated_mysql_ci_database(monkeypatch):
    """1. Verify Alembic safety guard allows isolated MySQL CI database URLs."""
    ci_url = "mysql+pymysql://root:root@127.0.0.1:3306/shopeasy_test_ci"
    validated = validate_alembic_database_url(ci_url)
    assert validated == ci_url

    # In GitHub Actions environment, the designated service host 'mysql' is also allowed for shopeasy_test_ci
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    ci_service_url = "mysql+pymysql://root:root@mysql:3306/shopeasy_test_ci"
    assert validate_alembic_database_url(ci_service_url) == ci_service_url


def test_alembic_guard_allows_approved_isolated_local_test_database(tmp_path: Path):
    """2. Verify Alembic safety guard allows approved local test databases (loopback and approved SQLite)."""
    local_mysql_url = "mysql+pymysql://user:pass@localhost:3306/shopeasy_test_local"
    assert validate_alembic_database_url(local_mysql_url) == local_mysql_url

    local_ip_url = "mysql+pymysql://user:pass@127.0.0.1:3306/shopeasy_test_2"
    assert validate_alembic_database_url(local_ip_url) == local_ip_url

    # In-memory SQLite permitted
    assert validate_alembic_database_url("sqlite:///:memory:") == "sqlite:///:memory:"

    # Approved isolated SQLite file in temp directory permitted
    approved_file = tmp_path / "test_isolated.db"
    approved_url = "sqlite:///" + str(approved_file).replace("\\", "/")
    assert validate_alembic_database_url(approved_url) == approved_url


def test_alembic_guard_sqlite_in_memory_allowed():
    """Verify SQLite in-memory URLs are allowed."""
    assert validate_alembic_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
    assert validate_alembic_database_url("sqlite://") == "sqlite://"


def test_alembic_guard_sqlite_approved_isolated_file_allowed(tmp_path: Path):
    """Verify explicitly approved isolated test SQLite files are allowed."""
    # File in pytest tmp_path with test_ prefix
    f1 = tmp_path / "test_migrations.db"
    url1 = "sqlite:///" + str(f1).replace("\\", "/")
    assert validate_alembic_database_url(url1) == url1

    # File in pytest tmp_path with shopeasy_test_ prefix
    f2 = tmp_path / "shopeasy_test_isolated.sqlite"
    url2 = "sqlite:///" + str(f2).replace("\\", "/")
    assert validate_alembic_database_url(url2) == url2

    # File in backend/tests directory with test_ prefix
    backend_tests_dir = Path(__file__).resolve().parent
    f3 = backend_tests_dir / "test_dummy.db"
    url3 = "sqlite:///" + str(f3).replace("\\", "/")
    assert validate_alembic_database_url(url3) == url3


def test_alembic_guard_sqlite_arbitrary_relative_file_rejected():
    """Verify arbitrary relative SQLite file paths outside approved policy are rejected."""
    arbitrary_relative = [
        "sqlite:///arbitrary.db",
        "sqlite:///test.db",
        "sqlite:///some/relative/test_db.db",
        "sqlite:///test_relative.db",  # in project root, outside approved test directory
    ]
    for url in arbitrary_relative:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            validate_alembic_database_url(url)


def test_alembic_guard_sqlite_arbitrary_absolute_file_rejected():
    """Verify arbitrary absolute SQLite file paths outside approved policy are rejected."""
    arbitrary_absolute = [
        "sqlite:////var/data/test_migrations.db",
        "sqlite:///C:/arbitrary_nonexistent_dir/test_isolated.db",
        "sqlite:////etc/shopeasy_test.db",
    ]
    for url in arbitrary_absolute:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            validate_alembic_database_url(url)


def test_alembic_guard_sqlite_application_database_file_rejected(tmp_path: Path):
    """Verify application/production SQLite database filenames are rejected even in temp dir."""
    app_urls = [
        "sqlite:///shopeasy_app.db",
        "sqlite:///shopeasy_prod.sqlite",
        "sqlite:///shopeasy_arya.db",
        "sqlite:///shopeasy_dev.db",
        "sqlite:///app.db",
        "sqlite:///production.db",
        # Even when placed inside tmp_path:
        "sqlite:///" + str(tmp_path / "shopeasy_app.db").replace("\\", "/"),
        "sqlite:///" + str(tmp_path / "production.db").replace("\\", "/"),
    ]
    for url in app_urls:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            validate_alembic_database_url(url)


def test_alembic_guard_sqlite_malformed_urls_rejected():
    """Verify malformed SQLite URLs are rejected."""
    malformed_urls = [
        "sqlite:invalid.db",
        "sqlite:///",
        "sqlite:///?foo=1",
        "sqlite:///:invalid:",
        "sqlite:///:unknown:",
    ]
    for url in malformed_urls:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            validate_alembic_database_url(url)


def test_alembic_guard_blocks_remote_and_tidb_even_with_allow_remote_migration_env(monkeypatch):
    """Verify ALLOW_REMOTE_MIGRATION environment variable cannot override safety blocks."""
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")

    # Remote production host blocked
    with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to remote host"):
        validate_alembic_database_url("mysql+pymysql://user:pass@production-host.internal:3306/shopeasy_test_ci")

    # TiDB Cloud host blocked
    with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to TiDB Cloud"):
        validate_alembic_database_url(
            "mysql+pymysql://user:pass@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/shopeasy_test_db"
        )

    # Even with ALLOW_REMOTE_MIGRATION=1
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "1")
    with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to TiDB Cloud"):
        validate_alembic_database_url(
            "mysql+pymysql://user:pass@cluster.tidbcloud.com:4000/shopeasy_test_ci"
        )


def test_alembic_guard_blocks_tidb_cloud_hostname():
    """3. Verify Alembic safety guard strictly blocks TiDB Cloud hostnames."""
    tidb_urls = [
        "mysql+pymysql://user:pass@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/shopeasy_arya",
        "mysql+pymysql://user:pass@tidbcloud.com:4000/shopeasy_test_db",
        "mysql+pymysql://user:pass@cluster.tidbcloud.com:4000/shopeasy_test_ci",
    ]
    for url in tidb_urls:
        with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to TiDB Cloud"):
            validate_alembic_database_url(url)


def test_alembic_guard_blocks_production_database_hostname(monkeypatch):
    """4. Verify Alembic safety guard strictly blocks remote and production databases."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    # Remote non-local hosts rejected
    with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to remote host"):
        validate_alembic_database_url("mysql+pymysql://user:pass@production-host.internal:3306/shopeasy_test_ci")

    with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to remote host"):
        validate_alembic_database_url("mysql+pymysql://user:pass@192.168.1.100:3306/shopeasy_test_ci")

    # Local host with production or non-test database name rejected
    with pytest.raises(RuntimeError, match="Alembic database name must begin with 'shopeasy_test_'"):
        validate_alembic_database_url("mysql+pymysql://root:pass@localhost:3306/shopeasy_app")

    with pytest.raises(RuntimeError, match="Alembic database name must begin with 'shopeasy_test_'"):
        validate_alembic_database_url("mysql+pymysql://root:pass@127.0.0.1:3306/shopeasy_arya")


def test_alembic_guard_blocks_missing_explicit_url_and_prevents_silent_env_fallback(monkeypatch):
    """5. Verify Alembic fails closed when no explicit URL is provided, preventing silent fallback to backend/.env."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)

    # Calling get_alembic_database_url without an explicit environment variable or config option
    # must strictly raise RuntimeError rather than reading from backend/.env
    with pytest.raises(RuntimeError, match="No explicit DATABASE_URL environment variable provided for Alembic"):
        get_alembic_database_url()

    # Empty string or whitespace also strictly rejected
    with pytest.raises(RuntimeError, match="Explicit database URL is required for Alembic migrations"):
        validate_alembic_database_url("")

    with pytest.raises(RuntimeError, match="Explicit database URL is required for Alembic migrations"):
        validate_alembic_database_url("   ")

