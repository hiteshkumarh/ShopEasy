import urllib.parse
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

# Safely URL-encode user and password to handle special characters (@, #, :, /, etc.)
encoded_user = urllib.parse.quote_plus(settings.DB_USER)
encoded_password = urllib.parse.quote_plus(settings.DB_PASSWORD)

# Construct MySQL connection URL with pymysql driver and utf8mb4 encoding
DATABASE_URL = (
    f"mysql+pymysql://{encoded_user}:{encoded_password}"
    f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset=utf8mb4"
)

# Create SQLAlchemy engine with robust connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Test connections for liveness before using
    pool_recycle=3600,   # Recycle connections older than 1 hour
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
