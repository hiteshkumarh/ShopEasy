import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_customer
from app.core.database import get_db
from app.models.user import Address, User
from app.schemas.address import (
    AddressCreateRequest,
    AddressResponse,
    AddressUpdateRequest,
)

logger = logging.getLogger("shopeasy.addresses")

router = APIRouter(prefix="/addresses", tags=["Addresses"])


@router.get("", response_model=List[AddressResponse])
def list_addresses(
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Retrieve all delivery addresses registered by the authenticated customer."""
    addresses = (
        db.query(Address)
        .filter(Address.user_id == current_user.id)
        .order_by(Address.is_default.desc(), Address.id.asc())
        .all()
    )
    return addresses


@router.post("", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def create_address(
    payload: AddressCreateRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Create a new delivery address for the authenticated customer."""
    # Count existing addresses for this customer
    existing_count = (
        db.query(Address.id)
        .filter(Address.user_id == current_user.id)
        .count()
    )

    # First address is automatically set as default; otherwise respect requested flag
    is_default = payload.is_default or (existing_count == 0)

    if is_default:
        # Unset default flag on existing addresses
        db.query(Address).filter(
            Address.user_id == current_user.id,
            Address.is_default == True,  # noqa: E712
        ).update({"is_default": False})

    new_address = Address(
        user_id=current_user.id,
        recipient_name=payload.recipient_name.strip(),
        phone=payload.phone.strip(),
        address_line1=payload.address_line1.strip(),
        address_line2=payload.address_line2.strip() if payload.address_line2 else None,
        city=payload.city.strip(),
        state=payload.state.strip(),
        pincode=payload.pincode.strip(),
        is_default=is_default,
    )
    db.add(new_address)
    db.commit()
    db.refresh(new_address)

    logger.info(f"Created address #{new_address.id} for user #{current_user.id}")
    return new_address


@router.put("/{address_id}", response_model=AddressResponse)
def update_address(
    address_id: int,
    payload: AddressUpdateRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Update an existing delivery address belonging to the authenticated customer."""
    address = (
        db.query(Address)
        .filter(
            Address.id == address_id,
            Address.user_id == current_user.id,
        )
        .first()
    )
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("is_default") is True:
        # Unset other default addresses for this customer
        db.query(Address).filter(
            Address.user_id == current_user.id,
            Address.id != address.id,
            Address.is_default == True,  # noqa: E712
        ).update({"is_default": False})

    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(address, field, value)

    db.commit()
    db.refresh(address)

    logger.info(f"Updated address #{address.id} for user #{current_user.id}")
    return address


@router.delete("/{address_id}")
def delete_address(
    address_id: int,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    """Delete a delivery address belonging to the authenticated customer."""
    address = (
        db.query(Address)
        .filter(
            Address.id == address_id,
            Address.user_id == current_user.id,
        )
        .first()
    )
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    # Check if this address is associated with any confirmed orders
    if address.orders:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete an address associated with existing orders.",
        )

    db.delete(address)
    db.commit()

    logger.info(f"Deleted address #{address_id} for user #{current_user.id}")
    return {"message": "Address deleted successfully."}

