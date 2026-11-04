"""Pydantic schemas and data validation models."""

from app.schemas.address import (
    AddressCreateRequest,
    AddressResponse,
    AddressUpdateRequest,
)
from app.schemas.auth import (
    AdminMFAVerifyRequest,
    AdminOTPRequest,
    AdminOTPVerifyRequest,
    AdminPasswordLoginRequest,
    AuthUserResponse,
    CustomerOTPRequest,
    CustomerOTPVerifyRequest,
    CustomerPasswordLoginRequest,
    CustomerPasswordResetConfirmRequest,
    CustomerPasswordResetRequest,
    CustomerRegisterRequest,
    CustomerRegisterResponse,
    MFARequiredResponse,
    TokenResponse,
)
from app.schemas.cart import (
    CartItemAddRequest,
    CartItemResponse,
    CartItemUpdateRequest,
    CartResponse,
)
from app.schemas.order import (
    CheckoutRequest,
    OrderAllocationResponse,
    OrderItemResponse,
    OrderListResponse,
    OrderResponse,
)
from app.schemas.product import (
    ProductCreateRequest,
    ProductListResponse,
    ProductResponse,
    ProductUpdateRequest,
)

__all__ = [
    # Address
    "AddressCreateRequest",
    "AddressResponse",
    "AddressUpdateRequest",
    # Auth
    "AdminMFAVerifyRequest",
    "AdminOTPRequest",
    "AdminOTPVerifyRequest",
    "AdminPasswordLoginRequest",
    "AuthUserResponse",
    "CustomerOTPRequest",
    "CustomerOTPVerifyRequest",
    "CustomerPasswordLoginRequest",
    "CustomerPasswordResetConfirmRequest",
    "CustomerPasswordResetRequest",
    "CustomerRegisterRequest",
    "CustomerRegisterResponse",
    "MFARequiredResponse",
    "TokenResponse",
    # Cart
    "CartItemAddRequest",
    "CartItemResponse",
    "CartItemUpdateRequest",
    "CartResponse",
    # Order
    "CheckoutRequest",
    "OrderAllocationResponse",
    "OrderItemResponse",
    "OrderListResponse",
    "OrderResponse",
    # Product
    "ProductCreateRequest",
    "ProductListResponse",
    "ProductResponse",
    "ProductUpdateRequest",
]
