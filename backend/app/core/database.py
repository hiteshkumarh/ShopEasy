from pathlib import Path
from typing import Any, Optional
import urllib.parse

from sqlalchemy import Engine, create_engine
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
    "get_database_url",
    "get_db",
    "get_engine",
    "get_session_factory",
    "get_ssl_connect_args",
    "reset_database_engine",
]
