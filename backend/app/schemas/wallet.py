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
    completed_at: datetime

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
