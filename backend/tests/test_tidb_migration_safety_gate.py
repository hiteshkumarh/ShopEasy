"""Focused unit tests for the narrowly scoped TiDB Cloud migration safety gate.

Validates:
  1. Both authorization variables absent -> fails closed.
  2. Only ALLOW_REMOTE_MIGRATION present -> fails closed.
  3. Only CONFIRM_TARGET_DB present -> fails closed.
  4. Wrong confirmation database -> fails closed.
  5. Wrong hostname -> fails closed.
  6. Target shopeasy_app is strictly rejected.
  7. Correct exact target and both authorization variables in operator mode -> succeeds.
  8. Pytest environment (ENVIRONMENT=testing or PYTEST_CURRENT_TEST) always blocks remote migration.
  9. Normal application startup/connection does not require migration authorization.
 10. Local test databases continue to pass.
 11. Local non-test databases continue to fail closed.
"""

import os
from pathlib import Path
import sys
import pytest

# Ensure backend root is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.core.database import (
    APPROVED_REMOTE_DB,
    APPROVED_TIDB_HOST,
    create_database_engine,
    get_alembic_database_url,
    get_database_url,
    validate_alembic_database_url,
)

pytestmark = pytest.mark.unit

APPROVED_URL = f"mysql+pymysql://user:pass@{APPROVED_TIDB_HOST}:4000/{APPROVED_REMOTE_DB}"
PROHIBITED_APP_URL = f"mysql+pymysql://user:pass@{APPROVED_TIDB_HOST}:4000/shopeasy_app"
WRONG_HOST_URL = f"mysql+pymysql://user:pass@other-cluster.tidbcloud.com:4000/{APPROVED_REMOTE_DB}"
LOCAL_TEST_URL = "mysql+pymysql://root:pass@127.0.0.1:3306/shopeasy_test_ci"
LOCAL_NON_TEST_URL = "mysql+pymysql://root:pass@127.0.0.1:3306/shopeasy_dev"


@pytest.fixture(autouse=True)
def clean_gate_environment(monkeypatch):
    """Ensure clean gate environment variables around each test."""
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_gate_both_authorization_variables_absent_fails_closed(monkeypatch):
    """1. Verify migration fails closed when both authorization variables are absent."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    with pytest.raises(RuntimeError, match="Remote migration authorization required"):
        validate_alembic_database_url(APPROVED_URL)


def test_gate_only_allow_remote_migration_present_fails_closed(monkeypatch):
    """2. Verify migration fails closed when only ALLOW_REMOTE_MIGRATION is set."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    with pytest.raises(RuntimeError, match="Target database confirmation mismatch"):
        validate_alembic_database_url(APPROVED_URL)


def test_gate_only_confirm_target_db_present_fails_closed(monkeypatch):
    """3. Verify migration fails closed when only CONFIRM_TARGET_DB is set."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)

    with pytest.raises(RuntimeError, match="Remote migration authorization required"):
        validate_alembic_database_url(APPROVED_URL)


def test_gate_wrong_confirmation_database_fails_closed(monkeypatch):
    """4. Verify migration fails closed when CONFIRM_TARGET_DB specifies a different database."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", "wrong_database_name")

    with pytest.raises(RuntimeError, match="Target database confirmation mismatch"):
        validate_alembic_database_url(APPROVED_URL)


def test_gate_wrong_hostname_fails_closed(monkeypatch):
    """5. Verify migration fails closed when target host is not the exact approved TiDB Cloud host."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)

    with pytest.raises(RuntimeError, match="Remote migration authorization rejected for unauthorized host"):
        validate_alembic_database_url(WRONG_HOST_URL)


def test_gate_shopeasy_app_always_rejected(monkeypatch):
    """6. Verify shopeasy_app is strictly rejected even if both authorization variables are provided."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", "shopeasy_app")

    with pytest.raises(RuntimeError, match="Database 'shopeasy_app' is on the strictly prohibited database list"):
        validate_alembic_database_url(PROHIBITED_APP_URL)


def test_gate_approved_target_operator_mode_succeeds(monkeypatch):
    """7. Verify approved target succeeds when both authorization variables are set outside pytest."""
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    validated = validate_alembic_database_url(APPROVED_URL)
    assert validated == APPROVED_URL


def test_pytest_environment_always_blocks_remote_migration(monkeypatch):
    """8. Verify pytest environment (ENVIRONMENT=testing) unconditionally blocks remote migration."""
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    with pytest.raises(RuntimeError, match="Remote TiDB Cloud migrations are strictly prohibited during automated test execution"):
        validate_alembic_database_url(APPROVED_URL)


def test_pytest_current_test_always_blocks_remote_migration(monkeypatch):
    """9. Verify presence of PYTEST_CURRENT_TEST unconditionally blocks remote migration."""
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_something.py::test_foo")

    with pytest.raises(RuntimeError, match="Remote TiDB Cloud migrations are strictly prohibited during automated test execution"):
        validate_alembic_database_url(APPROVED_URL)


