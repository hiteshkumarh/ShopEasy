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
    get_database_url,
    get_db,
    get_engine,
    get_session_factory,
    get_ssl_connect_args,
    reset_database_engine,
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

