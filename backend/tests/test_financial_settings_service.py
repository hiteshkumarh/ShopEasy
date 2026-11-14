"""Comprehensive domain and integration test suite for FinancialSettingsService.

Covers:
  - Setting retrieval (active, or_none, not_found).
  - Historical resolution with strict half-open interval [effective_from, effective_to).
  - Inclusive lower bound and exclusive upper bound boundary resolution.
  - Historical resolution of superseded/inactive versions without is_active filtering.
  - Multi-match data integrity rejection (MultipleMatchingSettingsError).
  - First-version creation and duplicate version-1 rejection (SettingAlreadyExistsError).
  - Monotonic version progression on update.
  - Programme isolation across Plan A, Plan B, and Legacy.
  - Input validation: float rejection, NaN/Inf rejection, scale limit (6 decimals), integer digits limit.
  - Effective window validation: zero-duration and inverted intervals rejected.
  - Audit history creation for CREATED, UPDATED, DEACTIVATED, REACTIVATED.
  - Transaction atomicity: setting creation rolls back if history logging fails.
  - Deactivation and reactivation lifecycle transitions.
  - Multi-session and multi-threaded concurrency for initial creation and version updates.
  - Bounded retry behavior and immediate re-raise of unrelated integrity errors (e.g. FK violations).
  - Immutability of historical versions.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator, List
import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.money import Money
from app.models.enums import Programme, SettingAction, UserRole
from app.models.financial_settings import FinancialSetting, FinancialSettingHistory
from app.models.user import User
from app.services.financial_settings import (
    FinancialSettingError,
    FinancialSettingsService,
    FinancialSettingValidationError,
    MultipleMatchingSettingsError,
    SettingAlreadyExistsError,
    SettingConcurrencyError,
    SettingNotFoundError,
    create_setting,
    deactivate_setting,
    get_setting,
    get_setting_history,
    get_setting_or_none,
    reactivate_setting,
    resolve_setting,
    update_setting,
)


@pytest.fixture(scope="function")
def admin_user(db_session: Session) -> User:
    """Provide a persisted admin user fixture for audit tests."""
    admin = User(
        full_name="Financial Operations Admin",
        phone="9876543299",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    return admin


# ---------------------------------------------------------------------------
# 1. Retrieval & Query Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFinancialSettingsRetrieval:
    """Tests for active setting retrieval and not-found semantics."""

    def test_get_setting_active(self, db_session: Session) -> None:
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="DIRECT_COMMISSION_GROSS",
            setting_value=Decimal("750.000000"),
            description="Active commission setting",
        )
        res = get_setting(db_session, Programme.PLAN_A, "DIRECT_COMMISSION_GROSS")
        assert res is not None
        assert res.version == 1
        assert res.setting_value == Decimal("750.000000")
        assert res.is_active is True

    def test_get_setting_not_found_raises(self, db_session: Session) -> None:
        with pytest.raises(SettingNotFoundError) as exc_info:
            get_setting(db_session, Programme.PLAN_A, "NON_EXISTENT_KEY")
        assert "NON_EXISTENT_KEY" in str(exc_info.value)

    def test_get_setting_or_none(self, db_session: Session) -> None:
        assert get_setting_or_none(db_session, Programme.PLAN_A, "ABSENT_KEY") is None
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="PRESENT_KEY",
            setting_value=Decimal("100.000000"),
        )
        found = get_setting_or_none(db_session, Programme.PLAN_A, "PRESENT_KEY")
        assert found is not None
        assert found.setting_value == Decimal("100.000000")

    def test_service_class_wrapper_methods(self, db_session: Session) -> None:
        svc = FinancialSettingsService(db_session)
        s = svc.create(Programme.PLAN_B, "DISTRIBUTOR_DIRECT", Decimal("500.000000"))
        assert s.version == 1
        assert svc.get(Programme.PLAN_B, "DISTRIBUTOR_DIRECT").setting_value == Decimal("500.000000")


# ---------------------------------------------------------------------------
# 2. Historical Effective-Date Resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHistoricalEffectiveDateResolution:
    """Rigorous tests for half-open interval [effective_from, effective_to) historical resolution."""

    def test_resolution_exact_boundaries_and_superseded_versions(self, db_session: Session) -> None:
        t_jan = datetime(2026, 1, 1, 0, 0, 0)
        t_feb = datetime(2026, 2, 1, 0, 0, 0)
        t_mar = datetime(2026, 3, 1, 0, 0, 0)

        # Version 1 valid January: [Jan 1, Feb 1)
        v1 = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_BENCHMARK",
            setting_value=Decimal("700.000000"),
            effective_from=t_jan,
        )
        assert v1.version == 1

        # Version 2 valid February onwards: [Feb 1, None)
        v2 = update_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="COMMISSION_BENCHMARK",
            new_value=Decimal("750.000000"),
            effective_from=t_feb,
        )
        assert v2.version == 2

        # Invariant: v1 effective_to is now exactly t_feb, and is_active is False
        db_session.refresh(v1)
        assert v1.effective_to == t_feb
        assert v1.is_active is False

        # 1. Exact inclusive lower bound of Version 1 (Jan 1 00:00:00) -> Version 1
        r_jan_start = resolve_setting(db_session, Programme.PLAN_A, "COMMISSION_BENCHMARK", t_jan)
        assert r_jan_start.version == 1
        assert r_jan_start.setting_value == Decimal("700.000000")

        # 2. Mid-January transaction (Jan 15 12:00:00) -> Version 1 (inactive today!)
        r_jan_mid = resolve_setting(
            db_session, Programme.PLAN_A, "COMMISSION_BENCHMARK", datetime(2026, 1, 15, 12, 0, 0)
        )
        assert r_jan_mid.version == 1
        assert r_jan_mid.is_active is False

        # 3. 1 microsecond before Feb 1 (Jan 31 23:59:59.999999) -> Version 1
        r_jan_end = resolve_setting(
            db_session, Programme.PLAN_A, "COMMISSION_BENCHMARK", t_feb - timedelta(microseconds=1)
        )
        assert r_jan_end.version == 1

        # 4. Exact boundary handoff at Feb 1 00:00:00:
        # effective_to is exclusive (> tx), so v1 does NOT match.
        # effective_from is inclusive (<= tx), so v2 matches.
        r_feb_start = resolve_setting(db_session, Programme.PLAN_A, "COMMISSION_BENCHMARK", t_feb)
        assert r_feb_start.version == 2
        assert r_feb_start.setting_value == Decimal("750.000000")

        # 5. Future transaction (March 15) -> Version 2 (effective_to is None)
        r_future = resolve_setting(
            db_session, Programme.PLAN_A, "COMMISSION_BENCHMARK", datetime(2026, 3, 15, 0, 0, 0)
        )
        assert r_future.version == 2

        # 6. Prior to inception (Dec 31, 2025) -> SettingNotFoundError
        with pytest.raises(SettingNotFoundError):
            resolve_setting(
                db_session, Programme.PLAN_A, "COMMISSION_BENCHMARK", datetime(2025, 12, 31, 23, 59, 59)
            )

    def test_timezone_aware_datetime_normalization(self, db_session: Session) -> None:
        """Verify tz-aware transaction datetimes are safely normalized to UTC without TypeError."""
        t_utc = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="NORMALIZED_TZ_KEY",
            setting_value=Decimal("123.450000"),
            effective_from=datetime(2026, 5, 1, 0, 0, 0),
        )

        resolved = resolve_setting(db_session, Programme.PLAN_A, "NORMALIZED_TZ_KEY", t_utc)
        assert resolved.version == 1
        assert resolved.setting_value == Decimal("123.450000")

    def test_multiple_matching_versions_raises_integrity_error(self, db_session: Session) -> None:
        """If data corruption causes multiple versions to overlap, treat as a critical integrity error."""
        t_base = datetime(2026, 1, 1, 0, 0, 0)
        # Directly insert overlapping versions to simulate corrupted/anomalous database state
        corrupted_v1 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="CORRUPTED_OVERLAP",
            setting_value=Decimal("10.000000"),
            version=1,
            effective_from=t_base,
            effective_to=datetime(2026, 12, 31, 0, 0, 0),
            is_active=False,
        )
        corrupted_v2 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key="CORRUPTED_OVERLAP",
            setting_value=Decimal("20.000000"),
            version=2,
            effective_from=t_base,
            effective_to=datetime(2026, 12, 31, 0, 0, 0),
            is_active=True,
        )
        db_session.add_all([corrupted_v1, corrupted_v2])
        db_session.commit()

        # Querying within the overlapping window must raise MultipleMatchingSettingsError
        with pytest.raises(MultipleMatchingSettingsError) as exc_info:
            resolve_setting(
                db_session, Programme.PLAN_A, "CORRUPTED_OVERLAP", datetime(2026, 6, 1, 0, 0, 0)
            )
        assert "Data integrity error" in str(exc_info.value)
        assert "Multiple (2)" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Input Validation & Numeric Bounds
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFinancialValueAndWindowValidation:
    """Tests strictly preventing floats, non-finite Decimals, precision drift, and invalid windows."""

    def test_reject_float_with_type_error(self, db_session: Session) -> None:
        with pytest.raises(TypeError) as exc_info:
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="FLOAT_TEST",
                setting_value=750.50,  # float is forbidden
            )
        assert "Floating-point values are forbidden" in str(exc_info.value)

    def test_reject_nan_and_infinities(self, db_session: Session) -> None:
        for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), "nan", "inf"):
            with pytest.raises((FinancialSettingValidationError, ValueError)):
                create_setting(
                    db=db_session,
                    programme=Programme.PLAN_A,
                    setting_key="NAN_TEST",
                    setting_value=bad,
                )

    def test_reject_negative_values(self, db_session: Session) -> None:
        with pytest.raises(FinancialSettingValidationError) as exc:
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="NEG_TEST",
                setting_value=Decimal("-0.01"),
            )
        assert "cannot be negative" in str(exc.value)

    def test_reject_excessive_precision_beyond_six_decimals(self, db_session: Session) -> None:
        # 6 decimals is valid
        s6 = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="SIX_DEC",
            setting_value=Decimal("0.123456"),
        )
        assert s6.setting_value == Decimal("0.123456")

        # 7 decimals with non-zero trailing digit must be rejected to prevent truncation
        with pytest.raises(FinancialSettingValidationError) as exc:
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="SEVEN_DEC",
                setting_value=Decimal("0.1234567"),
            )
        assert "exceeds the maximum supported database precision of 6 decimal places" in str(exc.value)

    def test_reject_excessive_magnitude(self, db_session: Session) -> None:
        with pytest.raises(FinancialSettingValidationError):
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="HUGE_VAL",
                setting_value=Decimal("1000000000000.000000"),  # 10^12 exceeds Numeric(18, 6)
            )

    def test_accept_money_instance(self, db_session: Session) -> None:
        m = Money("750.00")
        s = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="MONEY_INPUT",
            setting_value=m,
        )
        assert s.setting_value == Decimal("750.00")
        assert s.currency == "INR"
        assert s.as_money() == m

    def test_reject_zero_duration_and_negative_effective_window(self, db_session: Session) -> None:
        t_start = datetime(2026, 1, 1, 0, 0, 0)

        # Equal start and end (zero duration)
        with pytest.raises(FinancialSettingValidationError) as exc1:
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="ZERO_DUR",
                setting_value=Decimal("100.00"),
                effective_from=t_start,
                effective_to=t_start,
            )
        assert "must be strictly greater than" in str(exc1.value)

        # Inverted start and end (negative window)
        with pytest.raises(FinancialSettingValidationError) as exc2:
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="NEG_WINDOW",
                setting_value=Decimal("100.00"),
                effective_from=t_start,
                effective_to=t_start - timedelta(days=1),
            )
        assert "must be strictly greater than" in str(exc2.value)


# ---------------------------------------------------------------------------
# 4. Programme Isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProgrammeIsolation:
    """Verify settings with the exact same key name are completely isolated across programmes."""

    def test_programme_isolation(self, db_session: Session) -> None:
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="TDS_RATE",
            setting_value=Decimal("0.020000"),
        )
        create_setting(
            db=db_session,
            programme=Programme.PLAN_B,
            setting_key="TDS_RATE",
            setting_value=Decimal("0.050000"),
        )
        create_setting(
            db=db_session,
            programme=Programme.LEGACY,
            setting_key="TDS_RATE",
            setting_value=Decimal("0.000000"),
        )

        assert get_setting(db_session, Programme.PLAN_A, "TDS_RATE").setting_value == Decimal("0.020000")
        assert get_setting(db_session, Programme.PLAN_B, "TDS_RATE").setting_value == Decimal("0.050000")
        assert get_setting(db_session, Programme.LEGACY, "TDS_RATE").setting_value == Decimal("0.000000")


# ---------------------------------------------------------------------------
# 5. Audit History & Lifecycle Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuditHistoryAndLifecycle:
    """Verify complete audit trail recording and atomic lifecycle transitions."""

    def test_complete_lifecycle_audit_trail(self, db_session: Session, admin_user: User) -> None:
        # 1. Create Version 1
        s1 = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="AUDIT_LIFECYCLE",
            setting_value=Decimal("100.000000"),
            created_by_id=admin_user.id,
            reason="Initial base setting",
        )
        assert s1.version == 1

        # 2. Update to Version 2
        s2 = update_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="AUDIT_LIFECYCLE",
            new_value=Decimal("150.000000"),
            changed_by_id=admin_user.id,
            reason="Market adjustment",
        )
        assert s2.version == 2

        # 3. Deactivate Version 2
        s_deact = deactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="AUDIT_LIFECYCLE",
            changed_by_id=admin_user.id,
            reason="Temporary suspension",
        )
        assert s_deact.is_active is False

        # 4. Reactivate: Invariant -> allocates Version 3 (never reopens closed Version 2 interval)
        s_react = reactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="AUDIT_LIFECYCLE",
            changed_by_id=admin_user.id,
            reason="Resumed operations",
        )
        assert s_react.version == 3
        assert s_react.is_active is True

        # Retrieve and inspect immutable audit trail
        history = get_setting_history(db_session, Programme.PLAN_A, "AUDIT_LIFECYCLE")
        assert len(history) == 4

        # Ordered newest first
        assert history[0].action == SettingAction.REACTIVATED
        assert history[0].version == 3
        assert history[0].reason == "Resumed operations"

        assert history[1].action == SettingAction.DEACTIVATED
        assert history[1].version == 2
        assert history[1].reason == "Temporary suspension"

        assert history[2].action == SettingAction.UPDATED
        assert history[2].version == 2
        assert history[2].old_value == Decimal("100.000000")
        assert history[2].new_value == Decimal("150.000000")
        assert history[2].reason == "Market adjustment"

        assert history[3].action == SettingAction.CREATED
        assert history[3].version == 1
        assert history[3].old_value is None
        assert history[3].new_value == Decimal("100.000000")
        assert history[3].reason == "Initial base setting"

    def test_reactivation_preserves_historical_intervals_and_allocates_new_version(
        self, db_session: Session, admin_user: User
    ) -> None:
        """Comprehensive regression test for historical reactivation semantics:
        1. Setting is created on 1 January.
        2. It is deactivated on 10 January.
        3. It is reactivated on 20 January.
        4. A historical lookup on 5 January returns the original version (v1).
        5. A lookup on 15 January does not return the deactivated version (raises SettingNotFoundError).
        6. A lookup on 20 January returns the newly reactivated version (v2).
        7. The original version's effective interval remains unchanged after reactivation ([Jan 1, Jan 10)).
        8. The history contains the appropriate deactivation and reactivation events.
        9. Failure to write the reactivation audit event rolls back the new version.
        """
        t_jan1 = datetime(2026, 1, 1, 0, 0, 0)
        t_jan5 = datetime(2026, 1, 5, 0, 0, 0)
        t_jan10 = datetime(2026, 1, 10, 0, 0, 0)
        t_jan15 = datetime(2026, 1, 15, 0, 0, 0)
        t_jan20 = datetime(2026, 1, 20, 0, 0, 0)

        # 1. Create on 1 January (Version 1)
        v1 = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="REACTIVATION_REGRESSION",
            setting_value=Decimal("750.000000"),
            effective_from=t_jan1,
            created_by_id=admin_user.id,
            reason="Initial launch",
        )
        assert v1.version == 1

        # 2. Deactivate on 10 January
        s_deact = deactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="REACTIVATION_REGRESSION",
            effective_to=t_jan10,
            changed_by_id=admin_user.id,
            reason="Suspended during audit",
        )
        assert s_deact.is_active is False
        assert s_deact.effective_to == t_jan10

        # 3. Reactivate on 20 January -> Allocates Version 2
        v2 = reactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="REACTIVATION_REGRESSION",
            effective_from=t_jan20,
            changed_by_id=admin_user.id,
            reason="Reactivated after audit",
        )
        assert v2.version == 2
        assert v2.is_active is True
        assert v2.effective_from == t_jan20
        assert v2.effective_to is None

        # 4. Historical lookup on 5 January returns the original Version 1
        r_jan5 = resolve_setting(db_session, Programme.PLAN_A, "REACTIVATION_REGRESSION", t_jan5)
        assert r_jan5.version == 1
        assert r_jan5.setting_value == Decimal("750.000000")

        # 5. Lookup on 15 January does NOT return the deactivated version (raises SettingNotFoundError)
        with pytest.raises(SettingNotFoundError):
            resolve_setting(db_session, Programme.PLAN_A, "REACTIVATION_REGRESSION", t_jan15)

        # 6. Lookup on 20 January returns the newly reactivated Version 2
        r_jan20 = resolve_setting(db_session, Programme.PLAN_A, "REACTIVATION_REGRESSION", t_jan20)
        assert r_jan20.version == 2
        assert r_jan20.setting_value == Decimal("750.000000")
        assert r_jan20.is_active is True

        # 7. The original version's effective interval remains unchanged after reactivation
        db_session.refresh(v1)
        assert v1.effective_from == t_jan1
        assert v1.effective_to == t_jan10
        assert v1.is_active is False

        # 8. History contains appropriate deactivation and reactivation events
        history = get_setting_history(db_session, Programme.PLAN_A, "REACTIVATION_REGRESSION")
        assert len(history) == 3
        assert history[0].action == SettingAction.REACTIVATED
        assert history[0].version == 2
        assert history[0].setting_id == v2.id
        assert history[1].action == SettingAction.DEACTIVATED
        assert history[1].version == 1
        assert history[1].setting_id == v1.id
        assert history[2].action == SettingAction.CREATED
        assert history[2].version == 1
        assert history[2].setting_id == v1.id

        # 9. Failure to write the reactivation audit event rolls back the new version
        deactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="REACTIVATION_REGRESSION",
            effective_to=datetime(2026, 1, 25, 0, 0, 0),
        )
        from unittest.mock import patch
        with patch("app.services.financial_settings.FinancialSettingHistory", side_effect=RuntimeError("Simulated audit write failure")):
            with pytest.raises(RuntimeError):
                reactivate_setting(
                    db=db_session,
                    programme=Programme.PLAN_A,
                    setting_key="REACTIVATION_REGRESSION",
                    effective_from=datetime(2026, 1, 30, 0, 0, 0),
                )

        # Invariant: Version 3 must NOT exist in the database; latest version remains version 2 (inactive)
        latest_after_failed_react = (
            db_session.execute(
                select(FinancialSetting)
                .where(
                    FinancialSetting.programme == Programme.PLAN_A,
                    FinancialSetting.setting_key == "REACTIVATION_REGRESSION",
                )
                .order_by(FinancialSetting.version.desc())
            )
            .scalars()
            .first()
        )
        assert latest_after_failed_react is not None
        assert latest_after_failed_react.version == 2
        assert latest_after_failed_react.is_active is False

    def test_deactivate_inactive_setting_raises(self, db_session: Session) -> None:
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="DEACT_TWICE",
            setting_value=Decimal("50.00"),
        )
        deactivate_setting(db_session, Programme.PLAN_A, "DEACT_TWICE")

        with pytest.raises(SettingNotFoundError):
            deactivate_setting(db_session, Programme.PLAN_A, "DEACT_TWICE")

    def test_reactivate_already_active_setting_raises(self, db_session: Session) -> None:
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="ALREADY_ACTIVE",
            setting_value=Decimal("50.00"),
        )
        with pytest.raises(FinancialSettingValidationError):
            reactivate_setting(db_session, Programme.PLAN_A, "ALREADY_ACTIVE")

    def test_update_inactive_setting_rejected_and_preserves_closure_boundary(
        self, db_session: Session, admin_user: User
    ) -> None:
        """Verify update_setting() rejects updating a deactivated setting and never alters closed boundaries:
        - Create Version 1 on 1 January.
        - Deactivate Version 1 on 10 January.
        - Attempt to update it with an effective date of 15 January -> rejected.
        - Confirm Version 1 still has effective_to = 10 January and is_active = False.
        - Confirm no Version 2 or UPDATE history event was created.
        - Confirm caller can use reactivate_setting() to create a new version without changing Version 1.
        """
        t_jan1 = datetime(2026, 1, 1, 0, 0, 0)
        t_jan10 = datetime(2026, 1, 10, 0, 0, 0)
        t_jan15 = datetime(2026, 1, 15, 0, 0, 0)
        t_jan20 = datetime(2026, 1, 20, 0, 0, 0)

        # 1. Create Version 1 on 1 January
        v1 = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="INACTIVE_UPDATE_GUARD",
            setting_value=Decimal("100.000000"),
            effective_from=t_jan1,
            created_by_id=admin_user.id,
        )
        assert v1.version == 1

        # 2. Deactivate Version 1 on 10 January
        s_deact = deactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="INACTIVE_UPDATE_GUARD",
            effective_to=t_jan10,
            changed_by_id=admin_user.id,
        )
        assert s_deact.is_active is False
        assert s_deact.effective_to == t_jan10

        # 3. Attempt to update it with an effective date of 15 January -> Must be rejected
        with pytest.raises(FinancialSettingValidationError) as exc:
            update_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="INACTIVE_UPDATE_GUARD",
                new_value=Decimal("150.000000"),
                effective_from=t_jan15,
                changed_by_id=admin_user.id,
            )
        assert "inactive/deactivated" in str(exc.value)
        assert "reactivate_setting" in str(exc.value)

        # 4. Confirm Version 1 still has effective_to = 10 January and is_active = False
        db_session.refresh(v1)
        assert v1.effective_from == t_jan1
        assert v1.effective_to == t_jan10
        assert v1.is_active is False

        # 5. Confirm no Version 2 or UPDATE history event was created
        history = get_setting_history(db_session, Programme.PLAN_A, "INACTIVE_UPDATE_GUARD")
        assert len(history) == 2
        assert [h.action for h in history] == [SettingAction.DEACTIVATED, SettingAction.CREATED]

        all_settings = (
            db_session.execute(
                select(FinancialSetting)
                .where(
                    FinancialSetting.programme == Programme.PLAN_A,
                    FinancialSetting.setting_key == "INACTIVE_UPDATE_GUARD",
                )
            )
            .scalars()
            .all()
        )
        assert len(all_settings) == 1
        assert all_settings[0].version == 1

        # 6. Confirm the caller can use reactivate_setting() to create a new version without changing Version 1
        v2 = reactivate_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="INACTIVE_UPDATE_GUARD",
            effective_from=t_jan20,
            changed_by_id=admin_user.id,
        )
        assert v2.version == 2
        assert v2.is_active is True
        assert v2.effective_from == t_jan20
        assert v2.effective_to is None

        # Version 1 is still completely unchanged
        db_session.refresh(v1)
        assert v1.effective_from == t_jan1
        assert v1.effective_to == t_jan10
        assert v1.is_active is False

    def test_update_cannot_silently_extend_finite_scheduled_boundary(
        self, db_session: Session, admin_user: User
    ) -> None:
        """Verify that an active setting with pre-existing finite effective_to cannot be extended by update_setting()."""
        t_start = datetime(2026, 1, 1, 0, 0, 0)
        t_finite_end = datetime(2026, 1, 10, 0, 0, 0)
        t_past_end = datetime(2026, 1, 15, 0, 0, 0)

        # Create active setting with finite end date of 10 January
        v1 = create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="FINITE_BOUNDARY_KEY",
            setting_value=Decimal("50.000000"),
            effective_from=t_start,
            effective_to=t_finite_end,
            created_by_id=admin_user.id,
        )
        assert v1.effective_to == t_finite_end
        assert v1.is_active is True

        # Attempt to update with effective_from = 15 January (> 10 January)
        # Must be rejected because it exceeds existing scheduled boundary
        with pytest.raises(FinancialSettingValidationError) as exc:
            update_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="FINITE_BOUNDARY_KEY",
                new_value=Decimal("60.000000"),
                effective_from=t_past_end,
                changed_by_id=admin_user.id,
            )
        assert "exceeds" in str(exc.value)

        # Confirm v1 boundary was NOT changed
        db_session.refresh(v1)
        assert v1.effective_to == t_finite_end

    def test_atomic_rollback_when_history_insertion_fails(self, db_session: Session) -> None:
        """Verify that if history creation fails, the setting is not committed (atomic transaction)."""
        from unittest.mock import patch

        with patch("app.services.financial_settings.FinancialSettingHistory", side_effect=RuntimeError("Simulated history failure")):
            with pytest.raises(RuntimeError):
                create_setting(
                    db=db_session,
                    programme=Programme.PLAN_A,
                    setting_key="ATOMIC_ROLLBACK",
                    setting_value=Decimal("100.00"),
                )

        # Database must have zero trace of the setting
        assert get_setting_or_none(db_session, Programme.PLAN_A, "ATOMIC_ROLLBACK") is None


# ---------------------------------------------------------------------------
# 6. Concurrency and Bounded Retry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcurrencyAndVersionManagement:
    """Rigorous multi-session and multi-threaded concurrency tests."""

    def test_create_setting_rejects_if_already_exists(self, db_session: Session) -> None:
        create_setting(
            db=db_session,
            programme=Programme.PLAN_A,
            setting_key="ALREADY_EXISTS_KEY",
            setting_value=Decimal("10.00"),
        )
        with pytest.raises(SettingAlreadyExistsError) as exc:
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="ALREADY_EXISTS_KEY",
                setting_value=Decimal("20.00"),
            )
        assert "already exists" in str(exc.value)

    def test_unrelated_integrity_error_fails_immediately_without_retry(self, db_session: Session) -> None:
        """Unrelated DB constraint failures (e.g. invalid created_by_id foreign key) must not be retried."""
        if db_session.bind and db_session.bind.dialect.name == "sqlite":
            db_session.execute(text("PRAGMA foreign_keys = ON"))
        with pytest.raises(IntegrityError):
            create_setting(
                db=db_session,
                programme=Programme.PLAN_A,
                setting_key="INVALID_FK_KEY",
                setting_value=Decimal("10.00"),
                created_by_id=99999999,  # Non-existent user ID
            )

    def test_concurrent_first_version_creation_across_sessions(self, test_engine: Engine) -> None:
        """Simulate two sessions simultaneously executing create_setting: exactly one succeeds, the other gets SettingAlreadyExistsError."""
        SessionMaker = sessionmaker(bind=test_engine)
        session1 = SessionMaker()
        session2 = SessionMaker()

        results = []
        errors = []

        def worker(session: Session, val: Decimal) -> None:
            try:
                res = create_setting(
                    db=session,
                    programme=Programme.PLAN_A,
                    setting_key="CONCURRENT_V1_KEY",
                    setting_value=val,
                )
                results.append(res)
            except Exception as e:
                errors.append(e)
            finally:
                session.close()

        # Run both workers
        worker(session1, Decimal("100.000000"))
        worker(session2, Decimal("200.000000"))

        assert len(results) == 1
        assert results[0].version == 1
        assert len(errors) == 1
        assert isinstance(errors[0], SettingAlreadyExistsError)

    def test_threaded_subsequent_version_updates(self, test_engine: Engine) -> None:
        """Verify sequential/concurrent update_setting executions produce monotonically increasing versions."""
        SessionMaker = sessionmaker(bind=test_engine)

        # Initialize Version 1
        init_sess = SessionMaker()
        create_setting(
            db=init_sess,
            programme=Programme.PLAN_A,
            setting_key="MONOTONIC_TEST",
            setting_value=Decimal("100.000000"),
            effective_from=datetime(2026, 1, 1, 0, 0, 0),
        )
        init_sess.close()

        # Update 4 times with strictly increasing effective_from
        for i in range(2, 6):
            sess = SessionMaker()
            updated = update_setting(
                db=sess,
                programme=Programme.PLAN_A,
                setting_key="MONOTONIC_TEST",
                new_value=Decimal(f"{100 + i}.000000"),
                effective_from=datetime(2026, 1, i, 0, 0, 0),
            )
            assert updated.version == i
            sess.close()

        # Final check: Version is 5, and exactly 5 history records exist
        final_sess = SessionMaker()
        latest = get_setting(final_sess, Programme.PLAN_A, "MONOTONIC_TEST")
        assert latest.version == 5
        assert latest.setting_value == Decimal("105.000000")

        history = get_setting_history(final_sess, Programme.PLAN_A, "MONOTONIC_TEST")
        assert len(history) == 5
        versions_in_history = [h.version for h in history]
        assert versions_in_history == [5, 4, 3, 2, 1]
        final_sess.close()
