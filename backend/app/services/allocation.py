import logging
from decimal import Decimal
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.enums import AllocationScenario, QueueStatus
from app.models.order import Order, OrderAllocation
from app.models.product import Product
from app.models.queue import BeneficiaryQueue

logger = logging.getLogger("shopeasy.allocation")

# Constants for Power Bank unit regular reserve costs (in INR)
PB_IMPORT_COST = Decimal("1500.00")
PB_OUTPUT_GST = Decimal("400.00")
PB_PACKING_COURIER = Decimal("150.00")
PB_GIFT_ACHIEVEMENT = Decimal("150.00")
PB_OFFICE_STAFF = Decimal("100.00")
PB_REGULAR_RESERVES_PER_UNIT = Decimal("2300.00")

# Order-level conditional rewards (in INR)
DIRECT_REFERRAL_REWARD_AMOUNT = Decimal("750.00")
SEQUENTIAL_COMMISSION_AMOUNT = Decimal("250.00")
ZERO_AMOUNT = Decimal("0.00")


def calculate_and_create_order_allocation(
    db: Session,
    order: Order,
    items_with_products: List[Tuple[int, Product]],
    buyer_id: int,
    is_first_successful_order: bool,
    has_valid_referral_code: bool,
) -> OrderAllocation:
    """Calculate and persist an immutable financial allocation snapshot for a confirmed order.

    Rules calibrated for initial Power Bank (₹3,999.00):
      - Power Bank regular cost reserves scale linearly with power_bank_quantity:
          Import: ₹1,500 * qty
          GST: ₹400 * qty
          Packing/courier: ₹150 * qty
          Gift/achievement: ₹150 * qty
          Office/staff: ₹100 * qty
          Total regular: ₹2,300 * qty
      - Sequential Commission (₹250.00 order-level):
          Applies only if an active beneficiary exists in the beneficiary queue,
          the buyer is NOT that active beneficiary, and the order contains an eligible product (Power Bank).
      - Direct Referral Reward (₹750.00 order-level):
          Applies when the customer places their first successful order with a valid referral code,
          regardless of product type.
      - The Four Independent Scenarios:
          Scenario A: Both apply (DR = ₹750, SC = ₹250)
          Scenario B: Sequential only (DR = ₹0, SC = ₹250)
          Scenario C: Neither applies (DR = ₹0, SC = ₹0)
          Scenario D: Direct Referral only (DR = ₹750, SC = ₹0)
      - Non-Power-Bank orders:
          Do not receive Power Bank regular cost reserves (₹0.00) or sequential commission (₹0.00).
          Eligible for Direct Referral Reward (₹750.00) on referee's first successful order.
      - Solvency:
          Total allocated must never exceed order total amount.

    Note:
      This service only computes and persists the immutable allocation snapshot.
      It does NOT credit customer wallets or advance the beneficiary queue (deferred to TASK-009).
    """
    # 1. Calculate Power Bank quantity
    power_bank_quantity = sum(
        qty for qty, prod in items_with_products if prod.is_power_bank
    )

    pb_qty_dec = Decimal(power_bank_quantity)

    # 2. Compute regular reserves
    if power_bank_quantity > 0:
        product_import_cost = PB_IMPORT_COST * pb_qty_dec
        output_gst = PB_OUTPUT_GST * pb_qty_dec
        packing_courier = PB_PACKING_COURIER * pb_qty_dec
        gift_achievement = PB_GIFT_ACHIEVEMENT * pb_qty_dec
        office_staff = PB_OFFICE_STAFF * pb_qty_dec
    else:
        product_import_cost = ZERO_AMOUNT
        output_gst = ZERO_AMOUNT
        packing_courier = ZERO_AMOUNT
        gift_achievement = ZERO_AMOUNT
        office_staff = ZERO_AMOUNT

    # 3. Determine conditional rewards
    # Direct Referral Reward (₹750.00):
    # Credited when a referred customer places their first successful order with a valid referral code,
    # regardless of product type.
    direct_referral_applies = bool(is_first_successful_order and has_valid_referral_code)

    # Sequential Commission (₹250.00):
    # The initial Power Bank automatically qualifies for sequential commission.
    # Applies only if the order contains at least one Power Bank, an active beneficiary exists in the queue,
    # and the buyer is NOT that active beneficiary.
    sequential_commission_applies = False
    if power_bank_quantity > 0:
        active_beneficiary = (
            db.query(BeneficiaryQueue)
            .filter(BeneficiaryQueue.status == QueueStatus.ACTIVE)
            .first()
        )
        if active_beneficiary is not None and active_beneficiary.user_id != buyer_id:
            sequential_commission_applies = True

    direct_referral_reward = (
        DIRECT_REFERRAL_REWARD_AMOUNT if direct_referral_applies else ZERO_AMOUNT
    )
    sequential_commission = (
        SEQUENTIAL_COMMISSION_AMOUNT if sequential_commission_applies else ZERO_AMOUNT
    )

    # 4. Map to AllocationScenario (A, B, C, D)
    if direct_referral_applies and sequential_commission_applies:
        scenario = AllocationScenario.A
    elif not direct_referral_applies and sequential_commission_applies:
        scenario = AllocationScenario.B
    elif not direct_referral_applies and not sequential_commission_applies:
        scenario = AllocationScenario.C
    else:  # direct_referral_applies and not sequential_commission_applies
        scenario = AllocationScenario.D

    # 5. Compute totals
    total_allocated = (
        product_import_cost
        + output_gst
        + packing_courier
        + gift_achievement
        + office_staff
        + direct_referral_reward
        + sequential_commission
    )
    remaining_amount = order.total_amount - total_allocated

    if remaining_amount < Decimal("0.00"):
        raise ValueError(
            f"Financial allocation insolvency: total allocated ({total_allocated}) "
            f"exceeds order total amount ({order.total_amount})."
        )

    # 6. Construct and persist OrderAllocation
    allocation = OrderAllocation(
        order_id=order.id,
        scenario=scenario,
        power_bank_quantity=power_bank_quantity,
        order_total_amount=order.total_amount,
        product_import_cost=product_import_cost,
        output_gst=output_gst,
        packing_courier=packing_courier,
        gift_achievement=gift_achievement,
        office_staff=office_staff,
        direct_referral_reward=direct_referral_reward,
        sequential_commission=sequential_commission,
        total_allocated=total_allocated,
        remaining_amount=remaining_amount,
    )
    db.add(allocation)
    db.flush()

    logger.info(
        f"Persisted OrderAllocation for order #{order.id}: scenario={scenario.value}, "
        f"pb_qty={power_bank_quantity}, total_allocated={total_allocated}, remaining={remaining_amount}"
    )

    return allocation

