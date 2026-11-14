"""SQLAlchemy database models for ShopEasy."""

from app.models.audit import AuditLog
from app.models.cart import CartItem
from app.models.commission import ReferralCommission, SequentialCommission
from app.models.enums import (
    AccountStatus,
    AllocationScenario,
    CycleStatus,
    OTPPurpose,
    OrderStatus,
    PaymentStatus,
    Programme,
    QueueStatus,
    SettingAction,
    UserRole,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.financial_settings import (
    FinancialSetting,
    FinancialSettingHistory,
)
from app.models.notification import Notification
from app.models.order import Order, OrderAllocation, OrderItem
from app.models.product import Product
from app.models.queue import BeneficiaryQueue, CommissionCycle, QueueControl
from app.models.referral import ReferralRelationship
from app.models.user import AccountStatusHistory, Address, OTP, User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal

__all__ = [
    # Enums
    "AccountStatus",
    "UserRole",
    "OTPPurpose",
    "OrderStatus",
    "PaymentStatus",
    "AllocationScenario",
    "QueueStatus",
    "CycleStatus",
    "WalletType",
    "WalletTransactionType",
    "WalletReferenceType",
    "WithdrawalStatus",
    "Programme",
    "SettingAction",
    # Models
    "User",
    "AccountStatusHistory",
    "ReferralRelationship",
    "AuditLog",
    "Notification",
    "OTP",
    "Address",
    "CartItem",
    "Product",
    "Order",
    "OrderItem",
    "OrderAllocation",
    "BeneficiaryQueue",
    "CommissionCycle",
    "QueueControl",
    "SequentialCommission",
    "ReferralCommission",
    "Wallet",
    "WalletTransaction",
    "Withdrawal",
    "FinancialSetting",
    "FinancialSettingHistory",
]
