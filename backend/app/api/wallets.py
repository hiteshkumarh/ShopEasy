import logging
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.enums import WalletType
from app.models.user import User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal
from app.schemas.wallet import (
    PaginatedWalletTransactions,
    PaginatedWithdrawals,
    WalletBalanceResponse,
    WalletTransactionResponse,
    WithdrawalRequest,
    WithdrawalResponse,
)
from app.services.wallet_service import (
    execute_simulated_withdrawal,
    get_or_create_wallet,
)

logger = logging.getLogger("shopeasy.api.wallets")

router = APIRouter(prefix="/wallets", tags=["Wallets & Withdrawals"])


@router.get("", response_model=List[WalletBalanceResponse])
def get_customer_wallets(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve isolated balances for both Direct Referral and Sequential Commission wallets."""
    result: List[WalletBalanceResponse] = []
    for w_type in [WalletType.DIRECT_REFERRAL, WalletType.SEQUENTIAL_COMMISSION]:
        wallet = get_or_create_wallet(db, user_id=current_user.id, wallet_type=w_type)
        result.append(
            WalletBalanceResponse(
                wallet_type=wallet.wallet_type,
                balance=wallet.balance,
                total_withdrawn=wallet.total_withdrawn,
            )
        )
    return result


@router.get("/transactions", response_model=PaginatedWalletTransactions)
def list_wallet_transactions(
    wallet_type: Optional[WalletType] = Query(
        None, description="Optional wallet category filter"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve paginated auditable ledger transactions for the authenticated customer."""
    query = db.query(WalletTransaction).filter(
        WalletTransaction.user_id == current_user.id
    )
    if wallet_type:
        query = query.filter(WalletTransaction.wallet_type == wallet_type)

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size

    transactions = (
        query.order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        WalletTransactionResponse.model_validate(tx) for tx in transactions
    ]

    return PaginatedWalletTransactions(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/withdrawals", response_model=PaginatedWithdrawals)
def list_customer_withdrawals(
    wallet_type: Optional[WalletType] = Query(
        None, description="Optional wallet category filter"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve paginated simulated withdrawal history for the authenticated customer."""
    query = (
        db.query(Withdrawal)
        .options(joinedload(Withdrawal.wallet))
        .filter(Withdrawal.user_id == current_user.id)
    )
    if wallet_type:
        query = query.join(Wallet, Withdrawal.wallet_id == Wallet.id).filter(
            Wallet.wallet_type == wallet_type
        )

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size

    withdrawals = (
        query.order_by(Withdrawal.requested_at.desc(), Withdrawal.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [WithdrawalResponse.model_validate(w) for w in withdrawals]

    return PaginatedWithdrawals(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/withdraw", response_model=WithdrawalResponse, status_code=status.HTTP_200_OK)
def withdraw_funds(
    payload: WithdrawalRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Execute simulated full-balance withdrawal for Direct Referral or Sequential Commission wallet.

    Enforces:
      - Direct Referral: Available balance >= ₹4,000.00.
      - Sequential Commission: Completed 16/16 cycle and balance == ₹4,000.00.
      - Withdraws full available balance and resets wallet balance to ₹0.00.
      - Idempotent: repeated identical requests return original withdrawal response.
    """
    try:
        withdrawal = execute_simulated_withdrawal(
            db=db,
            customer=current_user,
            wallet_type=payload.wallet_type,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        db.refresh(withdrawal)
        # Ensure wallet relationship is attached for wallet_type property
        if not withdrawal.wallet:
            withdrawal.wallet = (
                db.query(Wallet).filter(Wallet.id == withdrawal.wallet_id).first()
            )
        return WithdrawalResponse.model_validate(withdrawal)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(
            f"Withdrawal execution error for customer #{current_user.id}: {type(exc).__name__}: {exc}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute simulated withdrawal. Please try again.",
        )
