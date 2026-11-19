"""In-dashboard Notification API router for Arya Global Digital (WP-11)."""

from datetime import datetime, timezone
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.enums import Programme, UserRole
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import (
    NotificationMarkAllReadResponse,
    NotificationMarkReadResponse,
    NotificationResponse,
    PaginatedNotifications,
)

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=PaginatedNotifications, summary="List notifications for current user")
def list_my_notifications(
    programme: Optional[Programme] = Query(None, description="Optional programme filter (Admin only)"),
    is_read: Optional[bool] = Query(None, description="Filter by read/unread status"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedNotifications:
    """Retrieve paginated in-dashboard alerts scoped strictly to the authenticated user."""
    # 1. Base query strictly scoped to current user ownership
    query = db.query(Notification).filter(Notification.user_id == current_user.id)

    # 2. Programme isolation: non-admins are locked to their registered programme
    if current_user.role != UserRole.ADMIN:
        query = query.filter(Notification.programme == current_user.programme)
    elif programme is not None:
        query = query.filter(Notification.programme == programme)

    # 3. Read status filter
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)

    total = query.count()
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
    )
    if current_user.role != UserRole.ADMIN:
        unread_count = unread_count.filter(Notification.programme == current_user.programme)
    unread_total = unread_count.count()

    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size

    notifications = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [NotificationResponse.model_validate(n) for n in notifications]

    return PaginatedNotifications(
        items=items,
        total=total,
        unread_count=unread_total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{notification_id}", response_model=NotificationResponse, summary="Get single notification")
def get_my_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationResponse:
    """Retrieve an individual notification verifying strict current-user ownership."""
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .first()
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    # Enforce programme boundary for non-admin callers
    if current_user.role != UserRole.ADMIN and notification.programme != current_user.programme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    return NotificationResponse.model_validate(notification)


@router.post("/{notification_id}/read", response_model=NotificationMarkReadResponse, summary="Mark single notification as read")
def mark_notification_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationMarkReadResponse:
    """Mark an individual notification as read with ownership verification."""
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .first()
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    now = datetime.now(timezone.utc)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = now
        db.commit()
    else:
        now = notification.read_at or now

    return NotificationMarkReadResponse(
        status="success",
        notification_id=notification.id,
        is_read=True,
        read_at=now,
    )


@router.post("/read-all", response_model=NotificationMarkAllReadResponse, summary="Mark all notifications as read")
def mark_all_notifications_as_read(
    programme: Optional[Programme] = Query(None, description="Optional programme filter (Admin only)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationMarkAllReadResponse:
    """Mark all unread notifications belonging to the current user as read."""
    query = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )
    )

    if current_user.role != UserRole.ADMIN:
        query = query.filter(Notification.programme == current_user.programme)
    elif programme is not None:
        query = query.filter(Notification.programme == programme)

    now = datetime.now(timezone.utc)
    updated_count = query.update(
        {"is_read": True, "read_at": now},
        synchronize_session=False,
    )
    db.commit()

    return NotificationMarkAllReadResponse(
        status="success",
        marked_count=updated_count,
    )

