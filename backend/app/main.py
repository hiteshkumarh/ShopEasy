from contextlib import asynccontextmanager
import logging
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import (
    addresses,
    admin_auth,
    admin_dashboard,
    admin_financial_settings,
    admin_plan_a,
    admin_plan_b,
    admin_products,
    admin_search,
    cart,
    cashback,
    customer_auth,
    dashboard,
    distributor_auth,
    distributor_reports,
    identity,
    notifications,
    orders,
    payments_simulated,
    payments_webhook,
    products,
    referrals,
    wallets,
)
from app.core.config import settings
from app.core.database import get_db
from app.services.fulfilment.scheduler import recovery_scheduler

# Configure logger
logger = logging.getLogger("shopeasy")

# Ephemeral server startup instance identifier for client session-start tracking
SERVER_INSTANCE_ID = uuid.uuid4().hex[:12]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI application lifespan context manager for graceful startup and shutdown."""
    try:
        # Startup: Start fulfilment recovery background scheduler if enabled
        if settings.FULFILMENT_RECOVERY_ENABLED:
            logger.info("Starting background fulfilment recovery scheduler...")
            recovery_scheduler.start()
        yield
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Application lifespan received cancellation or interrupt signal during shutdown.")
    finally:
        # Shutdown: Gracefully stop background scheduler and drain active workers
        if recovery_scheduler.is_running:
            logger.info("Gracefully stopping background fulfilment recovery scheduler...")
            try:
                await recovery_scheduler.stop()
            except Exception as exc:
                logger.warning(f"Error stopping fulfilment recovery scheduler: {exc}")


app = FastAPI(
    title="ShopEasy API",
    description="Backend API for ShopEasy e-commerce application",
    version="1.0.0",
    lifespan=lifespan,
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
async def add_security_headers(request: Request, call_next):
    """Inject standard security, cache control, and content protection headers."""
    response = await call_next(request)

    # Attach ephemeral server instance identifier for fresh-session detection in local development
    response.headers["X-Server-Instance-Id"] = SERVER_INSTANCE_ID

    # 1. Disable aggressive browser caching for development, dynamic content, and API routes
    path = request.url.path.lower()
    if path.endswith((".html", ".js", ".css", ".json")) or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    # 2. Prevent clickjacking by forbidding iframe framing
    response.headers["X-Frame-Options"] = "DENY"

    # 3. Prevent MIME-type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # 4. Strict referrer policy protecting query parameters and sensitive URL parts
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # 5. Restrict unused browser hardware APIs
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

    # 6. HTTP Strict Transport Security (HSTS) - Enabled strictly when request is over HTTPS
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )
    if is_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # 7. Content Security Policy (CSP) tailored to ShopEasy frontend assets
    # Note: 'unsafe-inline' is required for existing frontend HTML pages that register
    # DOMContentLoaded event listeners inline and dynamically inject style attributes.
    # Images are permitted from self, inline data URIs, and Unsplash CDN used by product catalog.
    csp_directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https://images.unsplash.com",
        "connect-src 'self'",
        "font-src 'self' data:",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

    return response


@app.exception_handler(OperationalError)
@app.exception_handler(ProgrammingError)
@app.exception_handler(DBAPIError)
async def database_exception_handler(request: Request, exc: Exception):
    """Intercept database connection or schema errors without leaking SQL internals.

    Enforces:
      - Diagnostic information is logged securely on the server with stack trace.
      - Never exposes database hostnames, usernames, passwords, or raw SQL queries to client.
      - Returns structured HTTP 503 Service Unavailable with clear, safe client message.
    """
    logger.error(
        f"Database operation failed on path '{request.url.path}': {type(exc).__name__}: {exc}",
        exc_info=True,
    )

    # Check if error indicates missing database tables (MySQL error 1146 or SQLite no such table)
    orig = getattr(exc, "orig", None)
    err_str = f"{exc} {orig}".lower()
    is_table_missing = False
    if orig and hasattr(orig, "args") and len(orig.args) > 0 and orig.args[0] == 1146:
        is_table_missing = True
    elif "doesn't exist" in err_str or "no such table" in err_str or "1146" in err_str:
        is_table_missing = True

    if is_table_missing:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "code": "DATABASE_SCHEMA_UNAVAILABLE",
                "message": "The service database schema is currently unavailable or initializing. Please try again shortly.",
            },
        )

    # Operational errors (connection loss, server unreachable, locks) indicate a database service outage
    if isinstance(exc, OperationalError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "code": "DATABASE_UNAVAILABLE",
                "message": "The database service is temporarily unavailable. Please try again shortly.",
            },
        )

    # Unrelated ProgrammingError or other DBAPI errors are application/query bugs, not infrastructure outages
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An internal database error occurred while processing the request.",
        },
    )


@app.get("/api/health")
def read_health():
    """Root health-check endpoint."""
    return {
        "message": "ShopEasy backend is running",
        "instance_id": SERVER_INSTANCE_ID,
    }


@app.get("/api/health/db")
def health_check_db(db: Session = Depends(get_db)):
    """Test database connectivity using SQLAlchemy text('SELECT 1')."""
    try:
        # Execute basic query to verify connection
        db.execute(text("SELECT 1"))
        res = {
            "status": "healthy",
            "database": "connected",
        }
        # Reveal database_name only in non-production environments to prevent reconnaissance
        if not settings.is_production:
            res["database_name"] = settings.DB_NAME
        return res
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
app.include_router(distributor_auth.router, prefix="/api/v1/auth")
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
app.include_router(cashback.router, prefix="/api/v1")

# Mount API v1 In-Dashboard Notifications Router (WP-11)
app.include_router(notifications.router, prefix="/api/v1")

# Mount API v1 Plan A & Plan B Admin Inspection Routers (WP-11)
app.include_router(admin_plan_a.router, prefix="/api/v1")
app.include_router(admin_plan_b.router, prefix="/api/v1")
app.include_router(admin_financial_settings.router, prefix="/api/v1")
app.include_router(admin_search.router, prefix="/api/v1")

# Mount API v1 Plan B Distributor Self-Service Reports Router (WP-11)
app.include_router(distributor_reports.router, prefix="/api/v1")

# Mount API v1 Referral Code Validation Router
app.include_router(referrals.router, prefix="/api/v1")

# Mount API v1 Payments Routers (WP-5)
# Webhook router is mounted unconditionally in all environments
app.include_router(payments_webhook.router, prefix="/api/v1")

# Simulated payment router is mounted strictly outside production when simulation is enabled
if not settings.is_production and settings.ALLOW_SIMULATED_PAYMENTS:
    app.include_router(payments_simulated.router, prefix="/api/v1")

# Mount static frontend files after all API routers to prevent route shadowing
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
