import os
from pathlib import Path
import tempfile
from typing import Any, List, Optional
import urllib.parse

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.config import settings

def get_database_url() -> str:
    """Resolve database URL from DATABASE_URL env or discrete connection parameters."""
    raw_url = settings.DATABASE_URL
    if raw_url and raw_url.strip():
        url = raw_url.strip()
        # SQLAlchemy requires mysql+pymysql:// dialect driver for PyMySQL
        if url.startswith("mysql://"):
            url = "mysql+pymysql://" + url[len("mysql://") :]
        return url

    # Safely URL-encode user and password to handle special characters (@, #, :, /, etc.)
    encoded_user = urllib.parse.quote_plus(settings.DB_USER)
    encoded_password = urllib.parse.quote_plus(settings.DB_PASSWORD)

    # Construct MySQL connection URL with pymysql driver and utf8mb4 encoding
    return (
        f"mysql+pymysql://{encoded_user}:{encoded_password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset=utf8mb4"
    )


DATABASE_URL = get_database_url()


def _get_approved_sqlite_test_dirs() -> List[Path]:
    """Return approved directories for isolated SQLite test databases."""
    dirs: List[Path] = [Path(tempfile.gettempdir()).resolve()]
    backend_dir = Path(__file__).resolve().parent.parent.parent
    tests_dir = (backend_dir / "tests").resolve()
    if tests_dir.is_dir():
        dirs.append(tests_dir)
    repo_tests = (backend_dir.parent / "tests").resolve()
    if repo_tests.is_dir():
        dirs.append(repo_tests)
    test_tmp = (backend_dir / ".test_tmp").resolve()
    dirs.append(test_tmp)
    return dirs


def _validate_sqlite_url(clean_url: str) -> str:
    """Validate SQLite URL against strict isolation and test naming policies."""
    if not clean_url.startswith("sqlite://"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Malformed SQLite database URL: '{clean_url}'. "
            "SQLite URLs must begin with 'sqlite://' or 'sqlite:///'."
        )

    # In-memory database allowed
    if clean_url in ("sqlite:///:memory:", "sqlite://"):
        return clean_url

    if not clean_url.startswith("sqlite:///"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Malformed SQLite file URL: '{clean_url}'. "
            "File-based SQLite URLs must begin with 'sqlite:///'."
        )

    try:
        url_obj = make_url(clean_url)
    except Exception as exc:
        raise RuntimeError(f"SAFETY VIOLATION: Malformed SQLite database URL: {exc}") from exc

    db_path_str = url_obj.database
    if not db_path_str or not db_path_str.strip():
        raise RuntimeError(
            "SAFETY VIOLATION: SQLite database URL must specify a non-empty file path or ':memory:'."
        )

    clean_path_str = db_path_str.strip()
    if clean_path_str == ":memory:":
        return clean_url

    if clean_path_str.startswith(":"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Unknown SQLite target: '{clean_path_str}'."
        )

    target_path = Path(clean_path_str)
    filename = target_path.name.lower()

    # Rule 1: Reject application and production database files
    prohibited_names = (
        "shopeasy_app",
        "shopeasy_prod",
        "shopeasy_arya",
        "shopeasy_dev",
        "production",
        "prod",
        "app.db",
        "app.sqlite",
        "main.db",
    )
    for prohibited in prohibited_names:
        if prohibited in filename:
            raise RuntimeError(
                f"SAFETY VIOLATION: Application/production SQLite database target '{clean_path_str}' "
                "is strictly prohibited for Alembic migrations."
            )

    # Rule 2: Filename convention - must strictly begin with an approved test prefix
    # and end with an approved extension
    valid_prefixes = ("shopeasy_test_", "test_")
    valid_extensions = (".db", ".sqlite", ".sqlite3")

    if not any(filename.startswith(p) for p in valid_prefixes) or not any(
        filename.endswith(e) for e in valid_extensions
    ):
        raise RuntimeError(
            f"SAFETY VIOLATION: SQLite test file '{clean_path_str}' does not match the approved test filename "
            f"convention (must start with {valid_prefixes} and end with {valid_extensions})."
        )

    # Rule 3: Directory isolation - must resolve strictly within an approved test directory
    resolved_path = target_path.resolve()
    approved_dirs = _get_approved_sqlite_test_dirs()
    if not any(resolved_path.is_relative_to(ad) for ad in approved_dirs):
        raise RuntimeError(
            f"SAFETY VIOLATION: SQLite test database path '{clean_path_str}' resolves outside approved isolated test directories. "
            "Alembic SQLite migrations must target an approved test directory (system temp directory or backend/tests)."
        )

    return clean_url


