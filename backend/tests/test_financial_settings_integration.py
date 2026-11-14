"""End-to-end integration and reconciliation tests for WP-2 Step 2.4.

Covers:
  1. Idempotent baseline seeding of canonical financial settings on an empty database.
  2. Idempotent re-execution (zero duplicate settings, zero duplicate history, zero version bumps).
  3. Historical/inactive version safety (never overwriting, closing, or re-inserting v1 when any version exists).
  4. Savepoint atomicity and failure recovery (rolling back partial seed writes while preserving caller work).
  5. PA-24 Unit Allocation accounting reconciliation:
     - Seven actual allocation components sum to exactly Rs. 3,300.00.
     - Residual company balance is exactly Rs. 699.00 (not an allocation component).
     - Product price is Rs. 3,999.00 (3,300.00 + 699.00 = 3,999.00).
  6. Plan A integrated commission split with Money utility (750 -> 35 / 15 / 700).
  7. Plan B integrated direct (500 -> 0 / 0 / 500) and generation (50 -> 0 / 0 / 50) splits under BR-B2 defaults.
  8. Full baseline data seeding pipeline integration (Admin + QueueControl + Financial Settings).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from unittest.mock import patch
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import CommissionSplit, Money, calculate_commission_split
from app.core.seed import seed_baseline_data
from app.models.enums import Programme, SettingAction, UserRole
from app.models.financial_settings import FinancialSetting, FinancialSettingHistory
from app.models.user import User
from app.services.financial_settings import (
    CANONICAL_SETTINGS,
    FinancialSettingsService,
    SettingKey,
    has_setting,
    resolve_setting,
    seed_financial_settings,
)


@pytest.mark.unit
class TestFinancialSettingsCanonicalSeed:
    """Tests for idempotent canonical settings seeding and transaction boundaries."""

    def test_seed_canonical_settings_empty_database(self, db_session: Session) -> None:
        """Verify seeding on an empty database creates all 14 canonical settings with Version 1 and audit history."""
        # Database starts with zero financial settings
        assert db_session.query(FinancialSetting).count() == 0
        assert db_session.query(FinancialSettingHistory).count() == 0

        res = seed_financial_settings(db_session)
        assert res["action"] == "created"
        assert res["created_count"] == 14
        assert res["skipped_count"] == 0
        assert len(res["created_keys"]) == 14

        # Verify exactly 14 records in financial_settings
        settings_count = db_session.query(FinancialSetting).count()
        assert settings_count == 14

        # Verify exactly 14 records in financial_settings_history
        history_count = db_session.query(FinancialSettingHistory).count()
        assert history_count == 14

        # Every seeded setting must be active, version 1, with matching history
        all_settings = db_session.query(FinancialSetting).all()
        for s in all_settings:
            assert s.version == 1
            assert s.is_active is True
            assert s.effective_to is None
            assert len(s.history) == 1
            h = s.history[0]
            assert h.action == SettingAction.CREATED
            assert h.old_value is None
            assert h.new_value == s.setting_value
            assert h.version == 1
            assert h.reason == "Initial baseline seed"

    def test_seed_canonical_settings_idempotent_on_repeat(self, db_session: Session) -> None:
        """Verify running seed_financial_settings repeatedly creates zero duplicates and bumps zero versions."""
        # First execution
        first_res = seed_financial_settings(db_session)
        assert first_res["action"] == "created"
        assert first_res["created_count"] == 14

        # Second execution
        second_res = seed_financial_settings(db_session)
        assert second_res["action"] == "skipped"
        assert second_res["created_count"] == 0
        assert second_res["skipped_count"] == 14
        assert len(second_res["skipped_keys"]) == 14

        # Third execution
        third_res = seed_financial_settings(db_session)
        assert third_res["action"] == "skipped"
        assert third_res["created_count"] == 0
        assert third_res["skipped_count"] == 14

        # Totals remain strictly 14 settings and 14 history rows
        assert db_session.query(FinancialSetting).count() == 14
        assert db_session.query(FinancialSettingHistory).count() == 14

        # Confirm all settings remain version 1
        versions = [s.version for s in db_session.query(FinancialSetting).all()]
        assert versions == [1] * 14

    def test_seed_skips_inactive_or_historical_versions_without_creating_v1(
        self, db_session: Session
    ) -> None:
        """Historical version safety: if ANY version exists, seed must NOT insert Version 1 or mutate state."""
        # Pre-seed a customized inactive Version 1 and an active Version 2 for Plan A COMMISSION_GROSS
        custom_v1 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key=SettingKey.COMMISSION_GROSS,
            setting_value=Decimal("700.000000"),
            currency="INR",
            version=1,
            effective_from=datetime(2025, 1, 1, 0, 0, 0),
            effective_to=datetime(2026, 1, 1, 0, 0, 0),
            is_active=False,
        )
        custom_v2 = FinancialSetting(
            programme=Programme.PLAN_A,
            setting_key=SettingKey.COMMISSION_GROSS,
            setting_value=Decimal("750.000000"),
            currency="INR",
            version=2,
            effective_from=datetime(2026, 1, 1, 0, 0, 0),
            effective_to=None,
            is_active=True,
        )
        # Pre-seed a deactivated (inactive) setting for Plan B DIRECT_COMMISSION_GROSS
        custom_pb_v1 = FinancialSetting(
            programme=Programme.PLAN_B,
            setting_key=SettingKey.DIRECT_COMMISSION_GROSS,
            setting_value=Decimal("500.000000"),
            currency="INR",
            version=1,
            effective_from=datetime(2026, 1, 1, 0, 0, 0),
            effective_to=datetime(2026, 2, 1, 0, 0, 0),
            is_active=False,
        )
        db_session.add_all([custom_v1, custom_v2, custom_pb_v1])
        db_session.flush()

        assert has_setting(db_session, Programme.PLAN_A, SettingKey.COMMISSION_GROSS) is True
        assert has_setting(db_session, Programme.PLAN_B, SettingKey.DIRECT_COMMISSION_GROSS) is True

        # Run baseline seeding
        res = seed_financial_settings(db_session)

        # 2 existing settings were skipped, 12 new settings were seeded
        assert res["created_count"] == 12
        assert res["skipped_count"] == 2
        assert f"PLAN_A:{SettingKey.COMMISSION_GROSS}" in res["skipped_keys"]
        assert f"PLAN_B:{SettingKey.DIRECT_COMMISSION_GROSS}" in res["skipped_keys"]

        # Confirm Plan A COMMISSION_GROSS still has exactly 2 versions (v1 and v2), no v3 was created
        pa_comm_versions = (
            db_session.query(FinancialSetting)
            .filter_by(programme=Programme.PLAN_A, setting_key=SettingKey.COMMISSION_GROSS)
            .order_by(FinancialSetting.version.asc())
            .all()
        )
        assert len(pa_comm_versions) == 2
        assert pa_comm_versions[0].version == 1
        assert pa_comm_versions[0].setting_value == Decimal("700.000000")
        assert pa_comm_versions[1].version == 2
        assert pa_comm_versions[1].setting_value == Decimal("750.000000")

        # Confirm Plan B DIRECT_COMMISSION_GROSS remains inactive; was NOT reactivated or overwritten
        pb_direct = (
            db_session.query(FinancialSetting)
            .filter_by(programme=Programme.PLAN_B, setting_key=SettingKey.DIRECT_COMMISSION_GROSS)
            .all()
        )
        assert len(pb_direct) == 1
        assert pb_direct[0].version == 1
        assert pb_direct[0].is_active is False
        assert pb_direct[0].effective_to == datetime(2026, 2, 1, 0, 0, 0)

    def test_seed_savepoint_atomic_rollback_on_failure(self, db_session: Session) -> None:
        """Verify savepoint atomicity: failure during seeding rolls back all seed writes while preserving caller work."""
        # 1. Caller does prior uncommitted work in the same session
        caller_user = User(
            full_name="Caller Prior User",
            phone="9988776655",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db_session.add(caller_user)
        db_session.flush()
        caller_user_id = caller_user.id
        assert caller_user_id is not None

        # 2. Inject a simulated failure on the 3rd setting insertion during seeding
        original_flush = db_session.flush
        flush_call_count = 0

        def failing_flush(*args, **kwargs):
            nonlocal flush_call_count
            flush_call_count += 1
            # Setting 1 (setting + history = 2 flushes), Setting 2 (flushes 3 & 4), fail on 5
            if flush_call_count >= 5:
                raise RuntimeError("Simulated transient database write error during seeding")
            return original_flush(*args, **kwargs)

        with patch.object(db_session, "flush", side_effect=failing_flush):
            with pytest.raises(RuntimeError, match="Simulated transient database write error"):
                seed_financial_settings(db_session, created_by_id=caller_user_id)

        # 3. Assert all seed writes and history entries rolled back to the savepoint
        assert db_session.query(FinancialSetting).count() == 0
        assert db_session.query(FinancialSettingHistory).count() == 0

        # 4. Assert prior caller work is preserved intact in the session
        persisted_caller = db_session.get(User, caller_user_id)
        assert persisted_caller is not None
        assert persisted_caller.full_name == "Caller Prior User"


@pytest.mark.unit
class TestPA24UnitAllocationReconciliation:
    """Authoritative validation of PA-24 Unit Allocation breakdown and company residual balance."""

    def test_pa24_unit_allocation_reconciliation(self, db_session: Session) -> None:
        """Verify PA-24 allocation accounting:

        PRD Plan A §3 (p.3) Invariants:
          - Seven actual allocation components:
            1. Product import cost:    Rs. 1,500.00
            2. GST reserve:            Rs.   400.00
            3. Packing and courier:    Rs.   150.00
            4. Customer cashback:      Rs.   250.00
            5. Gross commission pool:  Rs.   750.00
            6. Gift and achievement:   Rs.   150.00
            7. Office and staff:       Rs.   100.00
          - Sum of seven components:   Rs. 3,300.00
          - Product retail price:      Rs. 3,999.00
          - Residual company balance:  Rs.   699.00  (3,999 - 3,300 = 699)
          - Additive identity:         3,300.00 + 699.00 = 3,999.00

        The residual Rs. 699 is strictly the remaining company balance, NOT an allocation component.
        """
        seed_financial_settings(db_session)

        # Retrieve the seven allocation components from the database
        # Test both resolve_setting (historical resolution) and get_setting (active retrieval)
        t_query = datetime(2026, 1, 15, 0, 0, 0)
        import_cost = resolve_setting(db_session, Programme.PLAN_A, SettingKey.ALLOC_PRODUCT_IMPORT, t_query)
        gst_reserve = resolve_setting(db_session, Programme.PLAN_A, SettingKey.ALLOC_GST_RESERVE, t_query)
        courier_exp = resolve_setting(db_session, Programme.PLAN_A, SettingKey.ALLOC_PACKING_COURIER, t_query)
        cashback_val = resolve_setting(db_session, Programme.PLAN_A, SettingKey.CASHBACK_PER_UNIT, t_query)
        comm_gross = resolve_setting(db_session, Programme.PLAN_A, SettingKey.COMMISSION_GROSS, t_query)
        gift_fund = resolve_setting(db_session, Programme.PLAN_A, SettingKey.ALLOC_GIFT_FUND, t_query)
        staff_exp = resolve_setting(db_session, Programme.PLAN_A, SettingKey.ALLOC_OFFICE_STAFF, t_query)

        # 1. Assert each component has its exact PRD-mandated value
        assert import_cost.setting_value == Decimal("1500.000000")
        assert gst_reserve.setting_value == Decimal("400.000000")
        assert courier_exp.setting_value == Decimal("150.000000")
        assert cashback_val.setting_value == Decimal("250.000000")
        assert comm_gross.setting_value == Decimal("750.000000")
        assert gift_fund.setting_value == Decimal("150.000000")
        assert staff_exp.setting_value == Decimal("100.000000")

        # 2. Convert to Money value objects
        m_import = import_cost.as_money()
        m_gst = gst_reserve.as_money()
        m_courier = courier_exp.as_money()
        m_cashback = cashback_val.as_money()
        m_comm = comm_gross.as_money()
        m_gift = gift_fund.as_money()
        m_staff = staff_exp.as_money()

        # 3. Seven allocation components sum to exactly Rs. 3,300.00
        allocation_components = [
            m_import,
            m_gst,
            m_courier,
            m_cashback,
            m_comm,
            m_gift,
            m_staff,
        ]
        assert len(allocation_components) == 7

        total_allocations = sum(allocation_components, Money("0.00", "INR"))
        assert total_allocations == Money("3300.00", "INR")
        assert total_allocations.amount == Decimal("3300.00")

        # 4. Product price is Rs. 3,999.00
        product_price = Money("3999.00", "INR")

        # 5. Residual company balance: 3,999.00 - 3,300.00 = 699.00
        residual_company_balance = product_price - total_allocations
        assert residual_company_balance == Money("699.00", "INR")
        assert residual_company_balance.amount == Decimal("699.00")

        # 6. Conservation check: Allocations + Residual == Product Price
        assert total_allocations + residual_company_balance == product_price

        # 7. Explicit negative assertion: Rs. 699 is NOT in the allocation components list
        assert residual_company_balance not in allocation_components


@pytest.mark.unit
class TestEndToEndCommissionIntegration:
    """Tests verifying Money utility and CommissionSplit using database-resolved settings."""

    def test_plan_a_integrated_commission_split_with_money(self, db_session: Session) -> None:
        """Verify Plan A benchmark commission split (750 -> 35 / 15 / 700) using database-resolved settings."""
        seed_financial_settings(db_session)

        # Resolve rates and gross pool from database as of transaction time
        t_txn = datetime(2026, 1, 15, 12, 0, 0)
        s_gross = resolve_setting(db_session, Programme.PLAN_A, SettingKey.COMMISSION_GROSS, t_txn)
        s_op = resolve_setting(db_session, Programme.PLAN_A, SettingKey.OP_COST_RATE, t_txn)
        s_tds = resolve_setting(db_session, Programme.PLAN_A, SettingKey.TDS_RATE, t_txn)

        gross_money = s_gross.as_money()
        op_rate = s_op.as_rate()
        tds_rate = s_tds.as_rate()

        assert gross_money == Money("750.00", "INR")
        assert op_rate == Decimal("0.046667")
        assert tds_rate == Decimal("0.020000")

        # Execute integrated split calculation
        split = calculate_commission_split(
            gross=gross_money,
            op_cost_rate=op_rate,
            tds_rate=tds_rate,
        )

        assert isinstance(split, CommissionSplit)
        assert split.gross == Money("750.00", "INR")
        # 750 * 0.046667 = 35.00025 -> rounded to 35.00
        assert split.op_cost == Money("35.00", "INR")
        # 750 * 0.02 = 15.00
        assert split.tds == Money("15.00", "INR")
        # 750 - 35 - 15 = 700.00
        assert split.net == Money("700.00", "INR")

        # Invariants: conservation and exact paise precision
        assert split.gross == split.op_cost + split.tds + split.net
        assert split.gross.amount == Decimal("750.00")
        assert split.op_cost.amount == Decimal("35.00")
        assert split.tds.amount == Decimal("15.00")
        assert split.net.amount == Decimal("700.00")

    def test_plan_b_integrated_commission_splits_with_money(self, db_session: Session) -> None:
        """Verify Plan B direct (500 -> 0 / 0 / 500) and generation (50 -> 0 / 0 / 50) splits under BR-B2 defaults."""
        seed_financial_settings(db_session)

        # Resolve Plan B settings from database as of transaction time
        t_txn = datetime(2026, 1, 15, 12, 0, 0)
        s_direct = resolve_setting(db_session, Programme.PLAN_B, SettingKey.DIRECT_COMMISSION_GROSS, t_txn)
        s_gen = resolve_setting(db_session, Programme.PLAN_B, SettingKey.GENERATION_COMMISSION_GROSS, t_txn)
        s_op = resolve_setting(db_session, Programme.PLAN_B, SettingKey.OP_COST_RATE, t_txn)
        s_tds = resolve_setting(db_session, Programme.PLAN_B, SettingKey.TDS_RATE, t_txn)

        # 1. Direct Commission (Rs. 500.00)
        direct_split = calculate_commission_split(
            gross=s_direct.as_money(),
            op_cost_rate=s_op.as_rate(),
            tds_rate=s_tds.as_rate(),
        )
        assert direct_split.gross == Money("500.00", "INR")
        assert direct_split.op_cost == Money("0.00", "INR")
        assert direct_split.tds == Money("0.00", "INR")
        assert direct_split.net == Money("500.00", "INR")
        assert direct_split.gross == direct_split.op_cost + direct_split.tds + direct_split.net

        # 2. Generation Commission (Rs. 50.00)
        gen_split = calculate_commission_split(
            gross=s_gen.as_money(),
            op_cost_rate=s_op.as_rate(),
            tds_rate=s_tds.as_rate(),
        )
        assert gen_split.gross == Money("50.00", "INR")
        assert gen_split.op_cost == Money("0.00", "INR")
        assert gen_split.tds == Money("0.00", "INR")
        assert gen_split.net == Money("50.00", "INR")
        assert gen_split.gross == gen_split.op_cost + gen_split.tds + gen_split.net


@pytest.mark.unit
class TestBaselineDataSeedingPipeline:
    """Test full baseline seed pipeline integration."""

    def test_seed_baseline_data_integration(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify seed_baseline_data() initializes Admin, QueueControl, and Financial Settings together."""
        monkeypatch.setenv("ADMIN_NAME", "Integration Admin")
        monkeypatch.setenv("ADMIN_PHONE", "+919876543210")
        monkeypatch.setenv("ADMIN_PASSWORD", "SuperSecureAdminPassword123!")

        summary = seed_baseline_data(db_session, include_product=False)

        assert "admin" in summary
        assert "queue_control" in summary
        assert "financial_settings" in summary

        fin_summary = summary["financial_settings"]
        assert fin_summary["action"] == "created"
        assert fin_summary["created_count"] == 14

        # Confirm admin ID is linked as created_by_id in financial settings
        admin_id = summary["admin"]["id"]
        assert admin_id is not None

        admin_user = db_session.get(User, admin_id)
        assert admin_user is not None
        assert admin_user.role == UserRole.ADMIN

        settings_with_admin = (
            db_session.query(FinancialSetting)
            .filter(FinancialSetting.created_by_id == admin_id)
            .all()
        )
        assert len(settings_with_admin) == 14
