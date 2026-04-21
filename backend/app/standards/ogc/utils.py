from fastapi import Request


from app.core.public_urls import get_env_public_api_url, join_public_url

# Languages supported by the GeoLens catalog (ISO 639-1)
_SUPPORTED_LANGS = {"en", "de", "fr", "es"}


def build_url(
    path: str,
    request: Request | None = None,
    *,
    base_url: str | None = None,
) -> str:
    """Build an absolute API URL for OGC and distribution links."""
    resolved_base = base_url or get_env_public_api_url(request=request)
    return join_public_url(resolved_base, path)


def parse_accept_language(request: Request) -> str:
    """Extract the preferred language from Accept-Language, falling back to 'en'.

    Supports simple parsing of the ``Accept-Language`` header with quality
    values (e.g. ``de-DE,de;q=0.9,en;q=0.8``).  Returns the best match
    from ``_SUPPORTED_LANGS``, or ``"en"`` when no match is found.
    """
    header = request.headers.get("accept-language", "")
    if not header:
        return "en"

    # Parse language tags with optional quality values
    entries: list[tuple[float, str]] = []
    for part in header.split(","):
        part = part.strip()
        if not part:
            continue
        if ";q=" in part:
            lang, q = part.split(";q=", 1)
            try:
                entries.append((float(q.strip()), lang.strip()))
            except ValueError:
                entries.append((1.0, lang.strip()))
        else:
            entries.append((1.0, part))

    # Sort by quality descending, match against supported
    entries.sort(key=lambda x: -x[0])
    for _, lang in entries:
        base = lang.split("-")[0].lower()
        if base in _SUPPORTED_LANGS:
            return base
    return "en"
