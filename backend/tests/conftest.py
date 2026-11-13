import os
from pathlib import Path
import sys
from typing import Generator
import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Preserve original environment before setting test environment variables
_ORIGINAL_ENV = dict(os.environ)

# Establish safe, isolated test environment variables before application imports
TEST_ENV_VARS = {
    "ENVIRONMENT": "testing",
    "DEBUG": "False",
    "SECRET_KEY": "test-secret-key-for-automated-testing-minimum-32-chars",
    "OTP_HMAC_SECRET": "test-hmac-secret-for-automated-testing-minimum-32-chars",
    "DATABASE_URL": "sqlite:///:memory:",
    "DB_NAME": "test_shopeasy_sqlite",
    "DB_SSL_CA": "",
    "DEV_OTP_CODE": "123456",
}

for _k, _v in TEST_ENV_VARS.items():
    os.environ[_k] = _v

# Now import application modules
from app.core.config import settings
from app.core.database import Base, get_db
import app.models  # noqa: F401 - ensures all ORM models are registered on Base.metadata
from app.main import app


# ---------------------------------------------------------------------------
# Live Database Protection Guard (Prevents network connections to TiDB Cloud)
# ---------------------------------------------------------------------------
@event.listens_for(Engine, "do_connect")
def block_live_database_connections(dialect, conn_rec, cargs, cparams) -> None:
    """Safety guard: intercept any DBAPI connection attempt before sockets open.

    Raises RuntimeError immediately if a connection target resolves to TiDB Cloud
    or production/staging database names, preventing tests from touching live databases.
    """
    host = str(cparams.get("host", "")).lower()
    database = str(cparams.get("database", "")).lower()

    if "tidbcloud" in host:
        raise RuntimeError(
            "SAFETY VIOLATION: Automated test attempted to connect to live TiDB Cloud host! "
            "Tests must run against the isolated in-memory test database."
        )

    if database in ("shopeasy_arya", "shopeasy_app"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Automated test attempted to connect to live database '{database}'! "
            "Tests must run against the isolated in-memory test database."
        )


@pytest.fixture(scope="session", autouse=True)
def test_session_environment() -> Generator[None, None, None]:
    """Ensure safe test settings for the duration of the pytest session and restore after."""
    try:
        yield
    finally:
        for key in list(os.environ.keys()):
            if key not in _ORIGINAL_ENV and not key.startswith("PYTEST_"):
                os.environ.pop(key, None)
        for key, val in _ORIGINAL_ENV.items():
            os.environ[key] = val


# ---------------------------------------------------------------------------
# Isolated Database Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    """Create a persistent in-memory SQLite engine for the test session using StaticPool."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create all ORM tables once for the test session
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """Provide a clean, isolated database session per test function."""
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        # Clean table data after each test function in reverse dependency order
        with test_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


# ---------------------------------------------------------------------------
# API TestClient Fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    """Provide a FastAPI TestClient with get_db overridden to use the isolated test session."""
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)
