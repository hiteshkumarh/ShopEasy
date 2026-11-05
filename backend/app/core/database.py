from pathlib import Path
import urllib.parse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
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


def get_ssl_connect_args() -> dict:
    """Build verified PyMySQL TLS arguments and validate the CA file path."""
    if not settings.DB_SSL_CA or not settings.DB_SSL_CA.strip():
        raise ValueError("DB_SSL_CA must be configured for the TiDB Cloud connection.")

    ca_path = Path(settings.DB_SSL_CA).expanduser()
    if not ca_path.is_file():
        raise FileNotFoundError(f"DB_SSL_CA certificate file does not exist: {ca_path}")

    return {
        # These are PyMySQL's native TLS options. Both certificate and
        # hostname verification are enabled for TiDB Cloud.
        "ssl_ca": str(ca_path),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
    }

# Create SQLAlchemy engine with robust connection pooling
engine = create_engine(
    DATABASE_URL,
    connect_args=get_ssl_connect_args(),
    pool_pre_ping=True,  # Test connections for liveness before using
    pool_recycle=300,    # Recycle connections every 5 minutes for cloud DBs
    echo=settings.DEBUG,  # Log SQL queries when DEBUG is enabled
)

# Session factory for database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


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
