"""Source freshness: how a dataset's last refresh compares to its cadence.

feat(#1224): a pure read-side computation over ``records.update_frequency``
and ``datasets.last_refreshed_at`` (#1218), never persisted (ADR-002
Decision 2: a stored copy of a live-derived value can only disagree
with its inputs). Always ``source_`` prefixed, never bare "freshness" --
the frontend already uses that word for a different concept
(``frontend/src/lib/quality-freshness.ts``).

``now``/``origin`` are parameters, not lookups, so this stays a total,
freeze-time-testable function. Advisory only -- never blocks anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

FRESH = "fresh"
DUE = "due"
OVERDUE = "overdue"
# Spelled the same as dataset_origin.UNKNOWN and unrelated to it: that one is
# the wire form of a NULL source-state column, this one means "the question
# cannot be asked of this dataset". Two vocabularies that happen to share a
# word; do not collapse them.
UNKNOWN = "unknown"

SOURCE_FRESHNESS_VALUES: tuple[str, ...] = (FRESH, DUE, OVERDUE, UNKNOWN)

# Origins a refresh can actually re-pull from (ADR-002 Decision 5a). An
# allowlist, not a denylist: an unclassified future origin kind reads
# "unknown" (withholds advice) instead of "overdue" (names an action that
# may not exist). Pinned against dataset_origin.ORIGIN_KINDS in tests, so
# adding a kind fails loudly rather than defaulting silently.
REFRESHABLE_ORIGINS: frozenset[str] = frozenset(
    {"upload", "postgis", "service", "stac"}
)

# `created` is the whole reason origin is a parameter. A dataset drawn in
# the app came from nowhere (ADR-002 Decision 5a: 409
# `refresh_not_applicable`), yet service_create.py stamps every new dataset
# with `last_refreshed_at`, and migration 0036 backfills a floor for older
# rows. Without this gate an old sketch layer with `update_frequency`
# would report "overdue" for an action that doesn't exist for it.
NON_REFRESHABLE_ORIGINS: frozenset[str] = frozenset({"created"})

# Full ISO 19115 MD_MaintenanceFrequencyCode set, mirroring
# chk_records_update_frequency on catalog.records. Kept here too so
# tests/test_dataset_source_freshness.py fails loudly if the CHECK gains a
# value nothing below assigns a meaning to.
UPDATE_FREQUENCY_VOCABULARY: frozenset[str] = frozenset(
    {
        "continual",
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "biannually",
        "annually",
        "asNeeded",
        "irregular",
        "notPlanned",
        "unknown",
    }
)

# One cycle of each cadence, in days. Calendar-length values are the
# LONGEST such period (31-day month, 92-day quarter, 366-day year) so a
# dataset kept on schedule is never reported late by a leap day or short
# month -- being a day slow to say "due" is the harmless direction.
#
# `continual` shares daily's period: ISO defines it as "repeatedly and
# frequently" with no unit, so any number is invented, and one day is the
# shortest cadence the table can express.
FREQUENCY_PERIOD_DAYS: dict[str, int] = {
    "continual": 1,
    "daily": 1,
    "weekly": 7,
    "monthly": 31,
    "quarterly": 92,
    "biannually": 183,
    "annually": 366,
}

# Vocabulary values that declare no cadence at all, so no age can be late
# against them. Derived rather than listed, so the two sets cannot disagree.
UNSCHEDULED_FREQUENCIES: frozenset[str] = UPDATE_FREQUENCY_VOCABULARY - frozenset(
    FREQUENCY_PERIOD_DAYS
)

# Past one period a dataset is due; past this multiple of it, overdue.
OVERDUE_PERIOD_MULTIPLE = 2


def _as_utc(value: datetime) -> datetime:
    """Read a naive datetime as UTC so the subtraction below cannot raise.

    The only naive datetimes this codebase produces are already UTC.
    Coercing rather than raising keeps a stray naive value from turning a
    plain dataset GET into a 500; coercing rather than returning
    ``UNKNOWN`` keeps it from disappearing into a legitimate-looking state.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def compute_source_freshness(
    last_refreshed_at: datetime | None,
    update_frequency: str | None,
    now: datetime,
    *,
    origin: str | None,
) -> str:
    """Map a dataset's refresh age against its declared cadence.

    Returns ``fresh`` within one declared period, ``due`` past one, and
    ``overdue`` past two. ``unknown`` when the question can't be asked: an
    unrefreshable origin, no/unrecognised cadence, or nothing refreshed yet.

    A NULL ``origin`` is a VRT, still refreshable here since ADR-002
    Decision 5a projects each VRT's latest generation into
    ``last_refreshed_at``. Boundaries are strict (exactly one period is
    still ``fresh``): a refresh timed to the cadence lands on the
    boundary, and an inclusive reading would report it late.
    """
    if origin is not None and origin not in REFRESHABLE_ORIGINS:
        return UNKNOWN

    if last_refreshed_at is None:
        return UNKNOWN

    period_days = FREQUENCY_PERIOD_DAYS.get(update_frequency or "")
    if period_days is None:
        return UNKNOWN

    age = _as_utc(now) - _as_utc(last_refreshed_at)
    period = timedelta(days=period_days)
    if age > period * OVERDUE_PERIOD_MULTIPLE:
        return OVERDUE
    if age > period:
        return DUE
    return FRESH
