"""Shared ILIKE escape helper for catalog search patterns.

PostgreSQL uses backslash as the ILIKE escape character by default.
To treat %, _, and '\\' as literals in a LIKE/ILIKE pattern the backslash
must be escaped FIRST, before % and _ are escaped -- otherwise an
already-escaped sequence like \\% would be double-escaped on the second
pass.

Usage::

    escaped = escape_ilike(user_input)
    stmt = stmt.where(Column.ilike(f"%{escaped}%", escape="\\\\"))

The ``escape="\\\\"`` kwarg emits ``ESCAPE '\\'`` in the SQL, making the
escape character explicit and independent of any future PostgreSQL default
changes.
"""

__all__ = ["escape_ilike"]


def escape_ilike(s: str) -> str:
    """Escape backslash, percent, and underscore for use in an ILIKE pattern.

    Must be called before composing the surrounding ``%…%`` anchors::

        pattern = f"%{escape_ilike(search)}%"

    and the corresponding SQLAlchemy call must pass ``escape="\\\\"``:

        Column.ilike(pattern, escape="\\\\")
    """
    return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
