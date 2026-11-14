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
