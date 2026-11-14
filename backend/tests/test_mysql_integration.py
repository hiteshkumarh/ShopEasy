from decimal import Decimal
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import Engine

from app.models.user import User
from app.models.enums import UserRole
from app.models.wallet import Wallet
from app.models.enums import WalletType


@pytest.mark.mysql
def test_mysql_connection_and_database_name(mysql_engine: Engine) -> None:
    """Verify connection to the isolated MySQL 8 test database and assert safe test database name."""
    with mysql_engine.connect() as conn:
        result = conn.execute(text("SELECT DATABASE(), VERSION()")).fetchone()
        assert result is not None
        current_db = result[0]
        version = result[1]

        # Confirm target is an isolated test database, never production
        assert current_db.startswith("shopeasy_test_")
        assert current_db not in ("shopeasy_arya", "shopeasy_app", "shopeasy_dev", "sys", "mysql")
        assert version is not None


@pytest.mark.mysql
def test_mysql_crud_record_lifecycle(mysql_db_session: Session) -> None:
    """Verify record insertion and query retrieval using MySQL 8 test session."""
    test_phone = "+919999900001"
    test_referral = "REF_TEST_0001"
    user = User(
        phone=test_phone,
        full_name="MySQL Test User",
        password_hash="test_hashed_password",
        role=UserRole.CUSTOMER,
        referral_code=test_referral,
    )
    mysql_db_session.add(user)
    mysql_db_session.commit()

    fetched = mysql_db_session.query(User).filter_by(phone=test_phone).first()
    assert fetched is not None
    assert fetched.full_name == "MySQL Test User"
    assert fetched.role == UserRole.CUSTOMER
    assert fetched.referral_code == test_referral


@pytest.mark.mysql
def test_mysql_transaction_rollback(mysql_db_session: Session) -> None:
    """Verify uncommitted transactions are cleanly rolled back on MySQL 8."""
    test_phone = "+919999900002"
    user = User(
        phone=test_phone,
        full_name="Rollback Test User",
        password_hash="test_hashed_password",
        role=UserRole.CUSTOMER,
        referral_code="REF_TEST_0002",
    )
    mysql_db_session.add(user)
    mysql_db_session.flush()

    # Roll back transaction before commit
    mysql_db_session.rollback()

    fetched = mysql_db_session.query(User).filter_by(phone=test_phone).first()
    assert fetched is None


@pytest.mark.mysql
def test_mysql_foreign_key_enforcement(mysql_db_session: Session) -> None:
    """Verify MySQL 8 strictly enforces foreign key constraints."""
    # Attempt to insert a Wallet with a non-existent user_id (99999999)
    orphan_wallet = Wallet(
        user_id=99999999,
        wallet_type=WalletType.DIRECT_REFERRAL,
        balance=Decimal("0.00"),
    )
    mysql_db_session.add(orphan_wallet)
    with pytest.raises(IntegrityError):
        mysql_db_session.commit()
    mysql_db_session.rollback()


@pytest.mark.mysql
def test_mysql_financial_settings_version_uniqueness_enforcement(mysql_db_session: Session) -> None:
    """Verify MySQL 8 strictly enforces UNIQUE(programme, setting_key, version)."""
    from datetime import datetime
    from app.models.financial_settings import FinancialSetting
    from app.models.enums import Programme

    t_now = datetime(2026, 1, 1, 0, 0, 0)
    s1 = FinancialSetting(
        programme=Programme.PLAN_A,
        setting_key="TEST_MYSQL_RATE",
        setting_value=Decimal("0.050000"),
        version=1,
        effective_from=t_now,
    )
    mysql_db_session.add(s1)
    mysql_db_session.commit()

    s2 = FinancialSetting(
        programme=Programme.PLAN_A,
        setting_key="TEST_MYSQL_RATE",
        setting_value=Decimal("0.100000"),
        version=1,
        effective_from=t_now,
    )
    mysql_db_session.add(s2)
    with pytest.raises(IntegrityError):
        mysql_db_session.commit()
    mysql_db_session.rollback()


