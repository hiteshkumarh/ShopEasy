import logging
import sys
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.product import Product
from app.models.queue import QueueControl
from app.models.user import User

logger = logging.getLogger("shopeasy.seed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _mask_phone(phone: str) -> str:
    """Mask phone number for safe log output."""
    if not phone:
        return "****"
    return phone[:3] + "****" + phone[-3:] if len(phone) >= 7 else "****"


def seed_admin_user(db: Session) -> Dict[str, Any]:
    """Seed the initial pre-provisioned administrator account idempotently."""
    admin_phone = settings.ADMIN_PHONE.strip()
    admin_name = settings.ADMIN_NAME.strip()
    admin_password = settings.ADMIN_PASSWORD

    if not admin_password:
        raise ValueError("ADMIN_PASSWORD must be configured in environment.")

    # 1. Search for an existing user with role ADMIN
    existing_admin = (
        db.query(User)
        .filter(User.role == UserRole.ADMIN)
        .first()
    )

    if existing_admin:
        if existing_admin.phone == admin_phone:
            logger.info(
                f"Admin account already exists (ID: {existing_admin.id}, Phone: {_mask_phone(existing_admin.phone)}). "
                "Skipping creation."
            )
        else:
            logger.warning(
                f"Admin account already exists (ID: {existing_admin.id}) with phone {_mask_phone(existing_admin.phone)}, "
                f"which differs from configured ADMIN_PHONE ({_mask_phone(admin_phone)}). "
                "Skipping creation to preserve existing admin credentials."
            )
        return {
            "action": "skipped",
            "id": existing_admin.id,
            "role": existing_admin.role.value,
            "full_name": existing_admin.full_name,
        }

    # 2. If no admin exists, check whether ADMIN_PHONE is already registered to a customer
    phone_conflict = (
        db.query(User)
        .filter(User.phone == admin_phone)
        .first()
    )

    if phone_conflict:
        raise ValueError(
            f"Cannot seed initial admin: phone number {_mask_phone(admin_phone)} is already registered "
            f"to user ID {phone_conflict.id} with role '{phone_conflict.role.value}'."
        )

    # 3. Hash password securely using bcrypt and create initial admin
    password_hash = hash_password(admin_password)

    # Invariant: Admin must have NO referral code and NO referrer
    admin_user = User(
        full_name=admin_name,
        phone=admin_phone,
        password_hash=password_hash,
        role=UserRole.ADMIN,
        referral_code=None,
        referred_by_id=None,
        is_active=True,
    )
    db.add(admin_user)
    db.flush()  # Assigns primary key within transaction

    logger.info(f"Initial Admin provisioned successfully (ID: {admin_user.id}, Phone: {_mask_phone(admin_phone)}).")

    return {
        "action": "created",
        "id": admin_user.id,
        "role": admin_user.role.value,
        "full_name": admin_user.full_name,
    }


def seed_power_bank_product(db: Session) -> Dict[str, Any]:
    """Seed the initial Power Bank purchasable product idempotently."""
    product_code = "PB-3999"

    existing_product = (
        db.query(Product)
        .filter((Product.is_power_bank == True) | (Product.product_code == product_code))  # noqa: E712
        .first()
    )

    if existing_product:
        logger.info(
            f"Initial product already exists (ID: {existing_product.id}, Code: {existing_product.product_code}, Name: {existing_product.name}). Skipping creation."
        )
        return {
            "action": "skipped",
            "id": existing_product.id,
            "name": existing_product.name,
            "price": str(existing_product.price),
            "stock": existing_product.stock,
        }

    power_bank = Product(
        name="Power Bank",
        description="High-capacity 20,000mAh Power Bank with dual USB-C Power Delivery and fast charging.",
        price=Decimal("3999.00"),
        stock=1000,
        image_url="assets/products/power-bank.jpg",
        is_active=True,
        is_power_bank=True,
        product_code=product_code,
    )
    db.add(power_bank)
    db.flush()

    logger.info(
        f"Initial Power Bank product provisioned successfully (ID: {power_bank.id}, Price: Rs. {power_bank.price}, Stock: {power_bank.stock})."
    )

    return {
        "action": "created",
        "id": power_bank.id,
        "name": power_bank.name,
        "price": str(power_bank.price),
        "stock": power_bank.stock,
    }


def seed_queue_control(db: Session) -> Dict[str, Any]:
    """Seed the singleton queue controller record (id=1) idempotently."""
    existing_qc = db.query(QueueControl).filter(QueueControl.id == 1).first()

    if existing_qc:
        logger.info(f"QueueControl singleton already exists (ID: {existing_qc.id}). Skipping creation.")
        return {
            "action": "skipped",
            "id": existing_qc.id,
            "last_allocated_position": existing_qc.last_allocated_position,
        }

    queue_control = QueueControl(
        id=1,
        active_cycle_id=None,
        active_beneficiary_id=None,
        active_cycle_status=None,
        last_allocated_position=0,
    )
    db.add(queue_control)
    db.flush()

    logger.info("QueueControl singleton initialized successfully (ID: 1, last_allocated_position: 0).")

    return {
        "action": "created",
        "id": queue_control.id,
        "last_allocated_position": queue_control.last_allocated_position,
    }


def seed_baseline_data(db: Session) -> Dict[str, Any]:
    """Execute all baseline seed operations within a single database transaction."""
    logger.info("Beginning baseline data seeding transaction...")
    admin_result = seed_admin_user(db)
    product_result = seed_power_bank_product(db)
    qc_result = seed_queue_control(db)

    db.commit()
    logger.info("Baseline data seeding transaction committed successfully.")

    return {
        "admin": admin_result,
        "product": product_result,
        "queue_control": qc_result,
    }


def main():
    """CLI entrypoint to execute baseline seeding."""
    db = SessionLocal()
    try:
        results = seed_baseline_data(db)
        logger.info(f"Seeding completed. Summary: {results}")
    except Exception as exc:
        db.rollback()
        logger.error(f"Seeding transaction failed and rolled back: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
