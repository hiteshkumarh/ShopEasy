"""Financial Settings Service and Version Management.

This service manages versioned, effective-dated financial configurations for
Arya Global Digital's dual-programme platform (Plan A, Plan B, and Legacy).

Design Safeguards:
  1. Historical Effective-Date Resolution:
     Half-open interval [effective_from, effective_to):
     effective_from is inclusive (<=), effective_to is exclusive (>).
     Inactive or superseded historical versions remain resolvable for their valid timeframes.
     Multiple matching versions are rejected as data integrity violations.
  2. Concurrency and Version Management:
     Guarantees atomicity of setting version and audit history creation.
     Employs a bounded retry policy with transaction rollback and committed-state
     re-query when version uniqueness collisions occur under concurrent writers.
  3. Strict Financial Precision:
     Integrates with the Money value object and Decimal arithmetic.
     Rejects binary floats, non-finite values (NaN, Inf), negative amounts where prohibited,
     and values with fractional paise/sub-unit precision exceeding DB numeric scale (18, 6).
  4. Audit Integrity:
     Every successful lifecycle event (CREATED, UPDATED, DEACTIVATED, REACTIVATED)
     records an immutable FinancialSettingHistory row in the same transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.money import Money, _parse_decimal
from app.models.enums import Programme, SettingAction
from app.models.financial_settings import FinancialSetting, FinancialSettingHistory

logger = logging.getLogger("shopeasy.financial_settings")

# Maximum database numeric bounds for NUMERIC(18, 6)
MAX_SCALE = 6
SCALE_FACTOR = Decimal("0.000001")
MAX_INTEGER_DIGITS = 12
MAX_NUMERIC_VALUE = Decimal("1000000000000")  # 10^12

# Bounded retry limit for concurrent version collisions
DEFAULT_MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------


class FinancialSettingError(Exception):
    """Base exception for all financial settings operations."""
    pass


class SettingNotFoundError(FinancialSettingError):
    """Raised when a requested financial setting or historical version cannot be found."""
    pass


class SettingAlreadyExistsError(FinancialSettingError):
    """Raised when attempting to create a first version for a setting that already exists."""
    pass


class MultipleMatchingSettingsError(FinancialSettingError):
    """Raised when multiple setting versions match a single transaction timestamp (data integrity issue)."""
    pass


class FinancialSettingValidationError(FinancialSettingError, ValueError):
    """Raised when setting value, dates, or parameters fail domain validation rules."""
    pass


class SettingConcurrencyError(FinancialSettingError):
    """Raised when concurrent version collisions exceed the bounded retry limit."""
    pass


class SettingKey:
    """Canonical financial setting keys across programmes."""

    # Plan A commission & cashback
    COMMISSION_GROSS = "COMMISSION_GROSS"
    OP_COST_RATE = "OP_COST_RATE"
    TDS_RATE = "TDS_RATE"
    CASHBACK_PER_UNIT = "CASHBACK_PER_UNIT"
    CASHBACK_CYCLE_TARGET = "CASHBACK_CYCLE_TARGET"

    # Plan A PA-24 Unit Allocation expense & reserve components
    ALLOC_PRODUCT_IMPORT = "ALLOC_PRODUCT_IMPORT"
    ALLOC_GST_RESERVE = "ALLOC_GST_RESERVE"
    ALLOC_PACKING_COURIER = "ALLOC_PACKING_COURIER"
    ALLOC_GIFT_FUND = "ALLOC_GIFT_FUND"
    ALLOC_OFFICE_STAFF = "ALLOC_OFFICE_STAFF"

    # Plan B commissions & deductions
    DIRECT_COMMISSION_GROSS = "DIRECT_COMMISSION_GROSS"
    GENERATION_COMMISSION_GROSS = "GENERATION_COMMISSION_GROSS"


@dataclass(frozen=True)
class CanonicalSettingDefinition:
    """Immutable specification for a baseline canonical financial setting."""

    programme: Programme
    setting_key: str
    setting_value: Decimal
    currency: str = "INR"
    description: str = ""


CANONICAL_SETTINGS: Tuple[CanonicalSettingDefinition, ...] = (
    # -----------------------------------------------------------------------
    # Plan A Canonical Settings (PRD §3, §6, §8, §15, §26)
    # -----------------------------------------------------------------------
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.COMMISSION_GROSS,
        setting_value=Decimal("750.000000"),
        description="Plan A gross referral commission pool per eligible Billing ID",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.OP_COST_RATE,
        setting_value=Decimal("0.046667"),
        description="Plan A operational cost deduction rate (4.6667%)",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.TDS_RATE,
        setting_value=Decimal("0.020000"),
        description="Plan A Tax Deducted at Source rate (2.0000%)",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.CASHBACK_PER_UNIT,
        setting_value=Decimal("250.000000"),
        description="Plan A customer cashback contribution amount per eligible Billing ID",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.CASHBACK_CYCLE_TARGET,
        setting_value=Decimal("4000.000000"),
        description="Plan A cashback cycle completion threshold (16 contributions = Rs. 4,000)",
    ),
    # Plan A PA-24 Unit Allocation components (PRD A §3)
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.ALLOC_PRODUCT_IMPORT,
        setting_value=Decimal("1500.000000"),
        description="Plan A unit cost allocation: Product import cost",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.ALLOC_GST_RESERVE,
        setting_value=Decimal("400.000000"),
        description="Plan A unit cost allocation: GST reserve",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.ALLOC_PACKING_COURIER,
        setting_value=Decimal("150.000000"),
        description="Plan A unit cost allocation: Packing and courier expense",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.ALLOC_GIFT_FUND,
        setting_value=Decimal("150.000000"),
        description="Plan A unit cost allocation: Gift and achievement fund",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_A,
        setting_key=SettingKey.ALLOC_OFFICE_STAFF,
        setting_value=Decimal("100.000000"),
        description="Plan A unit cost allocation: Office and staff expenses",
    ),
    # -----------------------------------------------------------------------
    # Plan B Canonical Settings (PRD B §5, §26; BR-B2 defaults)
    # -----------------------------------------------------------------------
    CanonicalSettingDefinition(
        programme=Programme.PLAN_B,
        setting_key=SettingKey.DIRECT_COMMISSION_GROSS,
        setting_value=Decimal("500.000000"),
        description="Plan B direct distributor referral reward on referee first qualifying purchase",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_B,
        setting_key=SettingKey.GENERATION_COMMISSION_GROSS,
        setting_value=Decimal("50.000000"),
        description="Plan B generation commission per eligible Billing ID to direct referring distributor",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_B,
        setting_key=SettingKey.OP_COST_RATE,
        setting_value=Decimal("0.000000"),
        description="Plan B operational cost deduction rate (0.0000% engineering default pending BR-B2)",
    ),
    CanonicalSettingDefinition(
        programme=Programme.PLAN_B,
        setting_key=SettingKey.TDS_RATE,
        setting_value=Decimal("0.000000"),
        description="Plan B Tax Deducted at Source rate (0.0000% engineering default pending BR-B2)",
    ),
)


# ---------------------------------------------------------------------------
# Internal Validation & Datetime Normalization Helpers
# ---------------------------------------------------------------------------


def _get_naive_utc_now() -> datetime:
    """Return the current time as a naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetime inputs to naive UTC datetimes.

    The ShopEasy database models store UTC timestamps without timezone information.
    To prevent Python TypeError when comparing offset-naive and offset-aware datetimes,
    any timezone-aware datetime is explicitly converted to UTC and stripped of tzinfo.
    """
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        raise FinancialSettingValidationError(f"Expected datetime object, received {type(dt).__name__}.")
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _validate_programme(programme: Any) -> Programme:
    """Validate and convert input to a Programme enum instance."""
    if isinstance(programme, Programme):
        return programme
    if isinstance(programme, str):
        try:
            return Programme(programme.strip().upper())
        except ValueError:
            pass
    raise FinancialSettingValidationError(
        f"Invalid programme: {programme!r}. Must be one of {[p.value for p in Programme]}."
    )


def _validate_setting_key(setting_key: Any) -> str:
    """Validate and normalize setting key identifier."""
    if not isinstance(setting_key, str) or not setting_key.strip():
        raise FinancialSettingValidationError("Setting key must be a non-empty string.")
    normalized = setting_key.strip().upper()
    if len(normalized) > 64:
        raise FinancialSettingValidationError(
            f"Setting key '{normalized}' exceeds maximum length of 64 characters."
        )
    return normalized


def _validate_effective_window(
    effective_from: datetime, effective_to: Optional[datetime]
) -> None:
    """Validate that effective_to is strictly greater than effective_from.

    A half-open interval [effective_from, effective_to) requires effective_to > effective_from.
    An equal or inverted window creates an empty or invalid period.
    """
    if effective_to is not None:
        if effective_to <= effective_from:
            raise FinancialSettingValidationError(
                f"effective_to ({effective_to.isoformat()}) must be strictly greater than "
                f"effective_from ({effective_from.isoformat()}). Zero-duration and negative intervals are prohibited."
            )


def _parse_and_validate_value(
    value: Any, currency: Optional[str] = "INR"
) -> Tuple[Decimal, str]:
    """Validate numeric input, verify bounds and scale, and return (Decimal, currency).

    Rules:
      1. Floats are strictly prohibited.
      2. NaN, +/-Inf, and invalid numeric strings are rejected.
      3. Negative amounts are prohibited (chk_fin_settings_value_non_negative).
      4. Precision must not exceed 12 integer digits (< 10^12).
      5. Fractional digits beyond 6 decimal places without precision loss are rejected.
      6. Currency must be a 3-character uppercase string.
    """
    if isinstance(value, float):
        raise TypeError(
            f"Floating-point values are forbidden for financial settings. Received float: {value!r}. "
            f"Use Decimal, Money, str, or int instead."
        )

    resolved_currency = currency or "INR"
    if isinstance(value, Money):
        resolved_currency = value.currency
        raw_decimal = value.amount
    else:
        try:
            raw_decimal = _parse_decimal(value)
        except (TypeError, ValueError) as exc:
            raise FinancialSettingValidationError(str(exc)) from exc

    if raw_decimal < Decimal("0.000000"):
        raise FinancialSettingValidationError(
            f"Financial setting value cannot be negative: {raw_decimal}."
        )

    if raw_decimal >= MAX_NUMERIC_VALUE:
        raise FinancialSettingValidationError(
            f"Financial setting value {raw_decimal} exceeds maximum supported database value (< 10^12)."
        )

    # Validate that truncating to 6 decimal places causes zero precision loss
    quantized = raw_decimal.quantize(SCALE_FACTOR, rounding=ROUND_DOWN)
    if raw_decimal != quantized:
        raise FinancialSettingValidationError(
            f"Setting value {raw_decimal} exceeds the maximum supported database precision of 6 decimal places."
        )

    if not isinstance(resolved_currency, str) or len(resolved_currency.strip()) != 3:
        raise FinancialSettingValidationError(
            f"Invalid currency code: {resolved_currency!r}. Must be a 3-letter ISO code."
        )

    return raw_decimal, resolved_currency.strip().upper()


def _is_version_uniqueness_conflict(exc: Exception) -> bool:
    """Determine whether an IntegrityError was caused by uq_fin_settings_prog_key_version."""
    msg = str(exc).lower()
    if "uq_fin_settings_prog_key_version" in msg:
        return True
    if "unique constraint failed" in msg and "version" in msg:
        return True
    if "duplicate entry" in msg and ("version" in msg or "uq_fin_settings" in msg):
        return True
    return False


# ---------------------------------------------------------------------------
# Core Service Functions
# ---------------------------------------------------------------------------


def resolve_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
    transaction_time: datetime,
) -> FinancialSetting:
    """Resolve the setting version effective at a specific transaction timestamp.

    Resolution Rule:
      effective_from <= transaction_time AND (effective_to IS NULL OR effective_to > transaction_time)

    Guarantees:
      - Half-open interval [effective_from, effective_to).
      - effective_from is inclusive.
      - effective_to is exclusive.
      - Does NOT filter on is_active=True: historical superseded or inactive versions
        remain resolvable for transactions that occurred during their valid tenure.
      - Raises SettingNotFoundError if no version matches.
      - Raises MultipleMatchingSettingsError if multiple versions match (data integrity issue).
    """
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)
    norm_time = _normalize_datetime(transaction_time)
    if norm_time is None:
        raise FinancialSettingValidationError("transaction_time cannot be None.")

    stmt = (
        select(FinancialSetting)
        .where(
            FinancialSetting.programme == prog,
            FinancialSetting.setting_key == key,
            FinancialSetting.effective_from <= norm_time,
            or_(
                FinancialSetting.effective_to.is_(None),
                FinancialSetting.effective_to > norm_time,
            ),
        )
        .order_by(FinancialSetting.effective_from.desc(), FinancialSetting.version.desc())
    )

    matches = list(db.execute(stmt).scalars().all())

    if len(matches) == 0:
        raise SettingNotFoundError(
            f"No financial setting found for programme '{prog.value}', key '{key}' "
            f"at transaction time {norm_time.isoformat()}."
        )

    if len(matches) > 1:
        matched_ids = [m.id for m in matches]
        matched_versions = [m.version for m in matches]
        raise MultipleMatchingSettingsError(
            f"Data integrity error: Multiple ({len(matches)}) setting versions match programme '{prog.value}', "
            f"key '{key}' at timestamp {norm_time.isoformat()}. "
            f"Matched IDs: {matched_ids}, versions: {matched_versions}."
        )

    return matches[0]


def get_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
) -> FinancialSetting:
    """Retrieve the currently active version of a setting for a programme and key.

    Filters for is_active == True. Raises SettingNotFoundError if none found,
    or MultipleMatchingSettingsError if more than one active record exists.
    """
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)

    stmt = (
        select(FinancialSetting)
        .where(
            FinancialSetting.programme == prog,
            FinancialSetting.setting_key == key,
            FinancialSetting.is_active == True,
        )
        .order_by(FinancialSetting.version.desc())
    )

    matches = list(db.execute(stmt).scalars().all())

    if len(matches) == 0:
        raise SettingNotFoundError(
            f"No active financial setting found for programme '{prog.value}', key '{key}'."
        )

    if len(matches) > 1:
        matched_ids = [m.id for m in matches]
        matched_versions = [m.version for m in matches]
        raise MultipleMatchingSettingsError(
            f"Data integrity error: Multiple ({len(matches)}) active versions found for programme '{prog.value}', "
            f"key '{key}'. Matched IDs: {matched_ids}, versions: {matched_versions}."
        )

    return matches[0]


def get_setting_or_none(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
) -> Optional[FinancialSetting]:
    """Retrieve the currently active setting, returning None if not configured."""
    try:
        return get_setting(db, programme, setting_key)
    except SettingNotFoundError:
        return None


def create_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
    setting_value: Union[Money, Decimal, str, int],
    effective_from: Optional[datetime] = None,
    effective_to: Optional[datetime] = None,
    currency: str = "INR",
    description: Optional[str] = None,
    created_by_id: Optional[int] = None,
    reason: Optional[str] = "Initial setting creation",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> FinancialSetting:
    """Create the initial (Version 1) configuration for a programme and setting key.

    Guarantees:
      - Validates numeric precision and non-negative bounds.
      - Sets version = 1.
      - Enforces atomic audit history insertion (CREATED).
      - Protects against simultaneous first-version inserts using a bounded retry
        loop that rolls back on collision and queries committed state.
      - If another transaction already committed Version 1, raises SettingAlreadyExistsError.
    """
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)
    parsed_value, parsed_currency = _parse_and_validate_value(setting_value, currency)

    eff_from = _normalize_datetime(effective_from) or _get_naive_utc_now()
    eff_to = _normalize_datetime(effective_to)
    _validate_effective_window(eff_from, eff_to)

    for attempt in range(1, max_retries + 1):
        try:
            # Query existing latest record under lock where supported
            existing = (
                db.execute(
                    select(FinancialSetting)
                    .where(
                        FinancialSetting.programme == prog,
                        FinancialSetting.setting_key == key,
                    )
                    .order_by(FinancialSetting.version.desc())
                    .with_for_update()
                )
                .scalars()
                .first()
            )

            if existing is not None:
                raise SettingAlreadyExistsError(
                    f"Financial setting '{key}' for programme '{prog.value}' already exists "
                    f"(latest version: {existing.version}). Use update_setting() to create a subsequent version."
                )

            new_setting = FinancialSetting(
                programme=prog,
                setting_key=key,
                setting_value=parsed_value,
                currency=parsed_currency,
                description=description,
                version=1,
                effective_from=eff_from,
                effective_to=eff_to,
                is_active=True,
                created_by_id=created_by_id,
            )
            db.add(new_setting)
            db.flush()

            history_entry = FinancialSettingHistory(
                setting_id=new_setting.id,
                programme=prog,
                setting_key=key,
                old_value=None,
                new_value=parsed_value,
                version=1,
                action=SettingAction.CREATED,
                reason=reason,
                changed_by_id=created_by_id,
            )
            db.add(history_entry)
            db.commit()
            db.refresh(new_setting)
            return new_setting

        except IntegrityError as exc:
            db.rollback()
            if not _is_version_uniqueness_conflict(exc):
                # Unrelated integrity failure (e.g. invalid created_by_id FK) -> fail immediately
                raise
            if attempt >= max_retries:
                raise SettingConcurrencyError(
                    f"Failed to create first version for setting '{key}' (programme: {prog.value}) "
                    f"after {max_retries} attempts due to persistent concurrent version conflicts."
                ) from exc
            logger.warning(
                f"Version conflict creating initial setting '{key}' ({prog.value}), attempt {attempt}/{max_retries}. Retrying."
            )
        except Exception:
            db.rollback()
            raise

    raise SettingConcurrencyError(f"Exceeded max retries creating setting '{key}'.")


def update_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
    new_value: Union[Money, Decimal, str, int],
    effective_from: Optional[datetime] = None,
    effective_to: Optional[datetime] = None,
    currency: Optional[str] = None,
    description: Optional[str] = None,
    changed_by_id: Optional[int] = None,
    reason: Optional[str] = "Setting updated",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> FinancialSetting:
    """Create a subsequent version for an existing setting.

    Guarantees:
      - Validates that a previous version exists.
      - Closes previous version's effective_to at new version's effective_from.
      - Sets previous version is_active = False.
      - Increments version monotonically: new_version = latest.version + 1.
      - Enforces atomic audit history insertion (UPDATED).
      - Handles concurrent updates safely with bounded rollback-and-retry.
    """
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)
    parsed_value, parsed_currency = _parse_and_validate_value(new_value, currency)

    req_eff_from = _normalize_datetime(effective_from)
    eff_to = _normalize_datetime(effective_to)

    for attempt in range(1, max_retries + 1):
        try:
            # Re-read committed state under row-level lock
            latest = (
                db.execute(
                    select(FinancialSetting)
                    .where(
                        FinancialSetting.programme == prog,
                        FinancialSetting.setting_key == key,
                    )
                    .order_by(FinancialSetting.version.desc())
                    .with_for_update()
                )
                .scalars()
                .first()
            )

            if latest is None:
                raise SettingNotFoundError(
                    f"Cannot update setting '{key}' for programme '{prog.value}': setting does not exist. "
                    f"Use create_setting() to create the first version."
                )

            if not latest.is_active:
                raise FinancialSettingValidationError(
                    f"Cannot update financial setting '{key}' for programme '{prog.value}': latest version "
                    f"(version {latest.version}) is inactive/deactivated. Use reactivate_setting() to reactivate "
                    f"this setting."
                )

            now = _get_naive_utc_now()
            if req_eff_from is not None:
                eff_from = req_eff_from
                if eff_from <= latest.effective_from:
                    raise FinancialSettingValidationError(
                        f"New version effective_from ({eff_from.isoformat()}) must be strictly after previous version "
                        f"effective_from ({latest.effective_from.isoformat()})."
                    )
                if latest.effective_to is not None and eff_from > latest.effective_to:
                    raise FinancialSettingValidationError(
                        f"Cannot update setting '{key}' for programme '{prog.value}': new version effective_from "
                        f"({eff_from.isoformat()}) exceeds current version's scheduled effective_to "
                        f"({latest.effective_to.isoformat()}). Cannot extend an existing finite boundary."
                    )
            else:
                eff_from = max(now, latest.effective_from + timedelta(microseconds=1))
                if latest.effective_to is not None and eff_from > latest.effective_to:
                    raise FinancialSettingValidationError(
                        f"Cannot update setting '{key}' for programme '{prog.value}': current timestamp "
                        f"({eff_from.isoformat()}) exceeds current version's scheduled effective_to "
                        f"({latest.effective_to.isoformat()}). Cannot extend an existing finite boundary."
                    )

            _validate_effective_window(eff_from, eff_to)

            # Close previous latest version
            latest.effective_to = eff_from
            latest.is_active = False

            next_version = latest.version + 1
            final_currency = parsed_currency or latest.currency

            new_setting = FinancialSetting(
                programme=prog,
                setting_key=key,
                setting_value=parsed_value,
                currency=final_currency,
                description=description or latest.description,
                version=next_version,
                effective_from=eff_from,
                effective_to=eff_to,
                is_active=True,
                created_by_id=changed_by_id,
            )
            db.add(new_setting)
            db.flush()

            history_entry = FinancialSettingHistory(
                setting_id=new_setting.id,
                programme=prog,
                setting_key=key,
                old_value=latest.setting_value,
                new_value=parsed_value,
                version=next_version,
                action=SettingAction.UPDATED,
                reason=reason,
                changed_by_id=changed_by_id,
            )
            db.add(history_entry)
            db.commit()
            db.refresh(new_setting)
            return new_setting

        except IntegrityError as exc:
            db.rollback()
            if not _is_version_uniqueness_conflict(exc):
                raise
            if attempt >= max_retries:
                raise SettingConcurrencyError(
                    f"Failed to update setting '{key}' for programme '{prog.value}' after "
                    f"{max_retries} attempts due to persistent concurrent version conflicts."
                ) from exc
            logger.warning(
                f"Version conflict updating setting '{key}' ({prog.value}), attempt {attempt}/{max_retries}. Retrying."
            )
        except Exception:
            db.rollback()
            raise

    raise SettingConcurrencyError(f"Exceeded max retries updating setting '{key}'.")


def deactivate_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
    changed_by_id: Optional[int] = None,
    reason: Optional[str] = "Setting deactivated",
    effective_to: Optional[datetime] = None,
) -> FinancialSetting:
    """Deactivate the currently active version of a setting.

    Marks is_active = False, bounds effective_to, and writes an atomic DEACTIVATED audit record.
    Historical resolution for transactions before effective_to remains intact.
    """
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)
    now = _get_naive_utc_now()
    if effective_to is not None:
        close_time = _normalize_datetime(effective_to)
        if close_time is not None and close_time <= now:
            pass  # Validated against current.effective_from below
    else:
        close_time = None

    try:
        current = (
            db.execute(
                select(FinancialSetting)
                .where(
                    FinancialSetting.programme == prog,
                    FinancialSetting.setting_key == key,
                    FinancialSetting.is_active == True,
                )
                .order_by(FinancialSetting.version.desc())
                .with_for_update()
            )
            .scalars()
            .first()
        )

        if current is None:
            raise SettingNotFoundError(
                f"No active setting '{key}' found for programme '{prog.value}' to deactivate."
            )

        if close_time is None:
            close_time = max(now, current.effective_from + timedelta(microseconds=1))
        elif close_time <= current.effective_from:
            raise FinancialSettingValidationError(
                f"effective_to ({close_time.isoformat()}) must be strictly after effective_from "
                f"({current.effective_from.isoformat()})."
            )

        if current.effective_to is not None and close_time > current.effective_to:
            raise FinancialSettingValidationError(
                f"Cannot deactivate setting '{key}' for programme '{prog.value}': effective_to "
                f"({close_time.isoformat()}) exceeds existing scheduled effective_to ({current.effective_to.isoformat()})."
            )

        current.is_active = False
        current.effective_to = close_time

        history_entry = FinancialSettingHistory(
            setting_id=current.id,
            programme=prog,
            setting_key=key,
            old_value=current.setting_value,
            new_value=current.setting_value,
            version=current.version,
            action=SettingAction.DEACTIVATED,
            reason=reason,
            changed_by_id=changed_by_id,
        )
        db.add(history_entry)
        db.commit()
        db.refresh(current)
        return current

    except Exception:
        db.rollback()
        raise


def reactivate_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
    changed_by_id: Optional[int] = None,
    reason: Optional[str] = "Setting reactivated",
    effective_from: Optional[datetime] = None,
    effective_to: Optional[datetime] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> FinancialSetting:
    """Reactivate a previously deactivated setting by creating a new version.

    Financial Integrity Rules:
      1. Never reopen a closed historical effective interval: previous versions retain their
         original [effective_from, effective_to) and remain immutable.
      2. Reactivation creates a new monotonic version (latest.version + 1) with is_active = True.
      3. The newly reactivated version takes effect from `effective_from` (defaulting to UTC now).
      4. Historical queries during the inactive gap will not match either version.
      5. Records an atomic SettingAction.REACTIVATED audit history row referencing the new version.
      6. Employs bounded retry if concurrent updates collide on the version unique constraint.
    """
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)
    req_eff_from = _normalize_datetime(effective_from)
    eff_to = _normalize_datetime(effective_to)

    for attempt in range(1, max_retries + 1):
        try:
            active = (
                db.execute(
                    select(FinancialSetting)
                    .where(
                        FinancialSetting.programme == prog,
                        FinancialSetting.setting_key == key,
                        FinancialSetting.is_active == True,
                    )
                )
                .scalars()
                .first()
            )
            if active is not None:
                raise FinancialSettingValidationError(
                    f"Setting '{key}' for programme '{prog.value}' is already active (version {active.version})."
                )

            latest = (
                db.execute(
                    select(FinancialSetting)
                    .where(
                        FinancialSetting.programme == prog,
                        FinancialSetting.setting_key == key,
                    )
                    .order_by(FinancialSetting.version.desc())
                    .with_for_update()
                )
                .scalars()
                .first()
            )

            if latest is None:
                raise SettingNotFoundError(
                    f"No setting '{key}' found for programme '{prog.value}' to reactivate. "
                    f"Use create_setting() to create the first version."
                )

            now = _get_naive_utc_now()
            prev_bound = latest.effective_to or latest.effective_from

            if req_eff_from is not None:
                eff_from = req_eff_from
                if eff_from <= prev_bound:
                    raise FinancialSettingValidationError(
                        f"Reactivation effective_from ({eff_from.isoformat()}) must be strictly after "
                        f"previous version closure ({prev_bound.isoformat()})."
                    )
            else:
                eff_from = max(now, prev_bound + timedelta(microseconds=1))

            _validate_effective_window(eff_from, eff_to)

            next_version = latest.version + 1

            # Invariant: Previous version is NOT altered. A new version is created.
            reactivated_setting = FinancialSetting(
                programme=prog,
                setting_key=key,
                setting_value=latest.setting_value,
                currency=latest.currency,
                description=latest.description,
                version=next_version,
                effective_from=eff_from,
                effective_to=eff_to,
                is_active=True,
                created_by_id=changed_by_id,
            )
            db.add(reactivated_setting)
            db.flush()

            history_entry = FinancialSettingHistory(
                setting_id=reactivated_setting.id,
                programme=prog,
                setting_key=key,
                old_value=latest.setting_value,
                new_value=latest.setting_value,
                version=next_version,
                action=SettingAction.REACTIVATED,
                reason=reason,
                changed_by_id=changed_by_id,
            )
            db.add(history_entry)
            db.commit()
            db.refresh(reactivated_setting)
            return reactivated_setting

        except IntegrityError as exc:
            db.rollback()
            if not _is_version_uniqueness_conflict(exc):
                raise
            if attempt >= max_retries:
                raise SettingConcurrencyError(
                    f"Failed to reactivate setting '{key}' for programme '{prog.value}' after "
                    f"{max_retries} attempts due to persistent concurrent version conflicts."
                ) from exc
            logger.warning(
                f"Version conflict reactivating setting '{key}' ({prog.value}), attempt {attempt}/{max_retries}. Retrying."
            )
        except Exception:
            db.rollback()
            raise

    raise SettingConcurrencyError(f"Exceeded max retries reactivating setting '{key}'.")


def get_setting_history(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
) -> List[FinancialSettingHistory]:
    """Retrieve full immutable version audit history for a setting, ordered newest first."""
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)

    stmt = (
        select(FinancialSettingHistory)
        .where(
            FinancialSettingHistory.programme == prog,
            FinancialSettingHistory.setting_key == key,
        )
        .order_by(FinancialSettingHistory.changed_at.desc(), FinancialSettingHistory.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def has_setting(
    db: Session,
    programme: Union[Programme, str],
    setting_key: str,
) -> bool:
    """Check whether ANY version (active or inactive, current or historical) exists for programme and key."""
    prog = _validate_programme(programme)
    key = _validate_setting_key(setting_key)
    stmt = (
        select(FinancialSetting.id)
        .where(
            FinancialSetting.programme == prog,
            FinancialSetting.setting_key == key,
        )
        .limit(1)
    )
    return db.execute(stmt).first() is not None


def seed_financial_settings(
    db: Session,
    created_by_id: Optional[int] = None,
    effective_from: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Seed canonical baseline financial settings idempotently within an atomic savepoint.

    Guarantees:
      - Historical-Version Safety: Checks whether ANY version (active or inactive)
        exists for each canonical (programme, setting_key) before inserting.
      - Immutability of Existing State: If any version exists, baseline seeding skips
        that setting completely. It never overwrites, reactivates, closes, or increments it.
      - Zero Duplicate History: Repeated seed executions make zero modifications and create
        zero history entries.
      - Transactional Atomicity: Uses a savepoint (begin_nested()) so that if an error occurs
        during seeding, all partial seed writes and history rows are rolled back to the savepoint
        without rolling back unrelated prior work in the caller's session.
      - Transaction Ownership: Does NOT commit the caller's transaction; commit ownership
        belongs entirely to the caller.
    """
    eff_from = _normalize_datetime(effective_from) or datetime(2026, 1, 1, 0, 0, 0)
    created_keys: List[str] = []
    skipped_keys: List[str] = []

    with db.begin_nested():
        for canonical in CANONICAL_SETTINGS:
            prog = canonical.programme
            key = canonical.setting_key

            if has_setting(db, prog, key):
                skipped_keys.append(f"{prog.value}:{key}")
                logger.info(
                    f"Financial setting '{key}' ({prog.value}) already exists. Skipping baseline seeding."
                )
                continue

            setting = FinancialSetting(
                programme=prog,
                setting_key=key,
                setting_value=canonical.setting_value,
                currency=canonical.currency,
                description=canonical.description,
                version=1,
                effective_from=eff_from,
                effective_to=None,
                is_active=True,
                created_by_id=created_by_id,
            )
            db.add(setting)
            db.flush()

            history = FinancialSettingHistory(
                setting_id=setting.id,
                programme=prog,
                setting_key=key,
                old_value=None,
                new_value=canonical.setting_value,
                version=1,
                action=SettingAction.CREATED,
                reason="Initial baseline seed",
                changed_by_id=created_by_id,
            )
            db.add(history)
            db.flush()

            created_keys.append(f"{prog.value}:{key}")
            logger.info(
                f"Seeded canonical financial setting '{key}' ({prog.value}) with value {canonical.setting_value}."
            )

    action = "created" if created_keys else "skipped"
    return {
        "action": action,
        "created_count": len(created_keys),
        "skipped_count": len(skipped_keys),
        "created_keys": created_keys,
        "skipped_keys": skipped_keys,
    }


