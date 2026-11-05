"""Safely inspect or remove ShopEasy manual test data.

Dry-run is the default. Pass ``--execute`` only after reviewing the report.
This utility is intentionally scoped to the supplied test phone numbers and
the exact PB-3999 Power Bank candidate; it fails closed on ambiguous/shared
relationships and never targets admin users or queue_control.
"""

import argparse
from collections import OrderedDict
from typing import Iterable

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.cart import CartItem
from app.models.commission import ReferralCommission, SequentialCommission
from app.models.order import Order, OrderAllocation, OrderItem
from app.models.product import Product
from app.models.queue import BeneficiaryQueue, CommissionCycle, QueueControl
from app.models.user import Address, OTP, User
from app.models.wallet import Wallet, WalletTransaction, Withdrawal
from app.models.enums import UserRole


TARGET_PHONES = tuple(str(number) for number in range(9019443501, 9019443521))
TARGET_HOST = "mysql"
TARGET_DATABASE = "shopeasy_db"
POWER_BANK_CODE = "PB-3999"


def _ids(values: Iterable[tuple[int]]) -> set[int]:
    return {row[0] for row in values}


def collect_targets(db: Session) -> dict[str, set[int]]:
    """Collect only test-owned IDs and fail closed on shared/ambiguous data."""
    configured_host = (settings.DB_HOST or "").strip().lower()
    if configured_host != TARGET_HOST:
        raise RuntimeError(
            "Refusing cleanup: DB_HOST must be the Docker MySQL service 'mysql'."
        )
    if settings.DATABASE_URL:
        raise RuntimeError(
            "Refusing cleanup: DATABASE_URL/MYSQL_URL override is not allowed."
        )
    if settings.DB_NAME != TARGET_DATABASE:
        raise RuntimeError(
            "Refusing cleanup: configured database must be shopeasy_db."
        )

    selected = db.execute(text("SELECT DATABASE()")).scalar_one()
    if selected != TARGET_DATABASE:
        raise RuntimeError("Refusing cleanup: selected database is not shopeasy_db.")

    users = db.execute(
        select(User.id, User.phone, User.role, User.referred_by_id).where(
            User.phone.in_(TARGET_PHONES)
        )
    ).all()
    if any(user.role == UserRole.ADMIN for user in users):
        raise RuntimeError("Refusing cleanup: a target phone belongs to an admin.")

    user_ids = {user.id for user in users}
    unrelated_referrals = db.scalars(
        select(User.id).where(
            User.referred_by_id.in_(user_ids),
            User.id.not_in(user_ids),
        )
    ).all() if user_ids else []
    if unrelated_referrals:
        raise RuntimeError(
            "Refusing cleanup: unrelated users refer to a target user."
        )

    addresses = _ids(db.execute(select(Address.id).where(Address.user_id.in_(user_ids))).all()) if user_ids else set()
    orders = _ids(
        db.execute(
            select(Order.id).where(
                (Order.user_id.in_(user_ids)) | (Order.address_id.in_(addresses))
            )
        ).all()
    ) if user_ids or addresses else set()
    shared_address_orders = db.scalars(
        select(Order.id).where(
            Order.address_id.in_(addresses),
            Order.user_id.not_in(user_ids),
        )
    ).all() if addresses else []
    if shared_address_orders:
        raise RuntimeError(
            "Refusing cleanup: a target address is used by an unrelated order."
        )
    queue_entries = _ids(db.execute(select(BeneficiaryQueue.id).where(BeneficiaryQueue.user_id.in_(user_ids))).all()) if user_ids else set()
    cycles = _ids(db.execute(select(CommissionCycle.id).where(CommissionCycle.beneficiary_id.in_(user_ids))).all()) if user_ids else set()
    wallets = _ids(db.execute(select(Wallet.id).where(Wallet.user_id.in_(user_ids))).all()) if user_ids else set()

    shared_queue_cycles = db.scalars(
        select(CommissionCycle.id).where(
            CommissionCycle.queue_entry_id.in_(queue_entries),
            CommissionCycle.beneficiary_id.not_in(user_ids),
        )
    ).all() if queue_entries else []
    if shared_queue_cycles:
        raise RuntimeError(
            "Refusing cleanup: a target queue entry is used by an unrelated cycle."
        )

    active_queue_control = db.scalars(
        select(QueueControl).where(QueueControl.id == 1)
    ).first()
    if active_queue_control and active_queue_control.active_cycle_id in cycles:
        if active_queue_control.active_beneficiary_id not in user_ids or active_queue_control.active_cycle_status != "active":
            raise RuntimeError(
                "Refusing cleanup: queue_control active pointers do not match the target active cycle."
            )

    target_orders = orders
    shared_cycle_orders = db.scalars(
        select(SequentialCommission.id).where(
            SequentialCommission.cycle_id.in_(cycles),
            SequentialCommission.source_order_id.not_in(target_orders),
        )
    ).all() if cycles and target_orders else []
    if cycles and not target_orders:
        shared_cycle_orders = db.scalars(
            select(SequentialCommission.id).where(
                SequentialCommission.cycle_id.in_(cycles)
            )
        ).all()
    if shared_cycle_orders:
        raise RuntimeError(
            "Refusing cleanup: a target commission cycle contains unrelated orders."
        )

    product_rows = db.scalars(
        select(Product).where(
            (Product.product_code == POWER_BANK_CODE)
            | ((Product.name == "Power Bank") & (Product.is_power_bank.is_(True)))
        )
    ).all()
    if len(product_rows) > 1:
        raise RuntimeError("Refusing cleanup: multiple Power Bank candidates found.")
    product_ids = {product_rows[0].id} if product_rows else set()

    product_order_items = db.scalars(
        select(OrderItem.id).where(OrderItem.product_id.in_(product_ids))
    ).all() if product_ids else []
    product_cart_items = db.scalars(
        select(CartItem.id).where(CartItem.product_id.in_(product_ids))
    ).all() if product_ids else []
    if product_ids:
        shared_product_orders = db.scalars(
            select(OrderItem.id).where(
                OrderItem.product_id.in_(product_ids),
                OrderItem.order_id.not_in(orders),
            )
        ).all()
        shared_product_carts = db.scalars(
            select(CartItem.id).where(
                CartItem.product_id.in_(product_ids),
                CartItem.user_id.not_in(user_ids),
            )
        ).all()
        if shared_product_orders or shared_product_carts:
            raise RuntimeError(
                "Refusing cleanup: Power Bank is referenced by unrelated data."
            )

    return {
        "users": user_ids,
        "addresses": addresses,
        "orders": orders,
        "queue_entries": queue_entries,
        "cycles": cycles,
        "wallets": wallets,
        "products": product_ids,
        "order_items": set(product_order_items),
        "cart_items": set(product_cart_items),
        "queue_control_reset": {
            active_queue_control.id
            for _ in [0]
            if active_queue_control and active_queue_control.active_cycle_id in cycles
        },
    }


