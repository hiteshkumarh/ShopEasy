from datetime import datetime
from decimal import Decimal
import logging
from typing import Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.cashback import PlanACashbackCycle
from app.models.commission import ReferralCommission
from app.models.enums import (
    AccountStatus,
    CycleStatus,
    Programme,
    WalletReferenceType,
    WalletTransactionType,
    WalletType,
    WithdrawalStatus,
)
from app.models.queue import CommissionCycle
from app.models.user import User
from app.models.wallet import Wallet, WalletFreezeHistory, WalletTransaction, Withdrawal

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
                    is_frozen=False,
                )
                db.add(wallet)
                db.flush()
            db.refresh(wallet)
        except IntegrityError:
            # Concurrent initialization hit uq_wallets_user_type constraint.
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

    Commissions continue accruing even if the wallet is frozen (is_frozen=True).

    Args:
        db: Active SQLAlchemy database session.
        user_id: Customer recipient user ID.
        wallet_type: Target wallet category.
        amount: Positive amount to credit.
        reference_type: DIRECT_REFERRAL, SEQUENTIAL_COMMISSION, or WITHDRAWAL.
        reference_id: ID of the corresponding source record.
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

    # 2b. Re-check under row lock in case a concurrent transaction finished while waiting
    existing_tx = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.idempotency_key == idempotency_key)
        .first()
    )
    if existing_tx:
        logger.info(
            f"Idempotent credit detected under lock for key '{idempotency_key}': "
            f"returning existing transaction #{existing_tx.id}"
        )
        return wallet, existing_tx

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


def freeze_wallet(
    db: Session,
    wallet_id: int,
    admin_id: int,
    reason: str,
) -> Wallet:
    """Freeze a wallet with pessimistic locking and administrative audit log."""
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid reason is required to freeze a wallet.",
        )

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).with_for_update().first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wallet #{wallet_id} not found.",
        )

    if wallet.is_frozen:
        # Already frozen
        return wallet

    wallet.is_frozen = True
    history = WalletFreezeHistory(
        wallet_id=wallet.id,
        admin_id=admin_id,
        action="FREEZE",
        reason=reason.strip(),
    )
    db.add(history)
    db.flush()

    logger.info(f"Wallet #{wallet.id} frozen by admin #{admin_id}. Reason: {reason.strip()}")
    return wallet


def unfreeze_wallet(
    db: Session,
    wallet_id: int,
    admin_id: int,
    reason: Optional[str] = None,
) -> Wallet:
    """Unfreeze a wallet with pessimistic locking and administrative audit log."""
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).with_for_update().first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wallet #{wallet_id} not found.",
        )

    if not wallet.is_frozen:
        # Already unfrozen
        return wallet

    wallet.is_frozen = False
    history = WalletFreezeHistory(
        wallet_id=wallet.id,
        admin_id=admin_id,
        action="UNFREEZE",
        reason=reason.strip() if reason else "Admin unfreeze",
    )
    db.add(history)
    db.flush()

    logger.info(f"Wallet #{wallet.id} unfrozen by admin #{admin_id}.")

    # Notify affected distributor if Plan B (R-10)
    wallet_user = db.query(User).filter(User.id == wallet.user_id).first()
    if wallet_user and wallet_user.programme == Programme.PLAN_B:
        from app.services.notification_service import (
            NotificationEvent,
            NotificationService,
        )
        NotificationService.emit_notification(
            db=db,
            user_id=wallet_user.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_DISTRIBUTOR_WALLET_UNFROZEN,
            title="Wallet Unfrozen",
            message=f"Your wallet #{wallet.id} has been unfrozen by administrator.",
            reference_type="wallet",
            reference_id=wallet.id,
        )

    return wallet


def count_prior_successful_withdrawals(db: Session, user_id: int) -> int:
    """Count completed withdrawals for this user across all wallets."""
    return (
        db.query(func.count(Withdrawal.id))
        .filter(
            Withdrawal.user_id == user_id,
            Withdrawal.status == WithdrawalStatus.COMPLETED,
        )
        .scalar()
        or 0
    )


