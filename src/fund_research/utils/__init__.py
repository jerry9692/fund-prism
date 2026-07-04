"""Utility functions — logging, date helpers, numeric helpers."""

from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """Return current UTC datetime (naive, for DB storage compatibility)."""
    return datetime.now(UTC).replace(tzinfo=None)


def safe_float(value: Any) -> float | None:
    """Convert value to float, returning None for NaN/None/invalid inputs.

    Used across analysis modules to safely handle nullable numeric columns
    that may contain NaN (float columns can store NaN from data ingestion).
    """
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN check (NaN != NaN)
            return None
        return f
    except (ValueError, TypeError):
        return None


def nav_value(row: Any) -> float | None:
    """Extract the best available NAV value from a FundNAV row.

    Priority: adjusted_nav > accumulated_nav > unit_nav.
    Returns None if no valid NAV exists.
    """
    for attr in ("adjusted_nav", "accumulated_nav", "unit_nav"):
        val = safe_float(getattr(row, attr, None))
        if val is not None:
            return val
    return None
