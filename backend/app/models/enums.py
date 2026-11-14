import enum


class UserRole(str, enum.Enum):
    """User account roles."""
    CUSTOMER = "customer"
    ADMIN = "admin"


class OTPPurpose(str, enum.Enum):
    """Purpose of one-time password."""
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"
    ADMIN_MFA = "admin_mfa"


class OrderStatus(str, enum.Enum):
    """Fulfillment state of an order."""
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class PaymentStatus(str, enum.Enum):
    """Payment transaction status."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SIMULATED_REFUNDED = "simulated_refunded"


class AllocationScenario(str, enum.Enum):
    """Financial allocation breakdown scenarios (Scenarios A, B, C, D)."""
    A = "A"  # Both Direct Referral & Sequential Commission apply
    B = "B"  # Sequential Commission only
    C = "C"  # Neither applies (Active Beneficiary purchase without referral code)
    D = "D"  # Direct Referral only (Active Beneficiary first purchase with referral code)


class QueueStatus(str, enum.Enum):
    """Status in the global sequential beneficiary queue."""
    WAITING = "waiting"
    ACTIVE = "active"
    COMPLETED = "completed"


class CycleStatus(str, enum.Enum):
    """Status of an individual commission cycle."""
    ACTIVE = "active"
    COMPLETED = "completed"


class WalletType(str, enum.Enum):
    """Isolated customer wallet types."""
    DIRECT_REFERRAL = "direct_referral"
    SEQUENTIAL_COMMISSION = "sequential_commission"


class WalletTransactionType(str, enum.Enum):
    """Direction of wallet funds movement."""
    CREDIT = "credit"
    DEBIT = "debit"


class WalletReferenceType(str, enum.Enum):
    """Source event for a wallet ledger entry."""
    DIRECT_REFERRAL = "direct_referral"
    SEQUENTIAL_COMMISSION = "sequential_commission"
    WITHDRAWAL = "withdrawal"


class WithdrawalStatus(str, enum.Enum):
    """Status of simulated balance payout."""
    COMPLETED = "completed"
    FAILED = "failed"


class Programme(str, enum.Enum):
    """Programme classification for dual-programme referral platform."""
    PLAN_A = "PLAN_A"
    PLAN_B = "PLAN_B"
    LEGACY = "LEGACY"


class SettingAction(str, enum.Enum):
    """Audit action types for financial settings history."""
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DEACTIVATED = "DEACTIVATED"
    REACTIVATED = "REACTIVATED"


class AccountStatus(str, enum.Enum):
    """Account status classification for dual-programme platform users."""
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    DEACTIVATED = "DEACTIVATED"


from sqlalchemy import Enum as _SAEnum


def sql_enum(enum_cls, **kwargs):
    """Construct a MySQL-compatible SQLAlchemy Enum using enum string values rather than names."""
    return _SAEnum(
        enum_cls,
        values_callable=lambda x: [e.value for e in x],
        native_enum=True,
        **kwargs,
    )
