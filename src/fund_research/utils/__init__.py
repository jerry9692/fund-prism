"""Utility functions — logging, date helpers, file I/O."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return current UTC datetime (naive, for DB storage compatibility)."""
    return datetime.now(UTC).replace(tzinfo=None)