def execute_simulated_withdrawal(
    db: Session,
    customer: User,
    wallet_type: WalletType,
    idempotency_key: Optional[str] = None,
) -> Withdrawal:
    """Orchestrate customer withdrawal through the state machine.

    State flow:
      - Active, unfrozen distributor:
          REQUESTED -> APPROVED -> PAYOUT_PENDING -> COMPLETED
          (funds debited atomically in DB transaction, sandbox simulated receipt generated).
      - Blocked distributor:
          REQUESTED (funds remain in wallet, held for admin review, no debit yet).
      - Frozen wallet:
          HTTP 409 Conflict.
      - Gating:
          First withdrawal for user across platform requires >= ₹750.
          Subsequent withdrawals require > ₹0.
          Sequential commission wallet requires completed 16/16 cycle and >= ₹4,000.
          Full available balance liquidation only.
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
            f"returning existing withdrawal #{existing_wd.id} ({existing_wd.status.value})"
        )
        return existing_wd

    # 2. Row-lock target wallet
    wallet = get_or_create_wallet(db, user_id=customer.id, wallet_type=wallet_type, for_update=True)

    # 3. Check wallet frozen state
    if wallet.is_frozen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wallet is frozen by administrator. Withdrawals are currently blocked.",
        )

    # 4. Check available balance
    if wallet.balance <= ZERO_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No available balance to withdraw.",
        )

    # 5. Validate first-withdrawal vs subsequent threshold
    if wallet_type == WalletType.DIRECT_REFERRAL:
        successful_prior_count = count_prior_successful_withdrawals(db, customer.id)
        if successful_prior_count == 0:
            if wallet.balance < DIRECT_REFERRAL_MIN_WITHDRAWAL:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Minimum first withdrawal balance is ₹{DIRECT_REFERRAL_MIN_WITHDRAWAL:,.2f}.",
                )
    elif wallet_type == WalletType.SEQUENTIAL_COMMISSION:
        # Check Plan A Cashback Cycle (WP-10) or legacy CommissionCycle (WP-7/WP-9)
        plan_a_cycle = (
            db.query(PlanACashbackCycle)
            .filter(
                PlanACashbackCycle.recipient_user_id == customer.id,
                PlanACashbackCycle.status == "COMPLETED",
                PlanACashbackCycle.completed_contributions == 16,
            )
            .first()
        )
        legacy_cycle = (
            db.query(CommissionCycle)
            .filter(
                CommissionCycle.beneficiary_id == customer.id,
                CommissionCycle.completed_commissions == 16,
            )
            .first()
        ) if not plan_a_cycle else None

        if not plan_a_cycle and not legacy_cycle:
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

    # 6. Branch based on distributor status
    # Full liquidation amount
    amount_to_withdraw = wallet.balance
    now = datetime.utcnow()

    if customer.account_status == AccountStatus.BLOCKED:
        # Blocked distributor: record REQUESTED state; funds remain in wallet for admin review
        try:
            withdrawal = Withdrawal(
                wallet_id=wallet.id,
                user_id=customer.id,
                amount=amount_to_withdraw,
                status=WithdrawalStatus.REQUESTED,
                idempotency_key=key,
                requested_at=now,
                completed_at=None,
            )
            withdrawal.wallet = wallet
            db.add(withdrawal)
            db.flush()

            logger.info(
                f"Withdrawal #{withdrawal.id} created in REQUESTED status for BLOCKED customer #{customer.id}. "
                f"Held for administrative review."
            )

            from app.services.notification_service import (
                NotificationEvent,
                NotificationService,
            )
            if customer.programme == Programme.PLAN_B:
                NotificationService.emit_admin_notification(
                    db=db,
                    programme=Programme.PLAN_B,
                    event_type=NotificationEvent.PB_ADMIN_BLOCKED_WITHDRAWAL_REQUESTED,
                    title="Blocked Distributor Withdrawal",
                    message=f"Blocked distributor #{customer.id} requested withdrawal #{withdrawal.id} of ₹{withdrawal.amount:,.2f}.",
                    reference_type="withdrawal",
                    reference_id=withdrawal.id,
                )
            elif customer.programme == Programme.PLAN_A and wallet_type == WalletType.SEQUENTIAL_COMMISSION:
                NotificationService.emit_admin_notification(
                    db=db,
                    programme=Programme.PLAN_A,
                    event_type=NotificationEvent.PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED,
                    title="Cashback Withdrawal Request",
                    message=f"Customer #{customer.id} requested cashback withdrawal #{withdrawal.id} of ₹{withdrawal.amount:,.2f}.",
                    reference_type="withdrawal",
                    reference_id=withdrawal.id,
                )

            return withdrawal
        except IntegrityError as exc:
            db.rollback()
            return _handle_withdrawal_integrity_error(db, customer.id, key, wallet_type, exc)

    # Active customer/distributor: auto-approve and execute simulated payout
    try:
        # Liquidation: deduct wallet balance and increment total_withdrawn
        wallet.balance = ZERO_AMOUNT
        wallet.total_withdrawn += amount_to_withdraw

        receipt = f"SIM-PAYOUT-{uuid.uuid4().hex[:12].upper()}"

        withdrawal = Withdrawal(
            wallet_id=wallet.id,
            user_id=customer.id,
            amount=amount_to_withdraw,
            status=WithdrawalStatus.COMPLETED,
            idempotency_key=key,
            requested_at=now,
            completed_at=now,
            receipt_reference=receipt,
        )
        withdrawal.wallet = wallet
        db.add(withdrawal)
        db.flush()

        # Immutable debit ledger transaction
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
            f"₹{amount_to_withdraw} from {wallet_type.value} wallet (tx #{tx.id}, receipt {receipt})"
        )

        from app.services.notification_service import (
            NotificationEvent,
            NotificationService,
        )
        if customer.programme == Programme.PLAN_A and wallet_type == WalletType.SEQUENTIAL_COMMISSION:
            NotificationService.emit_admin_notification(
                db=db,
                programme=Programme.PLAN_A,
                event_type=NotificationEvent.PA_ADMIN_CASHBACK_WITHDRAWAL_REQUESTED,
                title="Cashback Withdrawal Request",
                message=f"Customer #{customer.id} requested cashback withdrawal #{withdrawal.id} of ₹{withdrawal.amount:,.2f}.",
                reference_type="withdrawal",
                reference_id=withdrawal.id,
            )
        elif customer.programme == Programme.PLAN_B:
            NotificationService.emit_notification(
                db=db,
                user_id=customer.id,
                programme=Programme.PLAN_B,
                event_type=NotificationEvent.PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS,
                title="Withdrawal Successful",
                message=f"Withdrawal #{withdrawal.id} of ₹{withdrawal.amount:,.2f} was completed successfully.",
                reference_type="withdrawal",
                reference_id=withdrawal.id,
            )

        return withdrawal

    except IntegrityError as exc:
        db.rollback()
        return _handle_withdrawal_integrity_error(db, customer.id, key, wallet_type, exc)


def admin_approve_withdrawal(
    db: Session,
    withdrawal_id: int,
    admin_id: int,
) -> Withdrawal:
    """Admin approves a REQUESTED withdrawal for a blocked distributor.

    Enforces:
      - Pessimistic row-lock on withdrawal and wallet.
      - Idempotency / race condition protection: raises HTTP 409 if status != REQUESTED.
      - Debits wallet balance.
      - Appends WalletTransaction DEBIT entry.
      - Transitions status to COMPLETED with receipt reference and admin_id.
    """
    withdrawal = (
        db.query(Withdrawal)
        .options(joinedload(Withdrawal.wallet))
        .filter(Withdrawal.id == withdrawal_id)
        .with_for_update()
        .first()
    )
    if not withdrawal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Withdrawal #{withdrawal_id} not found.",
        )

    if withdrawal.status != WithdrawalStatus.REQUESTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Withdrawal #{withdrawal_id} cannot be approved from current status: {withdrawal.status.value}.",
        )

    # Pessimistic row lock on wallet
    wallet = (
        db.query(Wallet)
        .filter(Wallet.id == withdrawal.wallet_id)
        .with_for_update()
        .first()
    )
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated wallet not found.",
        )

    if wallet.is_frozen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot approve withdrawal: Associated wallet is currently frozen.",
        )

    # Check sufficient funds
    if wallet.balance < withdrawal.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds in wallet (Available: ₹{wallet.balance}, Requested: ₹{withdrawal.amount}).",
        )

    # Debit balance
    wallet.balance -= withdrawal.amount
    wallet.total_withdrawn += withdrawal.amount

    now = datetime.utcnow()
    receipt = f"SIM-PAYOUT-{uuid.uuid4().hex[:12].upper()}"

    withdrawal.status = WithdrawalStatus.COMPLETED
    withdrawal.completed_at = now
    withdrawal.admin_id = admin_id
    withdrawal.receipt_reference = receipt
    db.flush()

    # Central administrative audit log
    from app.services.audit_service import AuditService
    AuditService.record_action(
        db=db,
        action="WITHDRAWAL_APPROVED",
        entity_type="Withdrawal",
        entity_id=withdrawal.id,
        actor_id=admin_id,
        actor_role="admin",
        old_values={"status": "REQUESTED"},
        new_values={
            "status": withdrawal.status.value,
            "receipt_reference": receipt,
        },
        metadata={
            "withdrawal_id": withdrawal.id,
            "user_id": withdrawal.user_id,
            "wallet_id": wallet.id,
            "amount": str(withdrawal.amount),
        },
    )

    # Immutable debit transaction
    tx = WalletTransaction(
        wallet_id=wallet.id,
        user_id=withdrawal.user_id,
        wallet_type=wallet.wallet_type,
        transaction_type=WalletTransactionType.DEBIT,
        amount=withdrawal.amount,
        balance_after=wallet.balance,
        reference_type=WalletReferenceType.WITHDRAWAL,
        reference_id=withdrawal.id,
        idempotency_key=f"WTX-WD-{withdrawal.user_id}-{withdrawal.id}",
    )
    db.add(tx)
    db.flush()

    logger.info(
        f"Admin #{admin_id} approved withdrawal #{withdrawal.id} for user #{withdrawal.user_id}. "
        f"Debited ₹{withdrawal.amount} (receipt: {receipt})"
    )

    # Notify affected distributor if Plan B (R-10)
    distributor = db.query(User).filter(User.id == withdrawal.user_id).first()
    if distributor and distributor.programme == Programme.PLAN_B:
        from app.services.notification_service import (
            NotificationEvent,
            NotificationService,
        )
        NotificationService.emit_notification(
            db=db,
            user_id=distributor.id,
            programme=Programme.PLAN_B,
            event_type=NotificationEvent.PB_DISTRIBUTOR_WITHDRAWAL_SUCCESS,
            title="Withdrawal Successful",
            message=f"Withdrawal #{withdrawal.id} of ₹{withdrawal.amount:,.2f} was completed successfully.",
            reference_type="withdrawal",
            reference_id=withdrawal.id,
        )

    return withdrawal


def admin_reject_withdrawal(
    db: Session,
    withdrawal_id: int,
    admin_id: int,
    reason: str,
) -> Withdrawal:
    """Admin rejects a REQUESTED withdrawal for a blocked distributor.

    Enforces:
      - Pessimistic row-lock on withdrawal row.
      - Idempotency / race condition protection: raises HTTP 409 if status != REQUESTED.
      - Funds were never debited, so no refund debit/credit needed; balance remains in wallet.
      - Transitions status to REJECTED with rejection_reason and admin_id.
    """
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid rejection reason is required.",
        )

    withdrawal = (
        db.query(Withdrawal)
        .options(joinedload(Withdrawal.wallet))
        .filter(Withdrawal.id == withdrawal_id)
        .with_for_update()
        .first()
    )
    if not withdrawal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Withdrawal #{withdrawal_id} not found.",
        )

    if withdrawal.status != WithdrawalStatus.REQUESTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Withdrawal #{withdrawal_id} cannot be rejected from current status: {withdrawal.status.value}.",
        )

    now = datetime.utcnow()
    withdrawal.status = WithdrawalStatus.REJECTED
    withdrawal.completed_at = now
    withdrawal.admin_id = admin_id
    withdrawal.rejection_reason = reason.strip()
    db.flush()

    # Central administrative audit log
    from app.services.audit_service import AuditService
    AuditService.record_action(
        db=db,
        action="WITHDRAWAL_REJECTED",
        entity_type="Withdrawal",
        entity_id=withdrawal.id,
        actor_id=admin_id,
        actor_role="admin",
        old_values={"status": "REQUESTED"},
        new_values={
            "status": "REJECTED",
            "rejection_reason": reason.strip(),
        },
        metadata={
            "withdrawal_id": withdrawal.id,
            "user_id": withdrawal.user_id,
            "wallet_id": withdrawal.wallet_id,
            "amount": str(withdrawal.amount),
        },
    )

    logger.info(
        f"Admin #{admin_id} rejected withdrawal #{withdrawal.id} for user #{withdrawal.user_id}. "
        f"Reason: {reason.strip()}"
    )
    return withdrawal


def _handle_withdrawal_integrity_error(
    db: Session,
    user_id: int,
    key: str,
    wallet_type: WalletType,
    exc: Exception,
) -> Withdrawal:
    """Helper to handle database collision gracefully."""
    err_msg = str(exc)
    if "uq_withdrawals_user_idempotency" in err_msg or "idempotency_key" in err_msg:
        concurrent_wd = (
            db.query(Withdrawal)
            .options(joinedload(Withdrawal.wallet))
            .filter(
                Withdrawal.user_id == user_id,
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