def test_normal_application_connection_does_not_require_authorization(monkeypatch):
    """10. Verify normal application startup and engine creation do not require migration authorization."""
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Engine creation for isolated test DB succeeds without migration authorization
    engine = create_database_engine("sqlite:///:memory:")
    assert engine is not None
    engine.dispose()


def test_local_test_database_continues_to_pass(monkeypatch):
    """11. Verify local MySQL test databases continue to be permitted without remote variables."""
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    validated = validate_alembic_database_url(LOCAL_TEST_URL)
    assert validated == LOCAL_TEST_URL


def test_local_non_test_database_continues_to_be_rejected(monkeypatch):
    """12. Verify local non-test databases continue to fail closed."""
    with pytest.raises(RuntimeError, match="Alembic database name must begin with 'shopeasy_test_'"):
        validate_alembic_database_url(LOCAL_NON_TEST_URL)


def test_wp6_offline_sql_generation_succeeds(monkeypatch, capsys):
    """13. Verify WP-6 and full migration chain offline SQL generation succeeds without None scalar error."""
    from alembic.config import Config
    from alembic import command

    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "mysql+pymysql://test:test@127.0.0.1:3306/shopeasy_test_offline")
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    # Offline upgrade to head must succeed cleanly
    command.upgrade(cfg, "head", sql=True)
    captured = capsys.readouterr()

    # Verify WP-6 billing_counters insert is rendered into static SQL
    assert "billing_counters" in captured.out
    assert "GLOBAL_BILLING_ID" in captured.out


def test_get_alembic_database_url_placeholder_with_authorized_operator(monkeypatch):
    """14. Verify placeholder URL in alembic.ini resolves to approved target when operator authorization is present."""
    from alembic.config import Config

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))

    # alembic.ini contains static 'mysql+pymysql://placeholder'
    assert cfg.get_main_option("sqlalchemy.url") == "mysql+pymysql://placeholder"

    resolved_url = get_alembic_database_url(cfg)
    assert APPROVED_TIDB_HOST in resolved_url
    assert APPROVED_REMOTE_DB in resolved_url


def test_get_alembic_database_url_placeholder_missing_authorization_fails_closed(monkeypatch):
    """15. Verify placeholder in alembic.ini fails closed when operator authorization is absent."""
    from alembic.config import Config

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", APPROVED_URL)
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))

    with pytest.raises(RuntimeError, match="Remote migration authorization required"):
        get_alembic_database_url(cfg)


def test_get_alembic_database_url_programmatic_override_preserved(monkeypatch):
    """16. Verify explicit programmatic test-fixture URL overrides in Config are preserved."""
    from alembic.config import Config

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")

    resolved = get_alembic_database_url(cfg)
    assert resolved == "sqlite:///:memory:"


def test_get_alembic_database_url_placeholder_pytest_isolation_blocks_remote(monkeypatch):
    """17. Verify placeholder resolution strictly fails closed under pytest even with operator flags."""
    from alembic.config import Config

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", APPROVED_REMOTE_DB)
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))

    with pytest.raises(RuntimeError, match="Remote TiDB Cloud migrations are strictly prohibited during automated test execution"):
        get_alembic_database_url(cfg)


def test_get_alembic_database_url_placeholder_wrong_target_db_fails_closed(monkeypatch):
    """18. Verify placeholder resolution fails closed when CONFIRM_TARGET_DB does not match approved database."""
    from alembic.config import Config

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("ALLOW_REMOTE_MIGRATION", "true")
    monkeypatch.setenv("CONFIRM_TARGET_DB", "wrong_db")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))

    with pytest.raises(RuntimeError, match="Target database confirmation mismatch"):
        get_alembic_database_url(cfg)


def test_get_alembic_database_url_config_none_missing_env_fails_closed(monkeypatch):
    """19. Verify get_alembic_database_url(None) fails closed when no environment variables or authorization exist."""
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    with pytest.raises(RuntimeError, match="No explicit DATABASE_URL environment variable provided for Alembic"):
        get_alembic_database_url(None)


def test_get_alembic_database_url_explicit_url_containing_placeholder_word_not_ignored(monkeypatch):
    """20. Verify explicitly configured URL containing the substring 'placeholder' is not silently ignored as a placeholder."""
    from alembic.config import Config

    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_MIGRATION", raising=False)
    monkeypatch.delenv("CONFIRM_TARGET_DB", raising=False)

    ini_path = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini_path))

    # Explicit test DB whose name contains 'placeholder' must be honored and validated, not bypassed
    explicit_test_url = "mysql+pymysql://root:pass@127.0.0.1:3306/shopeasy_test_placeholder"
    cfg.set_main_option("sqlalchemy.url", explicit_test_url)

    resolved = get_alembic_database_url(cfg)
    assert resolved == explicit_test_url

    # Explicit unauthorized URL containing 'placeholder' must be validated and blocked, not treated as config placeholder
    unauthorized_placeholder_url = "mysql+pymysql://placeholder-server.internal:3306/shopeasy_test_db"
    cfg.set_main_option("sqlalchemy.url", unauthorized_placeholder_url)
    with pytest.raises(RuntimeError, match="Alembic safety guard blocked connection to remote host"):
        get_alembic_database_url(cfg)



