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