# ---------------------------------------------------------------------------
# Service Class
# ---------------------------------------------------------------------------


class FinancialSettingsService:
    """Unified service class for financial settings operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(
        self, programme: Union[Programme, str], setting_key: str, transaction_time: datetime
    ) -> FinancialSetting:
        return resolve_setting(self.db, programme, setting_key, transaction_time)

    def get(self, programme: Union[Programme, str], setting_key: str) -> FinancialSetting:
        return get_setting(self.db, programme, setting_key)

    def get_or_none(
        self, programme: Union[Programme, str], setting_key: str
    ) -> Optional[FinancialSetting]:
        return get_setting_or_none(self.db, programme, setting_key)

    def create(
        self,
        programme: Union[Programme, str],
        setting_key: str,
        setting_value: Union[Money, Decimal, str, int],
        effective_from: Optional[datetime] = None,
        effective_to: Optional[datetime] = None,
        currency: str = "INR",
        description: Optional[str] = None,
        created_by_id: Optional[int] = None,
        reason: Optional[str] = "Initial setting creation",
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> FinancialSetting:
        return create_setting(
            self.db,
            programme,
            setting_key,
            setting_value,
            effective_from=effective_from,
            effective_to=effective_to,
            currency=currency,
            description=description,
            created_by_id=created_by_id,
            reason=reason,
            max_retries=max_retries,
        )

    def update(
        self,
        programme: Union[Programme, str],
        setting_key: str,
        new_value: Union[Money, Decimal, str, int],
        effective_from: Optional[datetime] = None,
        effective_to: Optional[datetime] = None,
        currency: Optional[str] = None,
        description: Optional[str] = None,
        changed_by_id: Optional[int] = None,
        reason: Optional[str] = "Setting updated",
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> FinancialSetting:
        return update_setting(
            self.db,
            programme,
            setting_key,
            new_value,
            effective_from=effective_from,
            effective_to=effective_to,
            currency=currency,
            description=description,
            changed_by_id=changed_by_id,
            reason=reason,
            max_retries=max_retries,
        )

    def deactivate(
        self,
        programme: Union[Programme, str],
        setting_key: str,
        changed_by_id: Optional[int] = None,
        reason: Optional[str] = "Setting deactivated",
        effective_to: Optional[datetime] = None,
    ) -> FinancialSetting:
        return deactivate_setting(
            self.db,
            programme,
            setting_key,
            changed_by_id=changed_by_id,
            reason=reason,
            effective_to=effective_to,
        )

    def reactivate(
        self,
        programme: Union[Programme, str],
        setting_key: str,
        changed_by_id: Optional[int] = None,
        reason: Optional[str] = "Setting reactivated",
        effective_from: Optional[datetime] = None,
        effective_to: Optional[datetime] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> FinancialSetting:
        return reactivate_setting(
            self.db,
            programme,
            setting_key,
            changed_by_id=changed_by_id,
            reason=reason,
            effective_from=effective_from,
            effective_to=effective_to,
            max_retries=max_retries,
        )

    def history(
        self, programme: Union[Programme, str], setting_key: str
    ) -> List[FinancialSettingHistory]:
        return get_setting_history(self.db, programme, setting_key)

    def has_setting(
        self, programme: Union[Programme, str], setting_key: str
    ) -> bool:
        return has_setting(self.db, programme, setting_key)

    def seed_canonical(
        self,
        created_by_id: Optional[int] = None,
        effective_from: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return seed_financial_settings(
            self.db, created_by_id=created_by_id, effective_from=effective_from
        )
