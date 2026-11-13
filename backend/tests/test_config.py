import os
from pathlib import Path
import sys
import pytest

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings


@pytest.fixture(autouse=True)
def clean_env():
    """Preserve and restore os.environ around each test."""
    original_env = dict(os.environ)
    yield
    for key in list(os.environ.keys()):
        if key not in original_env and not key.startswith("PYTEST_"):
            os.environ.pop(key, None)
    for key, val in original_env.items():
        os.environ[key] = val


def test_development_defaults_preserve_local_workflow():
    """Verify default development configuration loads cleanly without manual variables."""
    os.environ.pop("ENVIRONMENT", None)
    os.environ.pop("DEBUG", None)
    os.environ.pop("SECRET_KEY", None)
    os.environ.pop("RENDER", None)

    s = Settings()
    assert s.ENVIRONMENT == "development"
    assert s.is_production is False
    assert s.DEBUG is True
    assert s.SECRET_KEY == "dev-secret-key-change-in-production"
    assert s.DEV_OTP_CODE == "123456"


def test_production_rejects_empty_secret_key():
    """Verify production fails when SECRET_KEY is missing or empty."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ.pop("SECRET_KEY", None)
    os.environ["DEBUG"] = "False"

    with pytest.raises(ValueError, match="SECRET_KEY environment variable is required in production"):
        Settings()


def test_production_rejects_placeholder_secret_key():
    """Verify production fails when SECRET_KEY uses a known placeholder."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["SECRET_KEY"] = "dev-secret-key-change-in-production"
    os.environ["DEBUG"] = "False"

    with pytest.raises(ValueError, match="SECRET_KEY cannot use placeholder value"):
        Settings()


def test_production_rejects_short_secret_key():
    """Verify production fails when SECRET_KEY is shorter than 32 characters."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["SECRET_KEY"] = "short-key-under-32-chars"
    os.environ["DEBUG"] = "False"

    with pytest.raises(ValueError, match="SECRET_KEY must be at least 32 characters long"):
        Settings()


def test_production_rejects_debug_true():
    """Verify production fails when DEBUG is explicitly set to True."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["SECRET_KEY"] = "x" * 32
    os.environ["OTP_HMAC_SECRET"] = "y" * 32
    os.environ["DEBUG"] = "True"

    with pytest.raises(ValueError, match="DEBUG must not be enabled in production"):
        Settings()


def test_production_accepts_valid_configuration():
    """Verify production loads successfully with valid security configuration."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["SECRET_KEY"] = "strong-production-secret-key-at-least-32-chars"
    os.environ["OTP_HMAC_SECRET"] = "distinct-production-hmac-secret-at-least-32-chars"
    os.environ["DEBUG"] = "False"

    s = Settings()
    assert s.ENVIRONMENT == "production"
    assert s.is_production is True
    assert s.DEBUG is False
    assert s.SECRET_KEY == "strong-production-secret-key-at-least-32-chars"


def test_production_prohibits_dev_otp_access():
    """Verify DEV_OTP_CODE raises RuntimeError when accessed in production."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["SECRET_KEY"] = "strong-production-secret-key-at-least-32-chars"
    os.environ["OTP_HMAC_SECRET"] = "distinct-production-hmac-secret-at-least-32-chars"
    os.environ["DEBUG"] = "False"

    s = Settings()
    with pytest.raises(RuntimeError, match="DEV_OTP_CODE is strictly prohibited and inaccessible in non-development"):
        _ = s.DEV_OTP_CODE


def test_render_environment_requires_explicit_setting():
    """Verify running on Render without ENVIRONMENT fails fast."""
    os.environ["RENDER"] = "true"
    os.environ.pop("ENVIRONMENT", None)

    with pytest.raises(ValueError, match="ENVIRONMENT environment variable must be explicitly configured when running on Render"):
        Settings()
