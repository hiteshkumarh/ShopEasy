import logging
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (
    addresses,
    admin_auth,
    admin_products,
    cart,
    customer_auth,
    dashboard,
    identity,
    orders,
    products,
    wallets,
)
from app.core.config import settings
from app.core.database import get_db

# Configure logger
logger = logging.getLogger("shopeasy")

app = FastAPI(
    title="ShopEasy API",
    description="Backend API for ShopEasy e-commerce application",
    version="1.0.0",
)

# Configure CORS middleware for frontend origin access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configurable in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    """Root health-check endpoint."""
    return {"message": "ShopEasy backend is running"}


@app.get("/api/health/db")
def health_check_db(db: Session = Depends(get_db)):
    """Test database connectivity using SQLAlchemy text('SELECT 1')."""
    try:
        # Execute basic query to verify connection
        db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
            "database_name": settings.DB_NAME,
        }
    except Exception as exc:
        # Log error internally without exposing credentials to caller
        logger.error(f"Database health check failed: {type(exc).__name__}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "message": "Database connection could not be established.",
            },
        )


# Mount API v1 Authentication & Identity Routers
app.include_router(customer_auth.router, prefix="/api/v1/auth")
app.include_router(admin_auth.router, prefix="/api/v1/auth")
app.include_router(identity.router, prefix="/api/v1/auth")

# Mount API v1 Product Catalog & Admin Product Management Routers
app.include_router(products.router, prefix="/api/v1")
app.include_router(admin_products.router, prefix="/api/v1")

# Mount API v1 Cart, Addresses & Orders Routers
app.include_router(cart.router, prefix="/api/v1")
app.include_router(addresses.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")

# Mount API v1 Wallets & Customer Dashboard Routers
app.include_router(wallets.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