@pytest.mark.mysql
def test_mysql_financial_settings_concurrent_unique_constraint(mysql_engine: Engine) -> None:
    """Verify MySQL 8 rejects concurrent duplicate version 1 inserts across two distinct connections."""
    from datetime import datetime
    from sqlalchemy.orm import sessionmaker
    from app.models.financial_settings import FinancialSetting
    from app.models.enums import Programme

    SessionLocal = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    sess1 = SessionLocal()
    sess2 = SessionLocal()
    t_now = datetime(2026, 1, 1, 0, 0, 0)

    try:
        s1 = FinancialSetting(
            programme=Programme.PLAN_B,
            setting_key="CONCURRENT_KEY",
            setting_value=Decimal("100.000000"),
            version=1,
            effective_from=t_now,
        )
        s2 = FinancialSetting(
            programme=Programme.PLAN_B,
            setting_key="CONCURRENT_KEY",
            setting_value=Decimal("200.000000"),
            version=1,
            effective_from=t_now,
        )
        sess1.add(s1)
        sess2.add(s2)

        sess1.commit()
        with pytest.raises(IntegrityError):
            sess2.commit()
        sess2.rollback()
    finally:
        sess1.close()
        sess2.close()


@pytest.mark.mysql
def test_mysql_financial_settings_service_lifecycle_and_history(mysql_db_session: Session) -> None:
    """Verify FinancialSettingsService creates settings and audit history on MySQL 8."""
    from app.services.financial_settings import (
        create_setting,
        update_setting,
        resolve_setting,
        get_setting_history,
    )
    from app.models.enums import Programme, SettingAction
    from datetime import datetime

    t_v1 = datetime(2026, 1, 1, 0, 0, 0)
    t_v2 = datetime(2026, 2, 1, 0, 0, 0)

    s1 = create_setting(
        db=mysql_db_session,
        programme=Programme.PLAN_A,
        setting_key="MYSQL_SERVICE_TEST",
        setting_value=Decimal("750.000000"),
        effective_from=t_v1,
    )
    assert s1.version == 1

    s2 = update_setting(
        db=mysql_db_session,
        programme=Programme.PLAN_A,
        setting_key="MYSQL_SERVICE_TEST",
        new_value=Decimal("800.000000"),
        effective_from=t_v2,
    )
    assert s2.version == 2

    # Historical resolution
    past_resolved = resolve_setting(
        mysql_db_session, Programme.PLAN_A, "MYSQL_SERVICE_TEST", datetime(2026, 1, 15, 0, 0, 0)
    )
    assert past_resolved.version == 1
    assert past_resolved.setting_value == Decimal("750.000000")

    curr_resolved = resolve_setting(
        mysql_db_session, Programme.PLAN_A, "MYSQL_SERVICE_TEST", datetime(2026, 2, 15, 0, 0, 0)
    )
    assert curr_resolved.version == 2
    assert curr_resolved.setting_value == Decimal("800.000000")

    history = get_setting_history(mysql_db_session, Programme.PLAN_A, "MYSQL_SERVICE_TEST")
    assert len(history) == 2
    assert history[0].action == SettingAction.UPDATED
    assert history[1].action == SettingAction.CREATED


@pytest.mark.mysql
def test_mysql_seed_financial_settings_and_idempotency(mysql_db_session: Session) -> None:
    """Verify seed_financial_settings runs idempotently against real MySQL 8."""
    from app.services.financial_settings import seed_financial_settings
    from app.models.financial_settings import FinancialSetting, FinancialSettingHistory

    # Initial seeding on MySQL 8
    res1 = seed_financial_settings(mysql_db_session)
    mysql_db_session.commit()
    assert res1["action"] == "created"
    assert res1["created_count"] == 14
    assert res1["skipped_count"] == 0

    count_settings_1 = mysql_db_session.query(FinancialSetting).count()
    count_history_1 = mysql_db_session.query(FinancialSettingHistory).count()
    assert count_settings_1 >= 14
    assert count_history_1 >= 14

    # Second execution must be strictly idempotent
    res2 = seed_financial_settings(mysql_db_session)
    mysql_db_session.commit()
    assert res2["action"] == "skipped"
    assert res2["created_count"] == 0
    assert res2["skipped_count"] == 14

    count_settings_2 = mysql_db_session.query(FinancialSetting).count()
    count_history_2 = mysql_db_session.query(FinancialSettingHistory).count()
    assert count_settings_2 == count_settings_1
    assert count_history_2 == count_history_1


