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
