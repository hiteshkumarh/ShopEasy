"""Test suite for WP-11 Step 4: Admin Financial Configuration API (AD-06 / ED-02).

Verifies:
1. Unauthenticated request returns HTTP 401.
2. Non-admin roles (customer, distributor) return HTTP 403.
3. Authorized admin can retrieve settings (with programme and as_of filtering).
4. Authorized admin can create/update a prospective setting.
5. Past effective dates are strictly rejected with HTTP 400 (ED-02).
6. Invalid effective window (effective_to <= effective_from) is rejected with HTTP 400.
7. Audit record is created via AuditService for successful mutations.
8. Version incrementing and previous-version closure remain strictly preserved.
9. Response does not expose secrets or internal sensitive fields.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit import AuditLog
from app.models.enums import AccountStatus, Programme, UserRole
from app.models.financial_settings import FinancialSetting, FinancialSettingHistory
from app.models.user import User
from app.services.financial_settings import FinancialSettingsService, SettingKey, seed_financial_settings


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client with overridden db session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_user(db_session: Session):
    """Factory fixture for test users."""
    counter = [900]

    def _create_user(
        programme: Programme = Programme.PLAN_A,
        role: UserRole = UserRole.CUSTOMER,
        referral_code: str = None,
    ) -> User:
        counter[0] += 1
        num = counter[0]
        code = None if role == UserRole.ADMIN else (referral_code or f"FS{num:05d}")

        user = User(
            phone=f"96666{num:05d}",
            full_name=f"FS User {num}",
            role=role,
            programme=programme,
            account_status=AccountStatus.ACTIVE,
            referral_code=code,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _create_user


@pytest.fixture
def auth_headers():
    """Generate Bearer authorization headers for a given User."""
    def _headers(user: User) -> dict:
        token = create_access_token(
            user_id=user.id,
            role=user.role.value,
            phone=user.phone,
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers


class TestAdminFinancialSettingsAuth:
    """Test authentication and authorization boundaries for financial settings."""

    def test_unauthenticated_requests_rejected_with_401(self, client: TestClient):
        """Unauthenticated requests must be rejected with 401."""
        res_get = client.get("/api/v1/admin/financial-settings")
        assert res_get.status_code == 401

        res_post = client.post(
            "/api/v1/admin/financial-settings",
            json={
                "programme": "PLAN_A",
                "setting_key": "pa_commission_gross",
                "setting_value": "800.00",
                "change_reason": "Rate review",
            },
        )
        assert res_post.status_code == 401

    def test_non_admin_roles_rejected_with_403(
        self, client: TestClient, make_user, auth_headers
    ):
        """Customer and Plan B distributor users must receive 403 Forbidden."""
        customer = make_user(programme=Programme.PLAN_A, role=UserRole.CUSTOMER)
        distributor = make_user(programme=Programme.PLAN_B, role=UserRole.CUSTOMER)

        for user in [customer, distributor]:
            headers = auth_headers(user)
            res_get = client.get("/api/v1/admin/financial-settings", headers=headers)
            assert res_get.status_code == 403, f"Expected 403 for user #{user.id}, got {res_get.status_code}"

            res_post = client.post(
                "/api/v1/admin/financial-settings",
                headers=headers,
                json={
                    "programme": "PLAN_A",
                    "setting_key": "pa_commission_gross",
                    "setting_value": "800.00",
                    "change_reason": "Rate review",
                },
            )
            assert res_post.status_code == 403, f"Expected 403 for user #{user.id}, got {res_post.status_code}"


class TestAdminFinancialSettingsOperations:
    """Test financial settings listing, filtering, creation, prospective updates, and auditing."""

    def test_admin_list_financial_settings(
        self, client: TestClient, db_session: Session, make_user, auth_headers
    ):
        """Admin can list and filter settings by programme and setting_key."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        seed_financial_settings(db_session, created_by_id=admin.id)
        db_session.commit()

        headers = auth_headers(admin)

        # 1. List all
        res = client.get("/api/v1/admin/financial-settings", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] > 0
        assert len(data["items"]) == data["total"]

        # Verify no sensitive fields in response
        for item in data["items"]:
            assert "password" not in item
            assert "password_hash" not in item
            assert "token" not in item
            assert "otp" not in item
            assert "dev_otp" not in item
            assert "secret" not in item
            assert "created_by" not in item  # Only created_by_id allowed

        # 2. Filter by programme
        res_pa = client.get("/api/v1/admin/financial-settings?programme=PLAN_A", headers=headers)
        assert res_pa.status_code == 200
        data_pa = res_pa.json()
        assert all(it["programme"] == "PLAN_A" for it in data_pa["items"])

        res_pb = client.get("/api/v1/admin/financial-settings?programme=PLAN_B", headers=headers)
        assert res_pb.status_code == 200
        data_pb = res_pb.json()
        assert all(it["programme"] == "PLAN_B" for it in data_pb["items"])

        # 3. Filter by setting_key
        res_key = client.get(
            f"/api/v1/admin/financial-settings?programme=PLAN_A&setting_key={SettingKey.COMMISSION_GROSS}",
            headers=headers,
        )
        assert res_key.status_code == 200
        data_key = res_key.json()
        assert data_key["total"] == 1
        assert data_key["items"][0]["setting_key"] == SettingKey.COMMISSION_GROSS
        assert Decimal(str(data_key["items"][0]["setting_value"])) == Decimal("750.000000")

    def test_admin_as_of_historical_resolution(
        self, client: TestClient, db_session: Session, make_user, auth_headers
    ):
        """Historical as_of query resolves setting active at that timestamp."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        service = FinancialSettingsService(db_session)

        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 6, 1, 0, 0, 0)

        # Create setting v1 effective from t1
        s1 = service.create(
            programme=Programme.PLAN_A,
            setting_key="test_historical_key",
            setting_value=Decimal("100.000000"),
            effective_from=t1,
            created_by_id=admin.id,
            reason="V1 creation",
        )
        # Update setting to v2 effective from t2
        s2 = service.update(
            programme=Programme.PLAN_A,
            setting_key="test_historical_key",
            new_value=Decimal("200.000000"),
            effective_from=t2,
            changed_by_id=admin.id,
            reason="V2 update",
        )
        db_session.commit()

        headers = auth_headers(admin)

        # Query as of t1 + 1 month -> should resolve V1 (100.00)
        as_of_v1 = (t1 + timedelta(days=30)).isoformat()
        res_v1 = client.get(
            f"/api/v1/admin/financial-settings?programme=PLAN_A&setting_key=test_historical_key&as_of={as_of_v1}",
            headers=headers,
        )
        assert res_v1.status_code == 200
        data_v1 = res_v1.json()
        assert data_v1["total"] == 1
        assert data_v1["items"][0]["version"] == 1
        assert Decimal(str(data_v1["items"][0]["setting_value"])) == Decimal("100.000000")

        # Query as of t2 + 1 month -> should resolve V2 (200.00)
        as_of_v2 = (t2 + timedelta(days=30)).isoformat()
        res_v2 = client.get(
            f"/api/v1/admin/financial-settings?programme=PLAN_A&setting_key=test_historical_key&as_of={as_of_v2}",
            headers=headers,
        )
        assert res_v2.status_code == 200
        data_v2 = res_v2.json()
        assert data_v2["total"] == 1
        assert data_v2["items"][0]["version"] == 2
        assert Decimal(str(data_v2["items"][0]["setting_value"])) == Decimal("200.000000")

    def test_admin_create_and_prospective_update_with_audit(
        self, client: TestClient, db_session: Session, make_user, auth_headers
    ):
        """Admin can create a new setting and update it prospectively with audit logging."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        headers = auth_headers(admin)

        # 1. Create a brand new setting via POST
        create_payload = {
            "programme": "PLAN_A",
            "setting_key": "custom_reward_rate",
            "setting_value": "125.500000",
            "currency": "INR",
            "description": "Custom promotional reward rate",
            "change_reason": "Initial policy definition",
        }
        res_create = client.post(
            "/api/v1/admin/financial-settings",
            headers=headers,
            json=create_payload,
        )
        assert res_create.status_code == 200
        created_data = res_create.json()
        assert created_data["version"] == 1
        assert created_data["setting_key"] == "CUSTOM_REWARD_RATE"
        assert Decimal(str(created_data["setting_value"])) == Decimal("125.500000")
        assert created_data["is_active"] is True
        assert created_data["created_by_id"] == admin.id

        # Verify audit log for CREATE
        audit_create = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "CREATE_FINANCIAL_SETTING",
                AuditLog.entity_id == str(created_data["id"]),
            )
            .first()
        )
        assert audit_create is not None
        assert audit_create.actor_id == admin.id
        assert audit_create.actor_role == "admin"
        assert "custom_reward_rate" in audit_create.metadata_json

        # 2. Update the setting prospectively (future effective date)
        future_eff = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        update_payload = {
            "programme": "PLAN_A",
            "setting_key": "custom_reward_rate",
            "setting_value": "150.000000",
            "effective_from": future_eff,
            "change_reason": "Quarterly rate increase",
        }
        res_update = client.post(
            "/api/v1/admin/financial-settings",
            headers=headers,
            json=update_payload,
        )
        assert res_update.status_code == 200
        updated_data = res_update.json()
        assert updated_data["version"] == 2
        assert Decimal(str(updated_data["setting_value"])) == Decimal("150.000000")
        assert updated_data["is_active"] is True

        # Verify that previous version (version 1) was superseded and closed
        v1_in_db = (
            db_session.query(FinancialSetting)
            .filter(
                FinancialSetting.programme == Programme.PLAN_A,
                FinancialSetting.setting_key == "CUSTOM_REWARD_RATE",
                FinancialSetting.version == 1,
            )
            .first()
        )
        assert v1_in_db.is_active is False
        assert v1_in_db.effective_to is not None

        # Verify audit log for UPDATE
        audit_update = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "UPDATE_FINANCIAL_SETTING",
                AuditLog.entity_id == str(updated_data["id"]),
            )
            .first()
        )
        assert audit_update is not None
        assert audit_update.actor_id == admin.id
        assert "Quarterly rate increase" in audit_update.metadata_json
        assert "125.50" in audit_update.old_values
        assert "150.00" in audit_update.new_values

    def test_past_effective_date_rejected_per_ed02(
        self, client: TestClient, db_session: Session, make_user, auth_headers
    ):
        """Past effective dates must be strictly rejected with HTTP 400."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        headers = auth_headers(admin)

        past_eff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        payload = {
            "programme": "PLAN_A",
            "setting_key": "retroactive_attempt_key",
            "setting_value": "99.00",
            "effective_from": past_eff,
            "change_reason": "Illegal retroactive edit attempt",
        }
        res = client.post(
            "/api/v1/admin/financial-settings",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 400
        assert "prohibited per ED-02" in res.json()["detail"]

    def test_invalid_effective_window_rejected_with_400(
        self, client: TestClient, db_session: Session, make_user, auth_headers
    ):
        """effective_to <= effective_from must be rejected with HTTP 400."""
        admin = make_user(programme=Programme.PLAN_A, role=UserRole.ADMIN)
        headers = auth_headers(admin)

        eff_from = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        eff_to = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()  # before eff_from

        payload = {
            "programme": "PLAN_A",
            "setting_key": "invalid_window_key",
            "setting_value": "99.00",
            "effective_from": eff_from,
            "effective_to": eff_to,
            "change_reason": "Invalid window",
        }
        res = client.post(
            "/api/v1/admin/financial-settings",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 400
        assert "effective_to must be strictly after effective_from" in res.json()["detail"]