def build_counts(db: Session, targets: dict[str, set[int]]) -> OrderedDict[str, int]:
    """Return the rows that the guarded delete plan would target."""
    users = targets["users"]
    addresses = targets["addresses"]
    orders = targets["orders"]
    queue_entries = targets["queue_entries"]
    cycles = targets["cycles"]
    wallets = targets["wallets"]
    products = targets["products"]
    queue_control_reset = targets["queue_control_reset"]
    counts: OrderedDict[str, int] = OrderedDict()

    counts["otps"] = db.scalar(select(func.count()).select_from(OTP).where(OTP.phone.in_(TARGET_PHONES)))
    counts["wallet_transactions"] = db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.wallet_id.in_(wallets))) if wallets else 0
    counts["withdrawals"] = db.scalar(select(func.count()).select_from(Withdrawal).where(Withdrawal.wallet_id.in_(wallets))) if wallets else 0
    counts["sequential_commissions"] = db.scalar(select(func.count()).select_from(SequentialCommission).where((SequentialCommission.beneficiary_id.in_(users)) | SequentialCommission.cycle_id.in_(cycles) | SequentialCommission.source_order_id.in_(orders))) if users or cycles or orders else 0
    counts["referral_commissions"] = db.scalar(select(func.count()).select_from(ReferralCommission).where((ReferralCommission.referrer_id.in_(users)) | ReferralCommission.referee_id.in_(users) | ReferralCommission.source_order_id.in_(orders))) if users or orders else 0
    counts["order_items"] = db.scalar(select(func.count()).select_from(OrderItem).where((OrderItem.order_id.in_(orders)) | OrderItem.product_id.in_(products))) if orders or products else 0
    counts["order_allocations"] = db.scalar(select(func.count()).select_from(OrderAllocation).where(OrderAllocation.order_id.in_(orders))) if orders else 0
    counts["orders"] = len(orders)
    counts["cart_items"] = db.scalar(select(func.count()).select_from(CartItem).where((CartItem.user_id.in_(users)) | (CartItem.product_id.in_(products)))) if users or products else 0
    counts["commission_cycles"] = len(cycles)
    counts["beneficiary_queue"] = len(queue_entries)
    counts["addresses"] = len(addresses)
    counts["wallets"] = len(wallets)
    counts["products"] = len(products)
    counts["users"] = len(users)
    counts["queue_control_reset"] = len(queue_control_reset)
    return counts


