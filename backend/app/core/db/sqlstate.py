"""PostgreSQL SQLSTATE helpers for classifying database errors (fix(#435)).

Handlers used to catch `Exception` (or bare `DBAPIError`) and guess. A dropped
table, a statement timeout, and a lost connection are very different events, and
only the first of them is a domain condition the API should paper over.

SQLSTATE reference: https://www.postgresql.org/docs/current/errcodes-appendix.html
"""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError

# The relation the query names does not exist. Not always damage: raster and VRT
# datasets carry a synthetic `table_name` with no PostGIS table behind it.
#
# fix(#435 codex r1): `3F000` (invalid_schema_name) was in this set and is now not.
# A `SELECT` against a missing schema reports `42P01`, so `3F000` never described the
# benign case here; Postgres raises it from DDL paths, where it means the schema is
# gone. Treating it as "empty dataset" would have hidden real provisioning drift.
#
# `42P01` alone cannot separate "raster dataset, no backing table" from "the tenant's
# data schema was never provisioned" — both report it. Callers must probe the schema.
# See `schema_exists()` and `get_dataset_rows()`.
TABLE_ABSENT = frozenset({"42P01"})  # undefined_table

# The caller sent something the table cannot answer — a bad filter column or an
# unparseable literal. These are 4xx, not 5xx.
BAD_QUERY_INPUT = frozenset(
    {
        "42703",  # undefined_column
        "22P02",  # invalid_text_representation
        "42883",  # undefined_function (e.g. no operator for the cast)
        "42804",  # datatype_mismatch
    }
)


# SQLSTATE *classes* (first two characters) that mean "the database could not serve
# this request", as opposed to "the request was wrong". Only these become a 503.
#
# Selecting by class rather than by exception type matters: SQLAlchemy's asyncpg
# dialect wraps a statement timeout (57014) as a plain `DBAPIError`, not as
# `OperationalError`, so `except OperationalError` silently misses it.
_OPERATIONAL_CLASSES = frozenset(
    {
        "08",  # connection_exception
        "40",  # transaction_rollback — serialization_failure, deadlock_detected
        "53",  # insufficient_resources — out of memory, too many connections
        "57",  # operator_intervention — query_canceled, admin_shutdown
        "58",  # system_error — I/O failure below the server
    }
)


# States that mean "the caller's value does not fit the column it was compared
# against", as opposed to an outage or a bug in our own SQL.
#
# fix(#1778 review r2): one definition, read by the OGC items handler and the
# native features list, because they had drifted. The OGC router carried this
# set inline while the native one tested a narrower `BAD_QUERY_INPUT`, so the
# same failure was a 400 through one endpoint and a 503 through the other.
#
# Class 22 is data_exception as a whole. asyncpg reports a client-side encode
# failure (an int outside int8, say) as plain 22000 on a bare
# ``sqlalchemy.exc.DBAPIError`` -- NOT a ``DataError``, which is why catching
# ``DataError`` alone missed it and both routers 500'd.
TYPE_FAULT_SQLSTATES = frozenset(
    {
        "42883",  # undefined_function — no operator for the pair
        "42804",  # datatype_mismatch
        "42846",  # cannot_coerce
        "42P18",  # indeterminate_datatype
    }
)


def is_caller_type_fault(exc: DBAPIError) -> bool:
    """True when the database refused a caller-supplied value's type or range.

    A DataError carrying no SQLSTATE counts: the driver raised before the
    server answered, and for this class of error that means it could not encode
    what the caller sent.
    """
    from sqlalchemy.exc import DataError

    code = sqlstate(exc) or ""
    return (
        code.startswith("22")
        or code in TYPE_FAULT_SQLSTATES
        or (isinstance(exc, DataError) and not code)
    )


def sqlstate(exc: DBAPIError) -> str | None:
    """Return the five-character SQLSTATE for a SQLAlchemy DBAPI error, if any.

    asyncpg exposes `sqlstate`; psycopg exposes `pgcode`. Returns None when the
    driver surfaced no code (e.g. the connection died before the server answered),
    which callers should treat as operational.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return str(code) if code else None


def is_operational(exc: DBAPIError) -> bool:
    """True when *exc* means the database failed us, not that the request was bad.

    A missing SQLSTATE counts as operational: the driver raised before the server
    answered, which is a connection failure by another name.

    Integrity violations (class 23), syntax and access errors (class 42), and data
    errors (class 22) are deliberately excluded — a unique-constraint collision is a
    bug or a conflict, and reporting it as "database unavailable" would send callers
    into a pointless retry loop.
    """
    code = sqlstate(exc)
    if code is None:
        return True
    return code[:2] in _OPERATIONAL_CLASSES


# Another transaction owns rows this one needs right now. Both states mean the
# same thing to a caller: nothing was written, and a retry lands after the
# owner commits.
#
# fix(#1847): one definition, because the answer had been rewritten per module.
# `app.platform.jobs.router` carried this exact pair inline, `catalog.maps`
# carried a 55P03-only copy whose docstring recorded that it wanted to share
# but had nowhere layer-legal to share from, and the feature-write router had
# no notion of a lock conflict at all -- so a deadlock victim there fell
# through `is_operational` (class 40) and surfaced as "database temporarily
# unavailable", which is a 503 telling the client to back off when the correct
# advice is to retry immediately.
#
# 40001 (serialization_failure) is deliberately NOT here. It is unreachable at
# READ COMMITTED, which is the only isolation level this application runs at,
# and adding it would widen two already-reviewed predicates for a case no
# caller can produce.
LOCK_CONFLICT = frozenset(
    {
        "55P03",  # lock_not_available — SET LOCAL lock_timeout expired
        "40P01",  # deadlock_detected — this transaction was the victim
    }
)


def is_lock_conflict(exc: BaseException) -> bool:
    """True when *exc* means "another transaction holds what this one wants".

    Accepts either shape. asyncpg raises `LockNotAvailableError` /
    `DeadlockDetectedError` directly, and `AsyncSession.execute` wraps that in
    SQLAlchemy's `DBAPIError` with `.orig` pointing at the same exception, so a
    helper that only unwrapped one of the two missed the other depending on
    which layer the call bubbled through.

    Narrower than a "retry this statement" test on purpose. The re-upload swap
    in `processing/ingest/tasks_common.py` keeps its own 55P03-only predicate,
    because retrying DDL after a *deadlock* is a different and unproven
    decision from retrying it after a lock timeout.
    """
    for candidate in (exc, getattr(exc, "orig", None)):
        if candidate is None:
            continue
        code = getattr(candidate, "sqlstate", None) or getattr(
            candidate, "pgcode", None
        )
        if code and str(code) in LOCK_CONFLICT:
            return True
    return False
