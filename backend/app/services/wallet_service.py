from datetime import datetime
from decimal import Decimal
import logging
from typing import Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.commission import ReferralCommission
from app.models.enums import (
    CycleStatus,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.queue import CommissionCycle
from app.models.user import User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal

logger = logging.getLogger("shopeasy.wallet")

DIRECT_REFERRAL_MIN_WITHDRAWAL = Decimal("750.00")
SEQUENTIAL_CYCLE_WITHDRAWAL_AMOUNT = Decimal("4000.00")
ZERO_AMOUNT = Decimal("0.00")


def get_or_create_wallet(
    db: Session,
    user_id: int,
    wallet_type: WalletType,
    for_update: bool = False,
) -> Wallet:
    """Retrieve or initialize a customer's wallet.

    Args:
        db: Active SQLAlchemy database session.
        user_id: ID of the customer owning the wallet.
        wallet_type: DIRECT_REFERRAL or SEQUENTIAL_COMMISSION.
        for_update: If True, locks the row using SELECT ... FOR UPDATE.

    Returns:
        The locked or initialized Wallet instance.
    """
    query = db.query(Wallet).filter(
        Wallet.user_id == user_id,
        Wallet.wallet_type == wallet_type,
    )
    if for_update:
        query = query.with_for_update()

    wallet = query.first()
    if not wallet:
        try:
            with db.begin_nested():
                wallet = Wallet(
                    user_id=user_id,
                    wallet_type=wallet_type,
                    balance=ZERO_AMOUNT,
                    total_withdrawn=ZERO_AMOUNT,
                )
                db.add(wallet)
                db.flush()
            db.refresh(wallet)
        except IntegrityError:
            # Concurrent initialization hit uq_wallets_user_type constraint.
            # begin_nested() rolled back only the savepoint; outer transaction is preserved.
            # Query using with_for_update() to execute a locking read that sees the committed row in MySQL InnoDB.
            query = db.query(Wallet).filter(
                Wallet.user_id == user_id,
                Wallet.wallet_type == wallet_type,
            )
            wallet = query.with_for_update().first()
            if not wallet:
                logger.error(
                    f"Failed to retrieve wallet for user #{user_id} and type {wallet_type.value} after collision."
                )
                raise RuntimeError(
                    f"Unable to retrieve wallet for user #{user_id} of type {wallet_type.value} following concurrent creation."
                )

    return wallet


def credit_wallet(
    db: Session,
    user_id: int,
    wallet_type: WalletType,
    amount: Decimal,
    reference_type: WalletReferenceType,
    reference_id: int,
    idempotency_key: str,
) -> Tuple[Wallet, WalletTransaction]:
    """Atomically credit a customer's wallet and append an auditable ledger entry.

    Args:
        db: Active SQLAlchemy database session.
        user_id: Customer recipient user ID.
        wallet_type: Target wallet category.
        amount: Positive amount to credit.
        reference_type: DIRECT_REFERRAL or SEQUENTIAL_COMMISSION.
        reference_id: ID of the corresponding commission record.
        idempotency_key: Unique idempotency key preventing duplicate ledger credits.

    Returns:
        Tuple of (updated Wallet, created WalletTransaction).
    """
    if amount <= ZERO_AMOUNT:
        raise ValueError(f"Credit amount must be strictly positive: {amount}")

    # 1. Check if transaction already exists for idempotency
    existing_tx = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.idempotency_key == idempotency_key)
        .first()
    )
    if existing_tx:
        logger.info(
            f"Idempotent credit detected for key '{idempotency_key}': "
            f"returning existing transaction #{existing_tx.id}"
        )
        wallet = (
            db.query(Wallet)
            .filter(
                Wallet.id == existing_tx.wallet_id,
                Wallet.user_id == user_id,
            )
            .first()
        )
        return wallet, existing_tx

    # 2. Row-lock wallet
    wallet = get_or_create_wallet(db, user_id=user_id, wallet_type=wallet_type, for_update=True)

    # 3. Increment balance
    new_balance = wallet.balance + amount
    wallet.balance = new_balance

    # 4. Append ledger transaction
    tx = WalletTransaction(
        wallet_id=wallet.id,
        user_id=user_id,
        wallet_type=wallet_type,
        transaction_type=WalletTransactionType.CREDIT,
        amount=amount,
        balance_after=new_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
    )
    db.add(tx)
    db.flush()

    logger.info(
        f"Credited ₹{amount} to {wallet_type.value} wallet of customer #{user_id}. "
        f"New balance: ₹{new_balance} (tx #{tx.id})"
    )
    return wallet, tx


