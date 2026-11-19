"""Admin API router for Financial Configuration (WP-11 Step 4 / AD-06 / ED-02).

Exposes:
- GET /admin/financial-settings: Query financial settings with optional filters (programme, is_active, as_of).
- POST /admin/financial-settings: Create or prospectively update a financial setting with mandatory audit logging.

Security & Invariants:
- Strictly requires administrator privileges (require_admin).
- Enforces prospective effective dates per ED-02 (past effective dates strictly rejected with HTTP 400).
- Maintains monotonic versioning and closes superseded versions at effective_from.
- Records immutable audit actions via AuditService before response delivery.
- Does not expose internal sensitive fields or secrets.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.models.enums import Programme
from app.models.financial_settings import FinancialSetting
from app.models.user import User
from app.schemas.financial_settings import (
    FinancialSettingListResponse,
    FinancialSettingResponse,
    FinancialSettingUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.financial_settings import (
    FinancialSettingsService,
    FinancialSettingValidationError,
    SettingAlreadyExistsError,
    SettingConcurrencyError,
    SettingNotFoundError,
)

logger = logging.getLogger("shopeasy.admin.financial_settings")

router = APIRouter(
    prefix="/admin/financial-settings",
    tags=["Admin Financial Settings"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=FinancialSettingListResponse,
    summary="List financial settings with filtering and historical resolution (Admin only)",
)
def get_financial_settings(
    programme: Optional[Programme] = Query(None, description="Filter by programme (PLAN_A or PLAN_B)"),
    setting_key: Optional[str] = Query(None, description="Filter by exact setting key"),
    is_active: Optional[bool] = Query(None, description="Filter active/inactive settings"),
    as_of: Optional[datetime] = Query(None, description="Historical timestamp to resolve active settings as of that time"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Page size"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FinancialSettingListResponse:
    """Retrieve financial settings with optional filters.

    If `as_of` is supplied, filters settings whose effective window covers the requested timestamp.
    Otherwise, applies standard programme, setting_key, and is_active filters.
    """
    query = db.query(FinancialSetting)

    if programme is not None:
        query = query.filter(FinancialSetting.programme == programme)

    if setting_key:
        query = query.filter(FinancialSetting.setting_key == setting_key.strip().upper())

    if as_of is not None:
        as_of_naive = as_of.replace(tzinfo=None) if as_of.tzinfo else as_of
        query = query.filter(
            FinancialSetting.effective_from <= as_of_naive,
            or_(
                FinancialSetting.effective_to.is_(None),
                FinancialSetting.effective_to > as_of_naive,
            ),
        )
    elif is_active is not None:
        query = query.filter(FinancialSetting.is_active == is_active)

    total = query.count()
    items = (
        query.order_by(
            FinancialSetting.programme.asc(),
            FinancialSetting.setting_key.asc(),
            FinancialSetting.version.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return FinancialSettingListResponse(total=total, items=items)


@router.post(
    "",
    response_model=FinancialSettingResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or prospectively update a financial setting (Admin only)",
)
def update_or_create_financial_setting(
    payload: FinancialSettingUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FinancialSettingResponse:
    """Create or prospectively update a versioned financial setting.

    Invariants:
      - Admin authorization required (HTTP 401 unauthenticated, HTTP 403 non-admin).
      - Prospective validation: effective_from must not be in the past per ED-02.
      - Monotonic versioning: if setting exists, increments version and supersedes previous version.
      - Immutable audit trail: records action and change reason via AuditService.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Enforce ED-02: Past effective dates are rejected
    if payload.effective_from is not None:
        eff_from_naive = (
            payload.effective_from.replace(tzinfo=None)
            if payload.effective_from.tzinfo
            else payload.effective_from
        )
        # Allow small 5-second leeway for network transit, but strictly reject past timestamps
        if eff_from_naive < (now - timedelta(seconds=5)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Effective date must be prospective (current or future timestamp). Past effective dates are prohibited per ED-02.",
            )
    else:
        eff_from_naive = now

    eff_to_naive = (
        payload.effective_to.replace(tzinfo=None)
        if payload.effective_to and payload.effective_to.tzinfo
        else payload.effective_to
    )

    if eff_to_naive is not None and eff_to_naive <= eff_from_naive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_to must be strictly after effective_from.",
        )

    service = FinancialSettingsService(db)
    existing = service.get_or_none(programme=payload.programme, setting_key=payload.setting_key)

    try:
        if existing is None:
            new_setting = service.create(
                programme=payload.programme,
                setting_key=payload.setting_key,
                setting_value=payload.setting_value,
                effective_from=eff_from_naive,
                effective_to=eff_to_naive,
                currency=payload.currency,
                description=payload.description,
                created_by_id=current_admin.id,
                reason=payload.change_reason,
            )
            action = "CREATE_FINANCIAL_SETTING"
            old_values = None
        else:
            old_values = {
                "setting_value": str(existing.setting_value),
                "version": existing.version,
                "effective_from": existing.effective_from.isoformat() if existing.effective_from else None,
                "effective_to": existing.effective_to.isoformat() if existing.effective_to else None,
            }
            new_setting = service.update(
                programme=payload.programme,
                setting_key=payload.setting_key,
                new_value=payload.setting_value,
                effective_from=eff_from_naive,
                effective_to=eff_to_naive,
                currency=payload.currency,
                description=payload.description,
                changed_by_id=current_admin.id,
                reason=payload.change_reason,
            )
            action = "UPDATE_FINANCIAL_SETTING"

        # Record system audit trail using AuditService
        new_values = {
            "setting_value": str(new_setting.setting_value),
            "version": new_setting.version,
            "effective_from": new_setting.effective_from.isoformat() if new_setting.effective_from else None,
            "effective_to": new_setting.effective_to.isoformat() if new_setting.effective_to else None,
        }
        metadata = {
            "programme": payload.programme.value if hasattr(payload.programme, "value") else str(payload.programme),
            "setting_key": payload.setting_key,
            "change_reason": payload.change_reason,
        }

        AuditService.record_action(
            db=db,
            action=action,
            entity_type="FinancialSetting",
            entity_id=new_setting.id,
            actor_id=current_admin.id,
            actor_role="admin",
            old_values=old_values,
            new_values=new_values,
            metadata=metadata,
        )
        db.commit()
        db.refresh(new_setting)

        return new_setting

    except FinancialSettingValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except SettingAlreadyExistsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except SettingConcurrencyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except SettingNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to update financial setting: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update financial setting.",
        )
