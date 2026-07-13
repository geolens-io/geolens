import math
import re

from fastapi import Request


from app.core.public_urls import get_env_public_api_url, join_public_url

# Languages supported by the GeoLens catalog (ISO 639-1)
_SUPPORTED_LANGS = {"en", "de", "fr", "es"}
_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


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
    for lang in parse_accept_languages(request):
        base = lang.split("-")[0].lower()
        if base in _SUPPORTED_LANGS:
            return base
    return "en"


def parse_accept_languages(request: Request) -> list[str]:
    """Return accepted language tags in quality and header order.

    Unlike :func:`parse_accept_language`, this parser is not restricted to the
    four UI locales.  Standards endpoints use it to negotiate any language for
    which a record has stored localized metadata.
    """
    header = request.headers.get("accept-language", "")
    entries: list[tuple[float, int, str]] = []
    for order, raw_part in enumerate(header.split(",")):
        pieces = [piece.strip() for piece in raw_part.split(";") if piece.strip()]
        if not pieces:
            continue
        language = pieces[0].replace("_", "-")
        if language == "*":
            continue
        quality = 1.0
        for parameter in pieces[1:]:
            key, separator, value = parameter.partition("=")
            if separator and key.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if not math.isfinite(quality) or quality <= 0 or quality > 1:
            continue
        normalized = normalize_language_tag(language)
        if normalized is not None:
            entries.append((quality, order, normalized))
    entries.sort(key=lambda item: (-item[0], item[1]))
    return [language for _, _, language in entries]


def normalize_language_tag(
    language: str | None, fallback: str | None = None
) -> str | None:
    """Normalize a stored language value for standards response headers."""
    if language is None:
        return fallback

    tag = language.strip().replace("_", "-")
    if not tag or not _LANGUAGE_TAG_RE.fullmatch(tag):
        return fallback

    parts = [part for part in tag.split("-") if part]
    if not parts:
        return fallback

    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def content_language_for_record_languages(
    languages: list[str | None],
    *,
    fallback: str | None = "en",
) -> str | None:
    """Return a truthful Content-Language value for serialized OGC records.

    OGC record content is currently single-language metadata. A collection page
    gets a header only when the serialized records are homogeneous; mixed pages
    omit the header instead of advertising the request's preferred language.
    """
    normalized = {
        tag
        for tag in (normalize_language_tag(language) for language in languages)
        if tag is not None
    }
    if not normalized:
        return fallback
    if len(normalized) == 1:
        return next(iter(normalized))
    return None
