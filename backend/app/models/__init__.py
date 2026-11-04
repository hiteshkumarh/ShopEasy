"""SQLAlchemy database models for ShopEasy."""

from app.models.commission import ReferralCommission, SequentialCommission
from app.models.enums import (
    AllocationScenario,
    CycleStatus,
    OTPPurpose,
    OrderStatus,
    PaymentStatus,
    QueueStatus,
    UserRole,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.order import Order, OrderAllocation, OrderItem
from app.models.product import Product
from app.models.queue import BeneficiaryQueue, CommissionCycle, QueueControl
from app.models.user import Address, OTP, User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal

__all__ = [
    # Enums
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
    # Models
    "User",
    "OTP",
    "Address",
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
]
