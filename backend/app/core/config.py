import os
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Base backend directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
ROOT_ENV_PATH = BASE_DIR.parent / ".env"

# Explicitly load environment variables. The repository-level .env is loaded
# first so it remains the source of truth when backend/.env still contains
# template placeholders. Existing process environment variables are preserved
# because load_dotenv defaults to override=False.
if ROOT_ENV_PATH.exists():
    load_dotenv(dotenv_path=ROOT_ENV_PATH)
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)


class Settings:
    """Application configuration loaded from environment variables."""

    # Server & network defaults
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]

    # JWT Algorithm & Expiry defaults
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # Database Configuration (MySQL/TiDB Cloud)
    MYSQL_URL: Optional[str] = os.getenv("MYSQL_URL")
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL") or MYSQL_URL
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "shopeasy_db")
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_SSL_CA: Optional[str] = os.getenv("DB_SSL_CA")

    # Simulated Mock Services
    ENABLE_MOCK_PAYMENT: bool = os.getenv("ENABLE_MOCK_PAYMENT", "True").lower() in ("true", "1", "yes")

    def __init__(self) -> None:
        """Initialize settings and execute production safeguards if running in production."""
        self.validate_production_configuration()

    @property
    def ENVIRONMENT(self) -> str:
        """Get the active application environment mode.

        Defaults to 'development' for local development. If running in a cloud
        deployment environment (e.g. Render) without an explicit ENVIRONMENT setting,
        fails fast to prevent accidental development fallbacks in production.
        """
        env = os.getenv("ENVIRONMENT")
        if not env or not env.strip():
            if os.getenv("RENDER"):
                raise ValueError(
                    "ENVIRONMENT environment variable must be explicitly configured when running on Render "
                    "(e.g. ENVIRONMENT=production)."
                )
            return "development"
        return env.strip()

    @ENVIRONMENT.setter
    def ENVIRONMENT(self, value: str) -> None:
        os.environ["ENVIRONMENT"] = value

    @property
    def is_production(self) -> bool:
        """Check whether the active environment is production."""
        return self.ENVIRONMENT.lower() in ("production", "prod")

    @property
    def DEBUG(self) -> bool:
        """Get the application debug flag.

        In production environments, DEBUG must strictly be False. Enabling DEBUG
        in production raises a ValueError to prevent query logging and internal
        information leakage.
        In development environments, defaults to True if unset.
        """
        raw = os.getenv("DEBUG")
        if self.is_production:
            if raw is not None and raw.strip().lower() in ("true", "1", "yes"):
                raise ValueError(
                    "DEBUG must not be enabled in production environments. "
                    "Set DEBUG=False to prevent query logging and sensitive data exposure."
                )
            return False

        if raw is None:
            return True
        return raw.strip().lower() in ("true", "1", "yes")

    @DEBUG.setter
    def DEBUG(self, value: bool) -> None:
        os.environ["DEBUG"] = str(value)

    @property
    def SECRET_KEY(self) -> str:
        """Get the JWT secret key.

        In production, requires an explicit, cryptographically strong secret of at
        least 32 characters and strictly rejects placeholders and weak keys.
        In development, falls back to a development placeholder if unset.
        """
        secret = os.getenv("SECRET_KEY")
        if self.is_production:
            if not secret or not secret.strip():
                raise ValueError(
                    "SECRET_KEY environment variable is required in production and cannot be empty. "
                    "Please configure a cryptographically strong secret key of at least 32 characters."
                )
            clean_secret = secret.strip()
            placeholder_prefixes = ("replace-with", "change-this", "dev-secret", "your-secret")
            known_placeholders = (
                "dev-secret-key-change-in-production",
                "change-this-to-a-secure-random-secret-key-at-least-32-chars",
                "change-this-to-a-secure-random-secret-key-minimum-32-characters",
            )
            if clean_secret in known_placeholders or any(clean_secret.lower().startswith(p) for p in placeholder_prefixes):
                raise ValueError(
                    "SECRET_KEY cannot use placeholder value in production. "
                    "Please configure a cryptographically strong secret key of at least 32 characters."
                )
            if len(clean_secret) < 32:
                raise ValueError(
                    f"SECRET_KEY must be at least 32 characters long in production (got {len(clean_secret)} characters). "
                    "Please configure a cryptographically strong secret."
                )
            return clean_secret

        # Development / test mode fallback
        if secret and secret.strip():
            return secret.strip()
        return "dev-secret-key-change-in-production"

    @SECRET_KEY.setter
    def SECRET_KEY(self, value: str) -> None:
        os.environ["SECRET_KEY"] = value

    @property
    def DEV_OTP_CODE(self) -> str:
        """Get the development fixed OTP code.

        Strictly prohibited and inaccessible in non-development environments.
        """
        if self.is_production or self.ENVIRONMENT.lower() != "development":
            raise RuntimeError(
                "DEV_OTP_CODE is strictly prohibited and inaccessible in non-development environments. "
                "Development OTP codes must never be queried or used in production."
            )
        return os.getenv("DEV_OTP_CODE", "123456").strip()

    @DEV_OTP_CODE.setter
    def DEV_OTP_CODE(self, value: str) -> None:
        os.environ["DEV_OTP_CODE"] = value

    def validate_production_configuration(self) -> None:
        """Validate critical security safeguards when running in production.

        Fails fast at application initialization time if any critical security
        setting is missing or unsafe.
        """
        if self.is_production:
            _ = self.SECRET_KEY
            _ = self.DEBUG
            _ = self.OTP_HMAC_SECRET

    # Initial Administrator Provisioning
    @property
    def ADMIN_NAME(self) -> str:
        """Get the initial administrator full name directly from ADMIN_NAME."""
        name = os.getenv("ADMIN_NAME")
        if not name or not name.strip():
            raise ValueError("ADMIN_NAME environment variable is required and cannot be empty.")
        name = name.strip()
        if len(name) > 100:
            raise ValueError("ADMIN_NAME must not exceed 100 characters.")
        return name

    @ADMIN_NAME.setter
    def ADMIN_NAME(self, value: str) -> None:
        os.environ["ADMIN_NAME"] = value

    @property
    def ADMIN_PHONE(self) -> str:
        """Get the initial administrator phone number directly from ADMIN_PHONE."""
        phone = os.getenv("ADMIN_PHONE")
        if not phone or not phone.strip():
            raise ValueError("ADMIN_PHONE environment variable is required and cannot be empty.")
        phone = phone.strip()
        raw_digits = phone.replace(" ", "").replace("-", "")
        if not re.match(r"^\+?[0-9]{10,15}$", raw_digits):
            raise ValueError(
                f"ADMIN_PHONE must be a valid phone number between 10 and 15 digits, got '{phone}'."
            )
        digits = "".join(c for c in raw_digits if c.isdigit())
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 10:
            return digits
        return raw_digits.lstrip("+")

    @ADMIN_PHONE.setter
    def ADMIN_PHONE(self, value: str) -> None:
        os.environ["ADMIN_PHONE"] = value

    @property
    def ADMIN_PASSWORD(self) -> str:
        """Get the initial administrator password directly from ADMIN_PASSWORD."""
        password = os.getenv("ADMIN_PASSWORD")
        if not password or not password.strip():
            raise ValueError("ADMIN_PASSWORD environment variable is required and cannot be empty.")
        if len(password) < 12:
            raise ValueError(
                f"ADMIN_PASSWORD must be at least 12 characters long, got {len(password)} characters."
            )
        if password.startswith("replace-with"):
            raise ValueError(
                "ADMIN_PASSWORD cannot use placeholder value. Please configure a secure password."
            )
        return password

    @ADMIN_PASSWORD.setter
    def ADMIN_PASSWORD(self, value: str) -> None:
        os.environ["ADMIN_PASSWORD"] = value

    @property
    def OTP_HMAC_SECRET(self) -> str:
        """Get the HMAC secret for OTP hashing.

        Requires an explicit, strong secret outside development.
        Must never reuse the JWT SECRET_KEY.
        """
        secret = os.getenv("OTP_HMAC_SECRET")
        is_dev = self.ENVIRONMENT.lower() == "development"

        if not is_dev:
            if not secret or not secret.strip():
                raise ValueError(
                    "In non-development environments, OTP_HMAC_SECRET must be explicitly configured."
                )
            if secret.strip() == "dev-otp-hmac-secret-change-in-production":
                raise ValueError(
                    "In non-development environments, OTP_HMAC_SECRET cannot use the default placeholder secret."
                )
            if len(secret.strip()) < 32:
                raise ValueError(
                    "In non-development environments, OTP_HMAC_SECRET must be at least 32 characters long."
                )
            if secret.strip() == self.SECRET_KEY:
                raise ValueError(
                    "OTP_HMAC_SECRET must not reuse the JWT SECRET_KEY."
                )
            return secret.strip()

        # Development mode
        dev_secret = secret.strip() if secret and secret.strip() else "dev-otp-hmac-secret-change-in-production"
        if dev_secret == self.SECRET_KEY:
            raise ValueError(
                "OTP_HMAC_SECRET must not reuse the JWT SECRET_KEY."
            )
        return dev_secret

    @OTP_HMAC_SECRET.setter
    def OTP_HMAC_SECRET(self, value: str) -> None:
        os.environ["OTP_HMAC_SECRET"] = value


settings = Settings()
