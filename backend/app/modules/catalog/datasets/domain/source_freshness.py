"""Source freshness: how a dataset's last refresh compares to its cadence.

feat(#1224): ``records.update_frequency`` has carried the ISO 19115
maintenance-frequency vocabulary since the catalog shipped, and nothing ever
compared it to anything. ``datasets.last_refreshed_at`` (#1218) supplies the
other half, so source freshness is a pure read-side computation over stored
columns.

**"Source freshness", never bare "freshness".** The frontend already owns a
different concept under that word: ``frontend/src/lib/quality-freshness.ts``
measures the quality score's ``computed_at`` against the same
``update_frequency``, with its own thresholds (2 / 14 / 62 / 186 / 550 days,
plus a 45-day policy for an unknown cadence) and its own state set
(``fresh`` / ``stale`` / ``missing``). The two share a word, an input, and the
state name ``fresh`` while answering different questions, so every name here —
module, function, response field, and copy — carries the ``source_`` qualifier.

ADR-002 Decision 2 is the reason nothing here writes: the state derives from
live columns, so persisting it would create a value whose only possible
behaviour is to disagree with the ones it came from. The same argument retires
``origin_kind`` and ``quality_score_numeric``. Contrast ``schema_drift_status``,
which IS stored — drift compares a pre-refresh schema that no longer exists, so
it derives from nothing at read time.

``now`` and ``origin`` are parameters, not lookups, so the mapping is a total
function of its inputs and every threshold is testable without freezing time.

Source freshness never blocks anything. It is advisory state for the catalog UI
(#1226), the CLI, and the SDKs.
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

# Origins a refresh can actually re-pull from (ADR-002 Decision 5a's per-origin
# table). An allowlist rather than a denylist on purpose: a future origin kind
# nobody classified here reads "unknown", which withholds advice, instead of
# reading "overdue", which names an action that may not exist. The partition
# below is pinned against dataset_origin.ORIGIN_KINDS in the test suite, so
# adding a kind fails loudly rather than defaulting either way in silence.
REFRESHABLE_ORIGINS: frozenset[str] = frozenset(
    {"upload", "postgis", "service", "stac"}
)

# `created` is the whole reason origin is a parameter. A dataset drawn in the
# app came from nowhere, so ADR-002 Decision 5a gives it 409
# `refresh_not_applicable` — and yet service_create.py stamps every new dataset
# with `last_refreshed_at` at creation, and migration 0036 backfills a floor for
# older rows. Without this gate an eighteen-month-old sketch layer carrying
# `update_frequency='monthly'` would report "overdue" and point the user at an
# action that does not exist for it.
NON_REFRESHABLE_ORIGINS: frozenset[str] = frozenset({"created"})

# The full ISO 19115 MD_MaintenanceFrequencyCode set GeoLens accepts, mirroring
# chk_records_update_frequency on catalog.records. Kept here as well so the two
# can be compared: tests/test_dataset_source_freshness.py fails if the CHECK
# gains a value that nothing below assigns a meaning to, which is the loud
# version of a new vocabulary value silently rendering as "unknown" forever.
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

# One cycle of each cadence, in days. Calendar-length values are the LONGEST
# such period (31-day month, 92-day quarter, 366-day year) so a dataset kept on
# schedule is never reported late by a leap day or a short month; being a day
# slow to say "due" is the harmless direction.
#
# `continual` shares daily's period. ISO defines it as "repeatedly and
# frequently", with no unit attached, so any number here is invented; one day
# is the shortest cadence the rest of the table can express and reads the way a
# continually-updated dataset is meant to behave.
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

    Both inputs are timestamptz in the schema and arrive aware, and the app
    builds its own clock reads with ``datetime.now(timezone.utc)`` — the only
    naive datetimes this codebase produces are already UTC. Coercing rather
    than raising keeps a stray naive value from turning a plain dataset GET
    into a 500; coercing rather than returning ``UNKNOWN`` keeps it from
    disappearing into a legitimate-looking state instead.
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
    ``overdue`` past two. ``unknown`` covers every case where the question
    cannot be asked: an origin nothing can refresh (``created``), no cadence
    declared (``asNeeded``, ``irregular``, ``notPlanned``, ``unknown``, or
    NULL), an unrecognised frequency string, or nothing refreshed yet.

    ``origin`` is the value ``classify_origin`` produces, passed explicitly so
    this stays a pure function. A NULL origin is a VRT, which is refreshable in
    the sense that matters here: ADR-002 Decision 5a projects each VRT's latest
    generation timestamp into ``last_refreshed_at`` precisely so freshness
    renders uniformly across record types. (A collection also classifies as
    NULL and never reaches this function — it has no dataset row.)

    Boundaries are strict: an age of exactly one period is still ``fresh``, and
    exactly two is still ``due``. A refresh timed to the declared cadence lands
    on the boundary, so the inclusive reading would report an on-time dataset
    late.
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
