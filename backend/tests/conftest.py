import os
from pathlib import Path
import sys
from typing import Generator, Optional
import urllib.parse
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
# Strict MySQL Target Validator
# ---------------------------------------------------------------------------
def validate_test_mysql_url(url: Optional[str]) -> None:
    """Validate that a test MySQL URL targets only an approved local test database.

    Permits ONLY:
      - Dialect: mysql or mysql+pymysql
      - Host: strictly local ('localhost', '127.0.0.1', '::1')
      - Database name: begins with 'shopeasy_test_'

    Rejects everything else before any connection or socket is opened.
    Raises RuntimeError without printing sensitive credentials or full URLs.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise RuntimeError("SAFETY VIOLATION: Empty or invalid TEST_MYSQL_URL provided.")

    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception:
        raise RuntimeError("SAFETY VIOLATION: Malformed TEST_MYSQL_URL provided.")

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("mysql", "mysql+pymysql"):
        raise RuntimeError(
            "SAFETY VIOLATION: TEST_MYSQL_URL dialect must be 'mysql' or 'mysql+pymysql'. "
            "Unsupported dialect rejected."
        )

    host = (parsed.hostname or "").lower()
    db_path = parsed.path.lstrip("/").split("?")[0].strip()
    db_name = db_path.lower()

    # Determine permitted hosts:
    # 1. Local loopback hosts (localhost, 127.0.0.1, ::1) are always permitted.
    # 2. In GitHub Actions (GITHUB_ACTIONS == 'true'), service hostname 'mysql' is
    #    permitted ONLY when the target database is strictly 'shopeasy_test_ci'.
    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    is_local_host = host in ("localhost", "127.0.0.1", "::1")
    is_ci_service_host = is_ci and host == "mysql" and db_name == "shopeasy_test_ci"

    if not host or (not is_local_host and not is_ci_service_host):
        raise RuntimeError(
            "SAFETY VIOLATION: TEST_MYSQL_URL host must be strictly local (localhost, 127.0.0.1, or ::1), "
            "or the designated CI service container ('mysql') in GitHub Actions with database 'shopeasy_test_ci'. "
            "Remote hosts and TiDB Cloud clusters are strictly prohibited."
        )

    if "tidbcloud" in host or "tidbcloud" in (parsed.netloc or "").lower():
        raise RuntimeError(
            "SAFETY VIOLATION: TEST_MYSQL_URL cannot target a TiDB Cloud host."
        )

    if not db_name.startswith("shopeasy_test_"):
        raise RuntimeError(
            "SAFETY VIOLATION: TEST_MYSQL_URL database name must begin with 'shopeasy_test_'. "
            "All other database names (including production, dev, and system databases) are strictly prohibited."
        )

    disallowed_exact = (
        "shopeasy_arya",
        "shopeasy_app",
        "shopeasy_dev",
        "sys",
        "test",
        "mysql",
        "information_schema",
        "performance_schema",
    )
    if db_name in disallowed_exact:
        raise RuntimeError(
            "SAFETY VIOLATION: Database name is on the strictly prohibited database list."
        )


# ---------------------------------------------------------------------------
# Live Database Protection Guard (Prevents network connections to TiDB Cloud)
# ---------------------------------------------------------------------------
@event.listens_for(Engine, "do_connect")
def block_live_database_connections(dialect, conn_rec, cargs, cparams) -> None:
    """Safety guard: intercept any DBAPI connection attempt before sockets open.

    Raises RuntimeError immediately if a connection target resolves to TiDB Cloud,
    production/staging database names, or an unapproved remote MySQL database.
    """
    host = str(cparams.get("host", "")).lower()
    database = str(cparams.get("database", "")).lower()

    if "tidbcloud" in host:
        raise RuntimeError(
            "SAFETY VIOLATION: Automated test attempted to connect to live TiDB Cloud host! "
            "Tests must run against isolated local test databases."
        )

    prohibited_dbs = ("shopeasy_arya", "shopeasy_app", "shopeasy_dev", "sys", "test", "mysql")
    if database in prohibited_dbs:
        raise RuntimeError(
            f"SAFETY VIOLATION: Automated test attempted to connect to prohibited database '{database}'! "
            "Tests must run against the isolated in-memory test database or an approved shopeasy_test_* database."
        )

    if dialect.name == "mysql":
        if not database.startswith("shopeasy_test_"):
            raise RuntimeError(
                "SAFETY VIOLATION: Automated test attempted to connect to a non-test MySQL database! "
                "Only databases starting with 'shopeasy_test_' are permitted."
            )
        is_ci = os.getenv("GITHUB_ACTIONS") == "true"
        is_local_host = host in ("localhost", "127.0.0.1", "::1")
        is_ci_service_host = is_ci and host == "mysql" and database == "shopeasy_test_ci"

        if not is_local_host and not is_ci_service_host:
            raise RuntimeError(
                "SAFETY VIOLATION: Automated test attempted to connect to an unauthorized MySQL host! "
                "Only local test hosts (localhost, 127.0.0.1, ::1) or the GitHub Actions CI service ('mysql') are permitted."
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


@pytest.fixture(autouse=True)
def skip_mysql_if_not_configured(request: pytest.FixtureRequest) -> None:
    """Automatically skip tests marked with 'mysql' if TEST_MYSQL_URL is not set."""
    if request.node.get_closest_marker("mysql"):
        test_mysql_url = os.getenv("TEST_MYSQL_URL")
        if not test_mysql_url or not test_mysql_url.strip():
            pytest.skip("Skipping MySQL test: TEST_MYSQL_URL not configured")


# ---------------------------------------------------------------------------
# Isolated SQLite Database Fixtures (Default)
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
# Optional MySQL 8 Database Fixtures (Activated only when TEST_MYSQL_URL is set)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def mysql_engine() -> Generator[Engine, None, None]:
    """Provide a validated MySQL 8 Engine if TEST_MYSQL_URL is configured, else skip."""
    test_mysql_url = os.getenv("TEST_MYSQL_URL")
    if not test_mysql_url or not test_mysql_url.strip():
        pytest.skip("Skipping MySQL test: TEST_MYSQL_URL not configured")

    validate_test_mysql_url(test_mysql_url)

    engine = create_engine(
        test_mysql_url,
        pool_pre_ping=True,
    )
    # Create tables inside the isolated test schema
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def mysql_db_session(mysql_engine: Engine) -> Generator[Session, None, None]:
    """Provide an isolated database session bound to the MySQL test engine."""
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=mysql_engine,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        # Clean table data after each test function in reverse dependency order
        with mysql_engine.begin() as conn:
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
