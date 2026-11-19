from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)


class WalletBalanceResponse(BaseModel):
    """Current balance and lifetime withdrawn total for a customer wallet."""

    wallet_type: WalletType
    balance: Decimal = Field(..., max_digits=10, decimal_places=2)
    total_withdrawn: Decimal = Field(..., max_digits=10, decimal_places=2)
    is_frozen: bool = Field(default=False)

    model_config = ConfigDict(from_attributes=True)


class WalletTransactionResponse(BaseModel):
    """Immutable auditable ledger transaction record."""

    id: int
    wallet_id: int
    wallet_type: WalletType
    transaction_type: WalletTransactionType
    amount: Decimal = Field(..., max_digits=10, decimal_places=2)
    balance_after: Decimal = Field(..., max_digits=10, decimal_places=2)
    reference_type: WalletReferenceType
    reference_id: int
    idempotency_key: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WithdrawalRequest(BaseModel):
    """Request to withdraw the full available balance from a designated wallet."""

    wallet_type: WalletType = Field(
        ...,
        description="Designated wallet type: 'direct_referral' or 'sequential_commission'",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional client-generated unique idempotency key (UUID or hash)",
    )


class WithdrawalResponse(BaseModel):
    """Simulated withdrawal execution result."""

    id: int
    wallet_id: int
    wallet_type: WalletType
    amount: Decimal = Field(..., max_digits=10, decimal_places=2)
    status: WithdrawalStatus
    idempotency_key: str
    requested_at: datetime
    completed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    admin_id: Optional[int] = None
    receipt_reference: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AdminWithdrawalReviewRequest(BaseModel):
    """Admin request payload to reject or process a pending withdrawal."""

    reason: Optional[str] = Field(default=None, max_length=255, description="Mandatory reason for rejection")


class AdminWalletFreezeRequest(BaseModel):
    """Admin request payload to freeze a wallet."""

    reason: str = Field(..., min_length=3, max_length=255, description="Mandatory reason for freezing wallet")


class UserWalletSummary(BaseModel):
    """Summary of a user wallet for administrative lookup and selection."""

    id: int
    user_id: int
    wallet_type: str
    balance: Decimal
    total_withdrawn: Decimal
    is_frozen: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserWalletsLookupResponse(BaseModel):
    """Response containing user identification and associated wallets."""

    user_id: int
    full_name: str
    phone: str
    role: str
    programme: Optional[str] = None
    account_status: Optional[str] = None
    wallets: List[UserWalletSummary]


class AdminWalletFreezeByPhoneRequest(BaseModel):
    """Admin request to freeze a wallet identified by registered mobile number."""

    user_number: str = Field(..., min_length=1, max_length=30, description="Customer or distributor registered mobile number")
    wallet_id: Optional[int] = Field(None, description="Optional wallet ID if user has multiple wallets")
    reason: str = Field(..., min_length=3, max_length=500, description="Mandatory reason for action")


class AdminWalletUnfreezeByPhoneRequest(BaseModel):
    """Admin request to unfreeze a wallet identified by registered mobile number."""

    user_number: str = Field(..., min_length=1, max_length=30, description="Customer or distributor registered mobile number")
    wallet_id: Optional[int] = Field(None, description="Optional wallet ID if user has multiple wallets")
    reason: Optional[str] = Field("Administrative unfreeze", max_length=500, description="Reason for action")


class AdminWalletFreezeByPhoneResponse(BaseModel):
    """Result of freeze or unfreeze operation executed by user mobile number."""

    status: str
    message: str
    wallet_id: int
    is_frozen: bool
    user: dict


class WalletFreezeHistoryResponse(BaseModel):
    """Audit record for wallet freeze/unfreeze actions."""

    id: int
    wallet_id: int
    admin_id: int
    action: str
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedWalletTransactions(BaseModel):
    """Paginated collection of wallet ledger transactions."""

    items: List[WalletTransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PaginatedWithdrawals(BaseModel):
    """Paginated collection of customer withdrawals."""

    items: List[WithdrawalResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
