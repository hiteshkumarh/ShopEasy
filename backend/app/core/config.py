import os
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Base backend directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
ROOT_ENV_PATH = BASE_DIR.parent / ".env"

# Explicitly load environment variables
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
if ROOT_ENV_PATH.exists():
    load_dotenv(dotenv_path=ROOT_ENV_PATH)


class Settings:
    """Application configuration loaded from environment variables."""

    # Application settings
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Security & JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # Database Configuration (MySQL 8.0)
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "shopeasy_db")
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")

    # Simulated Mock Services
    ENABLE_MOCK_PAYMENT: bool = os.getenv("ENABLE_MOCK_PAYMENT", "True").lower() in ("true", "1", "yes")
    DEV_OTP_CODE: str = os.getenv("DEV_OTP_CODE", "123456")

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
