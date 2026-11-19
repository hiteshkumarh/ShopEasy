"""Schemas for in-dashboard notifications (WP-11)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Programme


class NotificationResponse(BaseModel):
    """Public representation of an in-dashboard notification."""

    id: int
    programme: Programme
    event_type: str
    title: str
    message: str
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedNotifications(BaseModel):
    """Paginated list of user notifications."""

    items: List[NotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int
    total_pages: int


class NotificationMarkReadResponse(BaseModel):
    """Response after marking a notification as read."""

    status: str = "success"
    notification_id: int
    is_read: bool
    read_at: datetime


class NotificationMarkAllReadResponse(BaseModel):
    """Response after marking all notifications as read."""

    status: str = "success"
    marked_count: int