def delete_targets(db: Session, targets: dict[str, set[int]]) -> None:
    """Delete only collected IDs in child-before-parent foreign-key order."""
    users = targets["users"]
    addresses = targets["addresses"]
    orders = targets["orders"]
    queue_entries = targets["queue_entries"]
    cycles = targets["cycles"]
    wallets = targets["wallets"]
    products = targets["products"]
    queue_control_reset = targets["queue_control_reset"]

    if queue_control_reset:
        remaining_queue_entries = db.scalar(
            select(func.count()).select_from(BeneficiaryQueue).where(
                BeneficiaryQueue.id.not_in(queue_entries)
            )
        )
        db.execute(
            update(QueueControl)
            .where(
                QueueControl.id == 1,
                QueueControl.active_cycle_id.in_(cycles),
                QueueControl.active_beneficiary_id.in_(users),
                QueueControl.active_cycle_status == "active",
            )
            .values(
                active_cycle_id=None,
                active_beneficiary_id=None,
                active_cycle_status=None,
                last_allocated_position=0 if remaining_queue_entries == 0 else QueueControl.last_allocated_position,
                updated_at=func.now(),
            )
        )

    db.execute(delete(OTP).where(OTP.phone.in_(TARGET_PHONES)))
    if wallets:
        db.execute(delete(WalletTransaction).where(WalletTransaction.wallet_id.in_(wallets)))
        db.execute(delete(Withdrawal).where(Withdrawal.wallet_id.in_(wallets)))
    if users or cycles or orders:
        db.execute(delete(SequentialCommission).where((SequentialCommission.beneficiary_id.in_(users)) | SequentialCommission.cycle_id.in_(cycles) | SequentialCommission.source_order_id.in_(orders)))
    if users or orders:
        db.execute(delete(ReferralCommission).where((ReferralCommission.referrer_id.in_(users)) | ReferralCommission.referee_id.in_(users) | ReferralCommission.source_order_id.in_(orders)))
    if orders or products:
        db.execute(delete(OrderItem).where((OrderItem.order_id.in_(orders)) | OrderItem.product_id.in_(products)))
    if orders:
        db.execute(delete(OrderAllocation).where(OrderAllocation.order_id.in_(orders)))
        db.execute(delete(Order).where(Order.id.in_(orders)))
    if users or products:
        db.execute(delete(CartItem).where(CartItem.user_id.in_(users) | CartItem.product_id.in_(products)))
    if cycles:
        db.execute(delete(CommissionCycle).where(CommissionCycle.id.in_(cycles)))
    if queue_entries:
        db.execute(delete(BeneficiaryQueue).where(BeneficiaryQueue.id.in_(queue_entries)))
    if addresses:
        db.execute(delete(Address).where(Address.id.in_(addresses)))
    if wallets:
        db.execute(delete(Wallet).where(Wallet.id.in_(wallets)))
    if products:
        db.execute(delete(Product).where(Product.id.in_(products)))
    if users:
        # Break only target-to-target self-referral links before deleting users.
        db.execute(
            update(User)
            .where(User.id.in_(users))
            .values(referred_by_id=None)
        )
        db.execute(delete(User).where(User.id.in_(users), User.role != UserRole.ADMIN))


def preserved_counts(db: Session) -> dict[str, int | str | None]:
    """Return protected state that must remain unchanged."""
    return {
        "admin_users": db.scalar(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        ),
        "queue_control_id_1": db.scalar(
            select(func.count()).select_from(QueueControl).where(QueueControl.id == 1)
        ),
        "alembic_revision": db.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="commit the guarded cleanup")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        targets = collect_targets(db)
        counts = build_counts(db, targets)
        before_preserved = preserved_counts(db)
        print("Cleanup mode:", "EXECUTE" if args.execute else "DRY RUN")
        print("Selected database: shopeasy_db")
        for table, count in counts.items():
            print(f"before {table}: {count}")
        print("before preserved:", before_preserved)
        if args.execute:
            delete_targets(db, targets)
            db.commit()
            after_targets = collect_targets(db)
            after_counts = build_counts(db, after_targets)
            after_preserved = preserved_counts(db)
            for table, count in after_counts.items():
                print(f"after {table}: {count}")
            print("after preserved:", after_preserved)
            print("Cleanup committed.")
        else:
            db.rollback()
            print("No changes made. Review the report, then rerun with --execute only after approval.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
