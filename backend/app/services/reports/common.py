"""Common utilities, validators, and formatting helpers for report generation (WP-11)."""

from datetime import date, datetime
from decimal import Decimal
import re
from typing import Optional, Tuple

from fastapi import HTTPException, status
from fastapi.responses import Response

# MIME types
MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_PDF = "application/pdf"

# Maximum export limit for memory safety
MAX_EXPORT_ROWS = 10000


def validate_date_range(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Validate that start_date does not exceed end_date.

    Raises:
        HTTPException 400: If start_date is chronologically after end_date.
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date range: start_date cannot be chronologically after end_date.",
        )
    return start_date, end_date


def sanitize_filename(base_name: str, ext: str) -> str:
    """Create a safe filename with only alphanumeric characters, underscores, and hyphens."""
    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", base_name).strip("_")
    return f"{clean_name}.{ext.lstrip('.')}"


def format_currency(amount: Optional[Decimal]) -> str:
    """Format Decimal currency value as Indian Rupee string, e.g. ₹1,250.00."""
    if amount is None:
        return "₹0.00"
    return f"₹{amount:,.2f}"


def format_dt(dt: Optional[datetime]) -> str:
    """Format datetime as YYYY-MM-DD HH:MM:SS."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_date(d: Optional[date]) -> str:
    """Format date as YYYY-MM-DD."""
    if d is None:
        return "-"
    return d.strftime("%Y-%m-%d")


def build_file_response(
    content_bytes: bytes,
    filename: str,
    media_type: str,
) -> Response:
    """Construct an HTTP Response with appropriate download headers."""
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(content_bytes)),
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return Response(content=content_bytes, media_type=media_type, headers=headers)

