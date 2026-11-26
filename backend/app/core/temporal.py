"""RFC 3339 bounds for collection ``extent.temporal.interval``."""

from __future__ import annotations

from datetime import date, datetime, timezone


def rfc3339_bound(value: date | datetime | None, *, end: bool = False) -> str | None:
    """Render one interval bound as an RFC 3339 date-time, or ``None`` if open.

    A date covers its whole day: a start is midnight and an end is the last
    second. A datetime is converted to UTC; a naive one is taken as UTC.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{value.isoformat()}T{'23:59:59' if end else '00:00:00'}Z"


def temporal_interval(
    start: date | datetime | None, end: date | datetime | None
) -> list[list[str | None]]:
    return [[rfc3339_bound(start), rfc3339_bound(end, end=True)]]
