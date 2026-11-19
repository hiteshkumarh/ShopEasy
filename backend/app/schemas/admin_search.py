"""Pydantic schemas for Admin Unified Search API (WP-11 Step 4 / OR-13).

Provides schema definitions for exact-match search by Billing ID and Order ID
across Plan A and Plan B without exposing internal secrets or sensitive fields.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import Programme


class AdminSearchResultItem(BaseModel):
    """Unified representation of a search result item (Billing ID or Order)."""

    record_type: str  # "BILLING_ID" or "ORDER"
    programme: Programme  # PLAN_A or PLAN_B
    entity_id: int
    identifier: str  # billing_number or order_number
    order_id: Optional[int] = None
    order_number: Optional[str] = None
    billing_number: Optional[str] = None
    customer_id: int
    customer_name: Optional[str] = None
    status: str
    total_amount: Optional[Decimal] = None
    product_name: Optional[str] = None
    created_at: datetime
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class AdminSearchResponse(BaseModel):
    """Response payload for administrative unified search."""

    query: str
    total: int
    results: List[AdminSearchResultItem]

    model_config = ConfigDict(from_attributes=True)


class AdminPlanASearchResultItem(BaseModel):
    """Representation of a Plan A search result (Customer, Billing ID, or Queue)."""

    record_type: str  # "CUSTOMER", "BILLING_ID", "QUEUE"
    entity_id: int
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    identifier: str
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPlanASearchResponse(BaseModel):
    """Response payload for Plan A administrative search."""

    query: str
    total: int
    results: List[AdminPlanASearchResultItem]

    model_config = ConfigDict(from_attributes=True)


class AdminPlanBSearchResultItem(BaseModel):
    """Representation of a Plan B search result (Distributor, Ledger, or Commission)."""

    record_type: str  # "DISTRIBUTOR", "LEDGER", "COMMISSION"
    entity_id: int
    distributor_id: Optional[int] = None
    distributor_name: Optional[str] = None
    phone: Optional[str] = None
    sponsor_id: Optional[int] = None
    identifier: str
    status: Optional[str] = None
    amount: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPlanBSearchResponse(BaseModel):
    """Response payload for Plan B administrative search."""

    query: str
    total: int
    results: List[AdminPlanBSearchResultItem]

    model_config = ConfigDict(from_attributes=True)


