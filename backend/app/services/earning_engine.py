from datetime import datetime
from decimal import Decimal
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.commission import ReferralCommission
from app.models.enums import WalletReferenceType, WalletType
from app.models.order import Order, OrderAllocation
from app.models.queue import QueueControl
from app.models.user import User
from app.services.queue_service import (
    enroll_customer_in_queue,
    process_sequential_commission,
)
from app.services.wallet_service import credit_wallet

logger = logging.getLogger("shopeasy.earning_engine")

DIRECT_REFERRAL_AMOUNT = Decimal("750.00")
SEQUENTIAL_COMMISSION_AMOUNT = Decimal("250.00")


def process_order_earnings(
    db: Session,
    order: Order,
    order_allocation: OrderAllocation,
    customer: User,
    queue_control: QueueControl,
    active_beneficiary_id: Optional[int],
) -> None:
    """Execute all post-order earning allocations within the checkout database transaction.

    This function must be invoked while holding the QueueControl lock.

    Operations:
      1. Direct Referral Reward:
         If order_allocation.direct_referral_reward == ₹750.00, credit referrer's Direct Referral Wallet
         and create the immutable referral_commissions record.
      2. Beneficiary Queue Enrollment:
         If order.is_first_successful_order == True, enroll the customer in the single global
         beneficiary queue (bootstrapping them as active if the queue is empty, or enqueuing as waiting).
      3. Sequential Commission:
         If order_allocation.sequential_commission == ₹250.00, credit active beneficiary's
         Sequential Commission Wallet, record sequential_commissions row, advance cycle counter,
         and rotate queue upon 16-commission completion.

    Args:
        db: Active SQLAlchemy database session.
        order: Confirmed Order instance.
        order_allocation: Persisted OrderAllocation snapshot.
        customer: Purchasing customer entity.
        queue_control: Locked QueueControl singleton instance.
        active_beneficiary_id: Beneficiary ID determined prior to allocation calculation.
    """
    now = datetime.utcnow()

    # 1. Process Direct Referral Reward (₹750.00)
    if order_allocation.direct_referral_reward == DIRECT_REFERRAL_AMOUNT:
        referrer_id = customer.referred_by_id
        if not referrer_id:
            logger.error(
                f"Order #{order.id} allocated Direct Referral Reward, but customer #{customer.id} has no referred_by_id."
            )
        else:
            # Check idempotency: ensure referee has not already generated a referral reward
            existing_ref_comm = (
                db.query(ReferralCommission)
                .filter(ReferralCommission.referee_id == customer.id)
                .first()
            )
            if not existing_ref_comm:
                ref_comm = ReferralCommission(
                    referrer_id=referrer_id,
                    referee_id=customer.id,
                    source_order_id=order.id,
                    amount=DIRECT_REFERRAL_AMOUNT,
                    created_at=now,
                )
                db.add(ref_comm)
                db.flush()

                # Credit referrer's Direct Referral Wallet
                credit_wallet(
                    db=db,
                    user_id=referrer_id,
                    wallet_type=WalletType.DIRECT_REFERRAL,
                    amount=DIRECT_REFERRAL_AMOUNT,
                    reference_type=WalletReferenceType.DIRECT_REFERRAL,
                    reference_id=ref_comm.id,
                    idempotency_key=f"DR-{order.id}-{ref_comm.id}",
                )

                logger.info(
                    f"Successfully awarded ₹750 Direct Referral Reward to referrer #{referrer_id} "
                    f"for referee #{customer.id}'s first order #{order.id}."
                )

    # 2. Process Global Beneficiary Queue Enrollment (first successful order)
    if order.is_first_successful_order:
        enroll_customer_in_queue(
            db=db,
            customer_id=customer.id,
            queue_control=queue_control,
        )

    # 3. Process Sequential Commission (₹250.00)
    if order_allocation.sequential_commission == SEQUENTIAL_COMMISSION_AMOUNT:
        if active_beneficiary_id is None:
            logger.error(
                f"Order #{order.id} allocated Sequential Commission, but active_beneficiary_id is None."
            )
        else:
            process_sequential_commission(
                db=db,
                order=order,
                active_beneficiary_id=active_beneficiary_id,
                queue_control=queue_control,
            )
