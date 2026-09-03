"""Value ranges for PostgreSQL's fixed-width numeric types (fix(#1778 review r2)).

A caller-supplied literal can be a perfectly good Python number and still be
wrong for the column it is compared against, and how that fails depends on the
SQL the compiler happens to emit. Three shapes, all measured on PostgreSQL 18
with asyncpg:

  - ``?ratio=1e100`` on a ``real`` column, through the property-filter path.
    SQLAlchemy's ``REAL()`` bind emits no narrowing cast, so PostgreSQL
    promotes the stored float4 and compares in float8. No error, no match:
    HTTP 200 with zero features.
  - ``?construction_year=2147483648`` on an ``integer`` column, bound
    ``BigInteger`` so the asyncpg cast matches the numeric family. ``int4 =
    int8`` is a legal comparison no stored value can satisfy. Again 200 with
    zero features.
  - ``filter=ratio = 1e100``, through CQL2, which compiles to
    ``ratio = CAST($1::FLOAT AS REAL)``. That cast DOES overflow:
    ``NumericValueOutOfRangeError``, SQLSTATE 22003.

The first two answer a question the caller did not ask; the third was an
unhandled 500. Checking the range before the query makes all three a 400 that
names the property and the bound it broke, rather than leaving the outcome to
which cast the compiler chose.

``bigint`` is here for a fourth reason: a Python int outside int8 cannot be
encoded at all, and asyncpg's failure arrives as ``sqlalchemy.exc.DBAPIError``
-- the base class, not ``DataError`` -- so nothing that caught ``DataError``
ever saw it.
"""

from __future__ import annotations

# Inclusive bounds, per PostgreSQL's documented numeric type limits.
PG_INTEGER_RANGES: dict[str, tuple[int, int]] = {
    "smallint": (-32768, 32767),
    "integer": (-2147483648, 2147483647),
    "bigint": (-(2**63), 2**63 - 1),
}

# Largest finite float4. A float8 above it has no float4 counterpart, so a
# comparison against a real column can never match.
FLOAT4_MAX = 3.4028234663852886e38

INT8_MIN, INT8_MAX = PG_INTEGER_RANGES["bigint"]


def check_pg_value_range(pg_type: str, value: object) -> None:
    """Raise ValueError when *value* is out of range for *pg_type*.

    The message states the bound, so a caller reading the 400 learns which
    limit it broke rather than only that something was rejected. Types with no
    fixed width (``numeric``, ``double precision``, text, temporal) have no
    bound to check and pass through.
    """
    bounds = PG_INTEGER_RANGES.get(pg_type)
    if bounds is not None and isinstance(value, int) and not isinstance(value, bool):
        low, high = bounds
        if not low <= value <= high:
            raise ValueError(f"must be between {low} and {high} for a {pg_type} column")
    if pg_type == "real" and isinstance(value, float):
        if abs(value) > FLOAT4_MAX:
            raise ValueError(
                f"magnitude must not exceed {FLOAT4_MAX:g} for a real column"
            )


def check_int8_range(name: str, value: int) -> None:
    """Raise ValueError when an integer bind cannot be encoded as int8.

    For the pagination integers, which are caller-supplied and reach the driver
    untyped. FastAPI's ``int`` has no upper bound, so ``?offset=10**23`` used to
    surface as a 500 from the asyncpg encode path on both routers.
    """
    if not INT8_MIN <= value <= INT8_MAX:
        raise ValueError(
            f"Invalid value for {name}: must be between {INT8_MIN} and {INT8_MAX}"
        )
