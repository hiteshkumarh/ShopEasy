import os
from pathlib import Path
from dotenv import load_dotenv

# Base backend directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

# Explicitly load environment variables from backend/.env if it exists
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()


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
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "shopeasy_db")
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")

    # Simulated Mock Services
    ENABLE_MOCK_PAYMENT: bool = os.getenv("ENABLE_MOCK_PAYMENT", "True").lower() in ("true", "1", "yes")
    DEV_OTP_CODE: str = os.getenv("DEV_OTP_CODE", "123456")

    # Initial Administrator Provisioning
    ADMIN_NAME: str = os.getenv("ADMIN_NAME", "System Admin")

    @property
    def ADMIN_PHONE(self) -> str:
        """Get the initial admin phone, requiring explicit configuration in non-development."""
        env_phone = os.getenv("ADMIN_PHONE")
        is_dev = self.ENVIRONMENT.lower() == "development"

        if not is_dev:
            if not env_phone or not env_phone.strip():
                raise ValueError(
                    "In non-development environments, ADMIN_PHONE must be explicitly configured."
                )
            return env_phone.strip()

        # Local development fallback
        return env_phone.strip() if env_phone else "9800000000"

    @ADMIN_PHONE.setter
    def ADMIN_PHONE(self, value: str) -> None:
        os.environ["ADMIN_PHONE"] = value

    @property
    def ADMIN_PASSWORD(self) -> str:
        """Get the initial admin password, requiring an explicit strong password in non-development."""
        env_pwd = os.getenv("ADMIN_PASSWORD")
        is_dev = self.ENVIRONMENT.lower() == "development"

        if not is_dev:
            if not env_pwd:
                raise ValueError(
                    "In non-development environments, ADMIN_PASSWORD must be explicitly configured."
                )
            if env_pwd == "Admin@ShopEasy2026":
                raise ValueError(
                    "In non-development environments, ADMIN_PASSWORD cannot use the default placeholder password."
                )
            if len(env_pwd) < 12:
                raise ValueError(
                    "In non-development environments, ADMIN_PASSWORD must be at least 12 characters long."
                )
            return env_pwd

        # Local development fallback
        return env_pwd if env_pwd else "Admin@ShopEasy2026"

    @ADMIN_PASSWORD.setter
    def ADMIN_PASSWORD(self, value: str) -> None:
        os.environ["ADMIN_PASSWORD"] = value


settings = Settings()