def validate_alembic_database_url(url: Optional[str]) -> str:
    """Validate that an Alembic database URL strictly targets an approved isolated test database.

    Fail-closed security rules:
      1. Empty, missing, or whitespace-only URL is strictly rejected (no silent fallback).
      2. Dialects permitted: 'sqlite' or 'mysql'/'mysql+pymysql'.
      3. SQLite URLs are strictly restricted to ':memory:' or approved isolated test files
         matching test naming conventions within designated test directories. Arbitrary paths
         and application database files are strictly rejected.
      4. All remote database hosts, cloud IPs, and TiDB Cloud hostnames (*.tidbcloud.com)
         are strictly prohibited with zero override mechanisms.
      5. MySQL targets must be strictly local loopback ('localhost', '127.0.0.1', '::1')
         OR the designated GitHub Actions CI service container ('mysql') when
         GITHUB_ACTIONS is 'true' and database is 'shopeasy_test_ci'.
      6. For MySQL, database name must strictly begin with 'shopeasy_test_'.
         Production and development databases ('shopeasy_app', 'shopeasy_arya', 'shopeasy_dev', etc.)
         are strictly blocked.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise RuntimeError(
            "SAFETY VIOLATION: Explicit database URL is required for Alembic migrations. "
            "Silent fallback to backend/.env is strictly prohibited."
        )

    clean_url = url.strip()
    if clean_url.startswith("sqlite:") or clean_url.startswith("sqlite://"):
        return _validate_sqlite_url(clean_url)

    try:
        parsed = urllib.parse.urlsplit(clean_url)
    except Exception as exc:
        raise RuntimeError(f"SAFETY VIOLATION: Malformed Alembic database URL: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("mysql", "mysql+pymysql"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Alembic database URL dialect must be 'sqlite', 'mysql', or 'mysql+pymysql'. "
            f"Unsupported dialect: {scheme!r}."
        )

    host = (parsed.hostname or "").lower()
    db_path = parsed.path.lstrip("/").split("?")[0].strip()
    db_name = db_path.lower()

    # Fail closed: Remote database connections and TiDB Cloud are strictly blocked with zero overrides.
    netloc = (parsed.netloc or "").lower()
    if "tidbcloud" in host or "tidbcloud" in netloc:
        raise RuntimeError(
            f"SAFETY VIOLATION: Alembic safety guard blocked connection to TiDB Cloud host '{host}'. "
            f"Migrations against remote TiDB Cloud are strictly prohibited."
        )

    # Host must be strictly local loopback or designated CI service
    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    is_local_host = host in ("localhost", "127.0.0.1", "::1")
    is_ci_service_host = is_ci and host == "mysql" and db_name == "shopeasy_test_ci"

    if not host or (not is_local_host and not is_ci_service_host):
        raise RuntimeError(
            f"SAFETY VIOLATION: Alembic safety guard blocked connection to remote host '{host}'. "
            f"Alembic migrations must target local loopback (localhost, 127.0.0.1, ::1) "
            f"or the CI test container ('mysql')."
        )

    # Database name must follow test convention
    if not db_name.startswith("shopeasy_test_"):
        raise RuntimeError(
            f"SAFETY VIOLATION: Alembic database name must begin with 'shopeasy_test_'. "
            f"Target database '{db_name}' is strictly prohibited."
        )

    return clean_url


def get_alembic_database_url(config: Optional[Any] = None) -> str:
    """Resolve and validate the target database URL for Alembic migrations.

    Precedence:
      1. Explicit environment variable: ALEMBIC_DATABASE_URL or DATABASE_URL in os.environ.
      2. Explicit Alembic config main option 'sqlalchemy.url' (if programmatically configured by test fixtures).
      3. If neither is explicitly provided, strictly raises RuntimeError to prevent silent fallback to backend/.env.
    """
    raw_env = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if raw_env and raw_env.strip():
        url = raw_env.strip()
        if url.startswith("mysql://"):
            url = "mysql+pymysql://" + url[len("mysql://") :]
        return validate_alembic_database_url(url)

    # Check if alembic Config had sqlalchemy.url set programmatically (e.g. in test fixtures)
    if config is not None:
        cfg_url = config.get_main_option("sqlalchemy.url")
        if cfg_url and cfg_url.strip() and not cfg_url.startswith("%"):
            # Unescape double percents if present
            clean_cfg = cfg_url.replace("%%", "%").strip()
            return validate_alembic_database_url(clean_cfg)

    # Fail closed: reject silent fallback to backend/.env or settings.DATABASE_URL
    raise RuntimeError(
        "SAFETY VIOLATION: No explicit DATABASE_URL environment variable provided for Alembic. "
        "Silent fallback to backend/.env is strictly prohibited to protect remote databases."
    )


def get_ssl_connect_args(database_url: Optional[str] = None) -> dict:
    """Build verified PyMySQL TLS arguments and validate the CA file path.

    Rules:
      - SQLite connections never require TLS and return an empty dictionary.
      - In production (settings.is_production is True), MySQL/TiDB connections
        strictly require DB_SSL_CA with verified certificate and hostname checking.
        Missing CA or non-existent certificate file raises ValueError or FileNotFoundError.
      - In non-production (development / testing):
        - If DB_SSL_CA is configured and non-empty, the certificate file must exist,
          and verified TLS is enabled.
        - If DB_SSL_CA is unset or empty, returns an empty dictionary to support
          local unencrypted MySQL instances (e.g. Docker Compose mysql:3306).
    """
    url = database_url or get_database_url()
    if url.startswith("sqlite"):
        return {}

    ssl_ca = settings.DB_SSL_CA
    if not ssl_ca or not ssl_ca.strip():
        if settings.is_production:
            raise ValueError(
                "DB_SSL_CA must be configured for production MySQL/TiDB connections. "
                "TLS verification cannot be disabled in production."
            )
        return {}

    ca_path = Path(ssl_ca.strip()).expanduser()
    if not ca_path.is_file():
        raise FileNotFoundError(f"DB_SSL_CA certificate file does not exist: {ca_path}")

    return {
        # PyMySQL native TLS options: both certificate and hostname verification enabled
        "ssl_ca": str(ca_path),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }


def create_database_engine(database_url: Optional[str] = None) -> Engine:
    """Create a configured SQLAlchemy Engine instance with safe defaults."""
    url = database_url or get_database_url()

    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        return create_engine(
            url,
            connect_args=connect_args,
            echo=settings.DEBUG,
        )

    # MySQL / TiDB connection setup
    ssl_args = get_ssl_connect_args(url)
    connect_args = ssl_args if ssl_args else {}
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,   # Test connections for liveness before using
        pool_recycle=300,     # Recycle connections every 5 minutes for cloud DBs
        echo=settings.DEBUG,  # Log SQL queries only when DEBUG is enabled
    )


_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def get_engine(database_url: Optional[str] = None) -> Engine:
    """Get or create the global SQLAlchemy Engine singleton.

    If database_url is provided, creates and returns a new Engine for that URL.
    Otherwise, returns the cached singleton engine for the configured DATABASE_URL.
    """
    global _engine
    if database_url is not None:
        return create_database_engine(database_url)
    if _engine is None:
        _engine = create_database_engine()
    return _engine


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker:
    """Get or create the sessionmaker factory bound to the active engine."""
    global _session_factory
    if engine is not None:
        return sessionmaker(autocommit=False, autoflush=False, bind=engine)
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _session_factory


class _SessionLocalProxy:
    """Proxy that lazily binds to the database session factory on first use."""

    def __call__(self, *args, **kwargs) -> Session:
        return get_session_factory()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(get_session_factory(), name)

    def configure(self, **kwargs) -> None:
        get_session_factory().configure(**kwargs)


SessionLocal = _SessionLocalProxy()


def reset_database_engine(new_engine: Optional[Engine] = None) -> None:
    """Reset the cached engine and session factory (useful for isolated tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = new_engine
    if new_engine is not None:
        _session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=new_engine
        )
    else:
        _session_factory = None


class Base(DeclarativeBase):
    """Declarative Base class for future SQLAlchemy ORM models."""
    pass


def get_db():
    """FastAPI dependency that provides a transactional database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def __getattr__(name: str) -> Any:
    """Support lazy module-level access for 'engine'."""
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "Base",
    "DATABASE_URL",
    "SessionLocal",
    "create_database_engine",
    "get_alembic_database_url",
    "get_database_url",
    "get_db",
    "get_engine",
    "get_session_factory",
    "get_ssl_connect_args",
    "reset_database_engine",
    "validate_alembic_database_url",
]
