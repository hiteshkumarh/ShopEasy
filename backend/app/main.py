import logging
from pathlib import Path

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (
    addresses,
    admin_auth,
    admin_dashboard,
    admin_products,
    cart,
    customer_auth,
    dashboard,
    identity,
    orders,
    products,
    referrals,
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

# Same-origin deployment needs no CORS origins. Cross-origin deployments may
# provide an explicit comma-separated CORS_ORIGINS environment variable.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    """Disable aggressive browser caching for development and evaluation."""
    response = await call_next(request)
    path = request.url.path.lower()
    if path.endswith((".html", ".js", ".css", ".json")) or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/api/health")
def read_health():
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
app.include_router(admin_dashboard.router, prefix="/api/v1")

# Mount API v1 Cart, Addresses & Orders Routers
app.include_router(cart.router, prefix="/api/v1")
app.include_router(addresses.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")

# Mount API v1 Wallets & Customer Dashboard Routers
app.include_router(wallets.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")

# Mount API v1 Referral Code Validation Router
app.include_router(referrals.router, prefix="/api/v1")

# Mount static frontend files after all API routers to prevent route shadowing
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