@pytest.mark.mysql
def test_mysql_pa24_allocation_and_commission_split(mysql_db_session: Session) -> None:
    """Verify PA-24 allocation reconciliation and commission split calculations against MySQL 8."""
    from datetime import datetime
    from app.core.money import Money, calculate_commission_split
    from app.models.enums import Programme
    from app.services.financial_settings import (
        SettingKey,
        resolve_setting,
        seed_financial_settings,
    )

    seed_financial_settings(mysql_db_session)
    mysql_db_session.commit()

    t_txn = datetime(2026, 1, 15, 0, 0, 0)

    # 1. PA-24 Unit Allocation Reconciliation on MySQL 8
    m_import = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.ALLOC_PRODUCT_IMPORT, t_txn).as_money()
    m_gst = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.ALLOC_GST_RESERVE, t_txn).as_money()
    m_courier = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.ALLOC_PACKING_COURIER, t_txn).as_money()
    m_cashback = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.CASHBACK_PER_UNIT, t_txn).as_money()
    m_comm = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.COMMISSION_GROSS, t_txn).as_money()
    m_gift = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.ALLOC_GIFT_FUND, t_txn).as_money()
    m_staff = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.ALLOC_OFFICE_STAFF, t_txn).as_money()

    seven_allocations = [m_import, m_gst, m_courier, m_cashback, m_comm, m_gift, m_staff]
    total_alloc = sum(seven_allocations, Money("0.00", "INR"))
    assert total_alloc == Money("3300.00", "INR")

    product_price = Money("3999.00", "INR")
    residual_company_balance = product_price - total_alloc
    assert residual_company_balance == Money("699.00", "INR")
    assert total_alloc + residual_company_balance == product_price
    assert residual_company_balance not in seven_allocations

    # 2. Plan A Commission Split on MySQL 8: 750 -> 35 / 15 / 700
    s_gross = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.COMMISSION_GROSS, t_txn)
    s_op = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.OP_COST_RATE, t_txn)
    s_tds = resolve_setting(mysql_db_session, Programme.PLAN_A, SettingKey.TDS_RATE, t_txn)

    pa_split = calculate_commission_split(
        gross=s_gross.as_money(),
        op_cost_rate=s_op.as_rate(),
        tds_rate=s_tds.as_rate(),
    )
    assert pa_split.gross == Money("750.00", "INR")
    assert pa_split.op_cost == Money("35.00", "INR")
    assert pa_split.tds == Money("15.00", "INR")
    assert pa_split.net == Money("700.00", "INR")
    assert pa_split.gross == pa_split.op_cost + pa_split.tds + pa_split.net

    # 3. Plan B Commission Split on MySQL 8: 500 -> 0 / 0 / 500, 50 -> 0 / 0 / 50
    pb_direct = resolve_setting(mysql_db_session, Programme.PLAN_B, SettingKey.DIRECT_COMMISSION_GROSS, t_txn)
    pb_gen = resolve_setting(mysql_db_session, Programme.PLAN_B, SettingKey.GENERATION_COMMISSION_GROSS, t_txn)
    pb_op = resolve_setting(mysql_db_session, Programme.PLAN_B, SettingKey.OP_COST_RATE, t_txn)
    pb_tds = resolve_setting(mysql_db_session, Programme.PLAN_B, SettingKey.TDS_RATE, t_txn)

    pb_direct_split = calculate_commission_split(
        gross=pb_direct.as_money(),
        op_cost_rate=pb_op.as_rate(),
        tds_rate=pb_tds.as_rate(),
    )
    assert pb_direct_split.gross == Money("500.00", "INR")
    assert pb_direct_split.op_cost == Money("0.00", "INR")
    assert pb_direct_split.tds == Money("0.00", "INR")
    assert pb_direct_split.net == Money("500.00", "INR")

    pb_gen_split = calculate_commission_split(
        gross=pb_gen.as_money(),
        op_cost_rate=pb_op.as_rate(),
        tds_rate=pb_tds.as_rate(),
    )
    assert pb_gen_split.gross == Money("50.00", "INR")
    assert pb_gen_split.op_cost == Money("0.00", "INR")
    assert pb_gen_split.tds == Money("0.00", "INR")
    assert pb_gen_split.net == Money("50.00", "INR")
