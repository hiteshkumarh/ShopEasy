"""Focused tests for WP-13 Stage 1 Security Hardening.

Covers:
  1. Authentication rate limiting, HTTP 429 response, and Retry-After header.
  2. Rate limit test isolation and user enumeration protection.
  3. Standard HTTP security headers (X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy).
  4. Content Security Policy (CSP) directives and frontend asset compatibility.
  5. Conditional HSTS (Strict-Transport-Security) only on HTTPS.
  6. Plan A vs Plan B programme isolation on /dashboard/earnings and /dashboard/referrals.
  7. Central AuditLog records for admin withdrawal approval, rejection, and admin login.
  8. Safe database error handling (HTTP 503) without SQL traceback leakage.
  9. Health endpoint exposure control (omission of database_name in production).
  10. Password authentication without OTP continuity for customer and distributor.
"""

from decimal import Decimal
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import clear_rate_limits, get_rate_limiter
from app.core.security import create_access_token, hash_password
from app.models.audit import AuditLog
from app.models.enums import AccountStatus, Programme, UserRole, WalletType, WithdrawalStatus
from app.models.user import User
from app.models.wallet import Wallet, Withdrawal
from app.services.wallet_service import (
    admin_approve_withdrawal,
    admin_reject_withdrawal,
    get_or_create_wallet,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter_state():
    """Ensure rate limiter state is reset before and after every test."""
    clear_rate_limits()
    yield
    clear_rate_limits()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user_for_test(
    db: Session,
    phone: str,
    role: UserRole = UserRole.CUSTOMER,
    programme: Programme = Programme.PLAN_A,
    account_status: AccountStatus = AccountStatus.ACTIVE,
    password: str = "TestPassword123!",
) -> User:
    user = User(
        phone=phone,
        full_name=f"User {phone[-4:]}",
        password_hash=hash_password(password),
        role=role,
        programme=programme,
        account_status=account_status,
        referral_code=None if role == UserRole.ADMIN else f"REF{phone[-4:]}",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 1. Rate Limiting Tests
# ---------------------------------------------------------------------------

class TestAuthenticationRateLimiting:
    """Verify rate limiting protects authentication routes against brute-force attacks."""

    def test_customer_login_rate_limiting_enforced(self, api_client: TestClient, db_session: Session):
        """10 rapid login attempts are allowed; the 11th triggers HTTP 429 with Retry-After header."""
        user = create_user_for_test(db_session, "9876543201")

        # 10 attempts allowed
        for _ in range(10):
            res = api_client.post(
                "/api/v1/auth/customer/login/password",
                json={"phone": "9876543201", "password": "WrongPassword!"},
            )
            assert res.status_code == 401

        # 11th attempt blocked
        res_blocked = api_client.post(
            "/api/v1/auth/customer/login/password",
            json={"phone": "9876543201", "password": "WrongPassword!"},
        )
        assert res_blocked.status_code == 429
        assert "Retry-After" in res_blocked.headers
        assert int(res_blocked.headers["Retry-After"]) > 0
        assert "Too many requests" in res_blocked.json()["detail"]

    def test_rate_limit_generic_message_does_not_leak_registration(self, api_client: TestClient):
        """Rate limit response is generic and does not disclose whether a phone number exists."""
        for _ in range(10):
            api_client.post(
                "/api/v1/auth/customer/login/password",
                json={"phone": "9000000000", "password": "DummyPassword123!"},
            )

        res = api_client.post(
            "/api/v1/auth/customer/login/password",
            json={"phone": "9000000000", "password": "DummyPassword123!"},
        )
        assert res.status_code == 429
        # Does not say "phone 9000000000 is blocked" or "user exists"
        assert res.json()["detail"] == "Too many requests. Please try again shortly."

    def test_admin_login_rate_limiting_stricter_threshold(self, api_client: TestClient, db_session: Session):
        """Admin login enforces a stricter 5-request limit per minute."""
        admin = create_user_for_test(db_session, "9800000001", role=UserRole.ADMIN)

        for _ in range(5):
            res = api_client.post(
                "/api/v1/auth/admin/login/password",
                json={"phone": "9800000001", "password": "WrongPassword!"},
            )
            assert res.status_code == 401

        # 6th attempt blocked
        res_blocked = api_client.post(
            "/api/v1/auth/admin/login/password",
            json={"phone": "9800000001", "password": "WrongPassword!"},
        )
        assert res_blocked.status_code == 429
        assert "Retry-After" in res_blocked.headers

    def test_registration_rate_limiting_enforced(self, api_client: TestClient):
        """Registration route permits at most 5 attempts per minute per IP."""
        for i in range(5):
            api_client.post(
                "/api/v1/auth/customer/register",
                json={
                    "full_name": f"Test User {i}",
                    "phone": f"911111110{i}",
                    "password": "Password123!",
                    "confirm_password": "Password123!",
                    "programme": "PLAN_A",
                },
            )

        # 6th attempt blocked
        res_blocked = api_client.post(
            "/api/v1/auth/customer/register",
            json={
                "full_name": "Test User 6",
                "phone": "9111111106",
                "password": "Password123!",
                "confirm_password": "Password123!",
                "programme": "PLAN_A",
            },
        )
        assert res_blocked.status_code == 429
        assert "Retry-After" in res_blocked.headers


# ---------------------------------------------------------------------------
# 2. Security Headers & CSP Tests
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Verify presence and correctness of security HTTP headers."""

    def test_standard_security_headers_present(self, api_client: TestClient):
        """All responses must contain X-Frame-Options, nosniff, Referrer-Policy, and Permissions-Policy."""
        res = api_client.get("/api/health")
        assert res.status_code == 200

        headers = res.headers
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "camera=()" in headers.get("Permissions-Policy", "")

    def test_content_security_policy_directives(self, api_client: TestClient):
        """CSP must contain required directives supporting existing frontend scripts and Unsplash CDN."""
        res = api_client.get("/api/health")
        csp = res.headers.get("Content-Security-Policy", "")

        assert "default-src 'self'" in csp
        assert "script-src 'self' 'unsafe-inline'" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "https://images.unsplash.com" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_hsts_disabled_on_plain_http(self, api_client: TestClient):
        """Plain HTTP requests must NOT receive Strict-Transport-Security to prevent breaking local dev."""
        res = api_client.get("/api/health")
        assert "Strict-Transport-Security" not in res.headers

    def test_hsts_enabled_when_forwarded_proto_https(self, api_client: TestClient):
        """Requests with X-Forwarded-Proto: https must receive Strict-Transport-Security header."""
        res = api_client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" in res.headers
        assert "max-age=31536000" in res.headers["Strict-Transport-Security"]


# ---------------------------------------------------------------------------
# 3. Programme Authorization Isolation Tests
# ---------------------------------------------------------------------------

class TestProgrammeDashboardIsolation:
    """Verify Plan A / Plan B financial dashboard authorization separation."""

    def test_plan_a_customer_can_access_earnings_dashboard(self, api_client: TestClient, db_session: Session):
        """Plan A customer can access /api/v1/dashboard/earnings."""
        user = create_user_for_test(db_session, "9876543202", programme=Programme.PLAN_A)
        token = create_access_token(user_id=user.id, role="customer", phone=user.phone)

        res = api_client.get(
            "/api/v1/dashboard/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert "direct_referral_balance" in res.json()
        assert "sequential_progress" in res.json()

    def test_plan_b_distributor_blocked_from_plan_a_earnings_with_403(
        self, api_client: TestClient, db_session: Session
    ):
        """Plan B distributor calling /api/v1/dashboard/earnings receives HTTP 403 Forbidden."""
        distributor = create_user_for_test(db_session, "9876543203", programme=Programme.PLAN_B)
        token = create_access_token(user_id=distributor.id, role="customer", phone=distributor.phone)

        res = api_client.get(
            "/api/v1/dashboard/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        assert "Plan A customer privileges required" in res.json()["detail"]

    def test_plan_b_distributor_blocked_from_plan_a_referrals_with_403(
        self, api_client: TestClient, db_session: Session
    ):
        """Plan B distributor calling /api/v1/dashboard/referrals receives HTTP 403 Forbidden."""
        distributor = create_user_for_test(db_session, "9876543204", programme=Programme.PLAN_B)
        token = create_access_token(user_id=distributor.id, role="customer", phone=distributor.phone)

        res = api_client.get(
            "/api/v1/dashboard/referrals",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403
        assert "Plan A customer privileges required" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Central Audit Logging Tests
# ---------------------------------------------------------------------------

class TestAdministrativeAuditLogging:
    """Verify sensitive administrative actions record immutable AuditLog entries."""

    def test_admin_approve_withdrawal_records_audit_log(self, db_session: Session):
        """Approving a withdrawal appends an AuditLog entry with action WITHDRAWAL_APPROVED."""
        admin = create_user_for_test(db_session, "9800000002", role=UserRole.ADMIN)
        user = create_user_for_test(db_session, "9876543205", programme=Programme.PLAN_B)
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        wallet.balance = Decimal("1000.00")
        db_session.flush()

        withdrawal = Withdrawal(
            user_id=user.id,
            wallet_id=wallet.id,
            amount=Decimal("1000.00"),
            status=WithdrawalStatus.REQUESTED,
            idempotency_key="WD-TEST-AUDIT-001",
        )
        db_session.add(withdrawal)
        db_session.commit()

        # Approve
        admin_approve_withdrawal(db_session, withdrawal.id, admin.id)
        db_session.commit()

        # Verify audit log entry
        audit = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "WITHDRAWAL_APPROVED",
                AuditLog.entity_id == str(withdrawal.id),
            )
            .first()
        )
        assert audit is not None
        assert audit.actor_id == admin.id
        assert audit.actor_role == "admin"
        assert audit.entity_type == "Withdrawal"
        assert "1000.00" in audit.metadata_json

    def test_admin_reject_withdrawal_records_audit_log(self, db_session: Session):
        """Rejecting a withdrawal appends an AuditLog entry with action WITHDRAWAL_REJECTED and reason."""
        admin = create_user_for_test(db_session, "9800000003", role=UserRole.ADMIN)
        user = create_user_for_test(db_session, "9876543206", programme=Programme.PLAN_B)
        wallet = get_or_create_wallet(db_session, user.id, WalletType.DIRECT_REFERRAL)
        wallet.balance = Decimal("1000.00")
        db_session.flush()

        withdrawal = Withdrawal(
            user_id=user.id,
            wallet_id=wallet.id,
            amount=Decimal("1000.00"),
            status=WithdrawalStatus.REQUESTED,
            idempotency_key="WD-TEST-AUDIT-002",
        )
        db_session.add(withdrawal)
        db_session.commit()

        # Reject
        admin_reject_withdrawal(db_session, withdrawal.id, admin.id, reason="Suspicious compliance flag")
        db_session.commit()

        # Verify audit log entry
        audit = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "WITHDRAWAL_REJECTED",
                AuditLog.entity_id == str(withdrawal.id),
            )
            .first()
        )
        assert audit is not None
        assert audit.actor_id == admin.id
        assert "Suspicious compliance flag" in audit.new_values

    def test_admin_login_records_audit_log(self, api_client: TestClient, db_session: Session):
        """Admin password login records an ADMIN_LOGIN_SUCCESS audit log entry."""
        admin = create_user_for_test(db_session, "9800000004", role=UserRole.ADMIN, password="AdminPassword123!")

        res = api_client.post(
            "/api/v1/auth/admin/login/password",
            json={"phone": "9800000004", "password": "AdminPassword123!"},
        )
        assert res.status_code == 200

        audit = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "ADMIN_LOGIN_SUCCESS",
                AuditLog.entity_id == str(admin.id),
            )
            .first()
        )
        assert audit is not None
        assert audit.actor_id == admin.id


# ---------------------------------------------------------------------------
# 5. Database Exception Handling Tests
# ---------------------------------------------------------------------------

class TestDatabaseExceptionHandling:
    """Verify missing tables or database failures return safe HTTP 503 responses."""

    def test_unmigrated_table_returns_safe_503(self, api_client: TestClient, monkeypatch):
        """When an unhandled ProgrammingError (table missing) occurs, client receives safe 503."""
        from app.models.user import User

        def mock_query(*args, **kwargs):
            raise ProgrammingError("SELECT * FROM non_existent_table", {}, Exception("Table 'shopeasy_arya.users' doesn't exist"))

        # Trigger on user query in /api/v1/auth/customer/login/password
        monkeypatch.setattr(Session, "query", mock_query)

        res = api_client.post(
            "/api/v1/auth/customer/login/password",
            json={"phone": "9876543201", "password": "Password123!"},
        )
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "error"
        assert data["code"] == "DATABASE_SCHEMA_UNAVAILABLE"
        # Must not leak SQL or database hostname/schema
        assert "SELECT" not in data["message"]
        assert "shopeasy_arya" not in data["message"]

    def test_operational_error_returns_safe_503_database_unavailable(self, api_client: TestClient, monkeypatch):
        """When an OperationalError (connection refused/timeout) occurs, client receives safe 503 DATABASE_UNAVAILABLE."""
        def mock_query(*args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("2003: Can't connect to MySQL server"))

        monkeypatch.setattr(Session, "query", mock_query)

        res = api_client.post(
            "/api/v1/auth/customer/login/password",
            json={"phone": "9876543201", "password": "Password123!"},
        )
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "error"
        assert data["code"] == "DATABASE_UNAVAILABLE"
        assert "SELECT" not in data["message"]

    def test_unrelated_programming_error_returns_safe_500_not_classified_as_outage(self, api_client: TestClient, monkeypatch):
        """Unrelated ProgrammingError (SQL syntax/column error) returns 500, not misclassified as a database outage."""
        def mock_query(*args, **kwargs):
            raise ProgrammingError("SELECT bad_syntax FROM users", {}, Exception("1064: You have an error in your SQL syntax"))

        monkeypatch.setattr(Session, "query", mock_query)

        res = api_client.post(
            "/api/v1/auth/customer/login/password",
            json={"phone": "9876543201", "password": "Password123!"},
        )
        assert res.status_code == 500
        data = res.json()
        assert data["status"] == "error"
        assert data["code"] == "INTERNAL_SERVER_ERROR"
        # Must not be misclassified as DATABASE_UNAVAILABLE
        assert data["code"] != "DATABASE_UNAVAILABLE"
        assert "bad_syntax" not in data["message"]


# ---------------------------------------------------------------------------
# 6. Production Health Exposure Test
# ---------------------------------------------------------------------------

class TestHealthEndpointExposure:
    """Verify health endpoint does not leak internal schema name in production."""

    def test_health_db_omits_database_name_in_production(self, api_client: TestClient, monkeypatch):
        """In production environment, GET /api/health/db returns connected status but omits database_name."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")

        res = api_client.get("/api/health/db")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert "database_name" not in data

    def test_health_db_includes_database_name_in_non_production(self, api_client: TestClient, monkeypatch):
        """In non-production environment, GET /api/health/db includes database_name for dev convenience."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")

        res = api_client.get("/api/health/db")
        assert res.status_code == 200
        data = res.json()
        assert "database_name" in data


# ---------------------------------------------------------------------------
# 7. Password Authentication Continuity
# ---------------------------------------------------------------------------

class TestPasswordAuthenticationContinuity:
    """Verify existing password-based login continues to work without OTP requirements."""

    def test_customer_password_login_succeeds(self, api_client: TestClient, db_session: Session):
        """Customer logs in directly with phone and password, receiving a valid JWT."""
        user = create_user_for_test(db_session, "9876543207", password="ValidPassword123!")

        res = api_client.post(
            "/api/v1/auth/customer/login/password",
            json={"phone": "9876543207", "password": "ValidPassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["role"] == "customer"

    def test_distributor_password_login_succeeds(self, api_client: TestClient, db_session: Session):
        """Plan B distributor logs in directly with phone and password, receiving a valid JWT."""
        dist = create_user_for_test(db_session, "9876543208", programme=Programme.PLAN_B, password="ValidPassword123!")

        res = api_client.post(
            "/api/v1/auth/distributor/login/password",
            json={"phone": "9876543208", "password": "ValidPassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["role"] == "customer"

