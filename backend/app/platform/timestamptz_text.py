"""Text form of a ``timestamptz`` shared by tiles and column sample values."""


def utc_timestamptz_text(ref: str) -> str:
    """SQL rendering a timestamptz as fixed UTC text, e.g.
    ``2024-03-01T17:00:00+00:00`` or ``2024-03-01T17:00:00.25+00:00``.

    ST_AsMVT writes a timestamptz in the session TimeZone, which a client
    cannot know and whose daylight-saving offsets break text ordering. In
    this form text order is time order against any year 1-9999 value: the
    fraction drops trailing zeros, ``+`` sorts below ``.`` and every digit,
    a BC value takes ISO 8601's signed astronomical year (``-0043`` is 44
    BC) and sorts first, and a value past year 9999 reads ``infinity``.
    """
    utc = f"({ref} AT TIME ZONE 'UTC')"
    return (
        f"CASE WHEN NOT isfinite({ref}) THEN {ref}::text "
        f"WHEN {utc} >= '10000-01-01' THEN 'infinity' "
        f"ELSE CASE WHEN {utc} < '0001-01-01' "
        f"THEN '-' || lpad((-1 - extract(year FROM {utc})::int)::text, 4, '0') "
        f"|| to_char({utc}, '-MM-DD\"T\"HH24:MI:SS') "
        f"ELSE to_char({utc}, 'YYYY-MM-DD\"T\"HH24:MI:SS') END "
        f"|| rtrim(rtrim(to_char({utc}, '.US'), '0'), '.') || '+00:00' END"
    )
