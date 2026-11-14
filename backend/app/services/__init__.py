"""Business logic and domain services."""

from app.services.allocation import calculate_and_create_order_allocation
from app.services.checkout import execute_checkout
from app.services.earning_engine import process_order_earnings
from app.services.financial_settings import (
    CANONICAL_SETTINGS,
    CanonicalSettingDefinition,
    FinancialSettingError,
    FinancialSettingsService,
    FinancialSettingValidationError,
    MultipleMatchingSettingsError,
    SettingAlreadyExistsError,
    SettingConcurrencyError,
    SettingKey,
    SettingNotFoundError,
    create_setting,
    deactivate_setting,
    get_setting,
    get_setting_history,
    get_setting_or_none,
    has_setting,
    reactivate_setting,
    resolve_setting,
    seed_financial_settings,
    update_setting,
)
from app.services.otp_service import (
    create_otp,
    generate_otp,
    normalize_phone,
    verify_otp,
)
from app.services.queue_service import (
    determine_sequential_eligibility,
    enroll_customer_in_queue,
    lock_queue_control,
    process_sequential_commission,
)
from app.services.referral import generate_referral_code, validate_referral_code
from app.services.wallet_service import (
    credit_wallet,
    execute_simulated_withdrawal,
    get_or_create_wallet,
)

__all__ = [
    "calculate_and_create_order_allocation",
    "create_otp",
    "credit_wallet",
    "determine_sequential_eligibility",
    "enroll_customer_in_queue",
    "execute_checkout",
    "execute_simulated_withdrawal",
    "generate_otp",
    "generate_referral_code",
    "get_or_create_wallet",
    "lock_queue_control",
    "normalize_phone",
    "process_order_earnings",
    "process_sequential_commission",
    "validate_referral_code",
    "verify_otp",
    # Financial Settings
    "FinancialSettingsService",
    "create_setting",
    "update_setting",
    "deactivate_setting",
    "reactivate_setting",
    "resolve_setting",
    "get_setting",
    "get_setting_or_none",
    "has_setting",
    "get_setting_history",
    "seed_financial_settings",
    "SettingKey",
    "CanonicalSettingDefinition",
    "CANONICAL_SETTINGS",
    "FinancialSettingError",
    "SettingNotFoundError",
    "SettingAlreadyExistsError",
    "MultipleMatchingSettingsError",
    "FinancialSettingValidationError",
    "SettingConcurrencyError",
]