def execute_simulated_withdrawal(
    db: Session,
    customer: User,
    wallet_type: WalletType,
    idempotency_key: Optional[str] = None,
) -> Withdrawal:
    """Execute a simulated full-balance payout and record an immutable debit transaction.

    Rules:
      - Direct Referral Wallet: Requires balance >= ₹750.00.
      - Sequential Commission Wallet: Requires completed 16/16 cycle and balance == ₹4,000.00.
      - Liquidates entire available balance; resets wallet to ₹0.00.
      - Idempotent: repeated requests with the same key return the committed withdrawal.

    Args:
        db: Active SQLAlchemy database session.
        customer: Authenticated customer entity.
        wallet_type: DIRECT_REFERRAL or SEQUENTIAL_COMMISSION.
        idempotency_key: Client-supplied or generated idempotency identifier.

    Returns:
        Completed Withdrawal instance.

    Raises:
        HTTPException 400: If withdrawal gating rules or balance thresholds are unmet.
        HTTPException 409: If a concurrent conflict arises.
    """
    key = idempotency_key.strip() if idempotency_key else f"WD-{uuid.uuid4().hex}"

    # 1. Idempotency check: if user already has a withdrawal with this key
    existing_wd = (
        db.query(Withdrawal)
        .options(joinedload(Withdrawal.wallet))
        .filter(
            Withdrawal.user_id == customer.id,
            Withdrawal.idempotency_key == key,
        )
        .first()
    )
    if existing_wd:
        existing_type = existing_wd.wallet.wallet_type if existing_wd.wallet else None
        if existing_type is None:
            w = db.query(Wallet).filter(Wallet.id == existing_wd.wallet_id).first()
            existing_type = w.wallet_type if w else None

        if existing_type != wallet_type:
            logger.warning(
                f"Idempotency key '{key}' reuse mismatch for customer #{customer.id}: "
                f"existing withdrawal #{existing_wd.id} is for {existing_type.value if existing_type else 'unknown'}, "
                f"but request is for {wallet_type.value}."
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Idempotency key '{key}' was already used for a "
                    f"{existing_type.value if existing_type else 'different'} withdrawal."
                ),
            )

        logger.info(
            f"Idempotent withdrawal detected for customer #{customer.id} with key '{key}': "
            f"returning existing withdrawal #{existing_wd.id}"
        )
        return existing_wd

    # 2. Row-lock target wallet
    wallet = get_or_create_wallet(db, user_id=customer.id, wallet_type=wallet_type, for_update=True)

    # 3. Validate category-specific gating rules
    if wallet_type == WalletType.DIRECT_REFERRAL:
        if wallet.balance < DIRECT_REFERRAL_MIN_WITHDRAWAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Minimum withdrawal balance is ₹750.",
            )
    elif wallet_type == WalletType.SEQUENTIAL_COMMISSION:
        # Check that customer has completed 16/16 commissions
        cycle = (
            db.query(CommissionCycle)
            .filter(
                CommissionCycle.beneficiary_id == customer.id,
                CommissionCycle.completed_commissions == 16,
            )
            .first()
        )
        if not cycle:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Sequential Commission withdrawal is only permitted after completing "
                    "the full 16-commission cycle."
                ),
            )
        if wallet.balance < SEQUENTIAL_CYCLE_WITHDRAWAL_AMOUNT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"No withdrawable balance available in Sequential Commission Wallet "
                    f"(required completed cycle amount: ₹{SEQUENTIAL_CYCLE_WITHDRAWAL_AMOUNT:,.2f})."
                ),
            )

    # 4. Full balance liquidation
    amount_to_withdraw = wallet.balance
    wallet.balance = ZERO_AMOUNT
    wallet.total_withdrawn += amount_to_withdraw

    now = datetime.utcnow()

    # 5. Create Withdrawal record
    try:
        withdrawal = Withdrawal(
            wallet_id=wallet.id,
            user_id=customer.id,
            amount=amount_to_withdraw,
            status=WithdrawalStatus.COMPLETED,
            idempotency_key=key,
            requested_at=now,
            completed_at=now,
        )
        withdrawal.wallet = wallet
        db.add(withdrawal)
        db.flush()

        # 6. Record immutable debit in wallet_transactions
        tx = WalletTransaction(
            wallet_id=wallet.id,
            user_id=customer.id,
            wallet_type=wallet_type,
            transaction_type=WalletTransactionType.DEBIT,
            amount=amount_to_withdraw,
            balance_after=ZERO_AMOUNT,
            reference_type=WalletReferenceType.WITHDRAWAL,
            reference_id=withdrawal.id,
            idempotency_key=f"WTX-WD-{customer.id}-{withdrawal.id}",
        )
        db.add(tx)
        db.flush()

        logger.info(
            f"Successfully executed simulated withdrawal #{withdrawal.id} for customer #{customer.id}: "
            f"₹{amount_to_withdraw} from {wallet_type.value} wallet (tx #{tx.id})"
        )
        return withdrawal

    except IntegrityError as exc:
        db.rollback()
        err_msg = str(exc)
        if "uq_withdrawals_user_idempotency" in err_msg or "idempotency_key" in err_msg:
            # Concurrent request committed with same idempotency key
            concurrent_wd = (
                db.query(Withdrawal)
                .options(joinedload(Withdrawal.wallet))
                .filter(
                    Withdrawal.user_id == customer.id,
                    Withdrawal.idempotency_key == key,
                )
                .first()
            )
            if concurrent_wd:
                c_type = concurrent_wd.wallet.wallet_type if concurrent_wd.wallet else None
                if c_type is None:
                    w = db.query(Wallet).filter(Wallet.id == concurrent_wd.wallet_id).first()
                    c_type = w.wallet_type if w else None

                if c_type != wallet_type:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Idempotency key '{key}' was already used for a "
                            f"{c_type.value if c_type else 'different'} withdrawal."
                        ),
                    )
                return concurrent_wd
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A concurrent withdrawal with this idempotency key was processed. Please refresh.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Withdrawal conflict. Please try again.",
        )
