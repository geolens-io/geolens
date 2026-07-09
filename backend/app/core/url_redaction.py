"""Helpers for rejecting and redacting credential-bearing URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED_QUERY_VALUE = "<redacted>"
REDACTED_USERINFO = "redacted"
URL_LIKE_RE = re.compile(r"(?:(?:[A-Za-z0-9_+.-]+:)?https?://)[^\s\"'<>]+")

SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        "client_secret",
        "code",
        "key",
        "password",
        "refresh_token",
        "sig",
        "signature",
        "subscription-key",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
        "x-goog-credential",
        "x-goog-security-token",
        "x-goog-signature",
    }
)


def _is_sensitive_query_param(name: str) -> bool:
    return name.strip().lower() in SENSITIVE_QUERY_PARAMS


def query_has_credentials(query: str) -> bool:
    """Return True if a raw query string contains known credential parameters."""
    if query.startswith("?"):
        query = query[1:]
    return any(
        _is_sensitive_query_param(key)
        for key, _ in parse_qsl(query, keep_blank_values=True)
    )


def has_url_credentials(url: str) -> bool:
    """Return True if a URL carries credential-like userinfo or query params."""
    # fix(#430 BA-04): strip GDAL-style prefixes (ESRIJSON:, WFS:, ...) before
    # inspecting userinfo — otherwise urlsplit sees no netloc and misses
    # `user:pass@` behind the prefix, mirroring redact_url_credentials.
    prefixed = _split_prefixed_url(url)
    if prefixed is not None:
        return has_url_credentials(prefixed[1])
    parts = urlsplit(url)
    return bool(parts.username or parts.password) or query_has_credentials(parts.query)


def _split_prefixed_url(value: str) -> tuple[str, str] | None:
    """Split GDAL-style prefixes such as ``ESRIJSON:https://...``."""
    prefix, sep, rest = value.partition(":")
    if not sep or prefix.lower() in {"http", "https"}:
        return None
    if rest.startswith(("http://", "https://")):
        return f"{prefix}:", rest
    return None


def _redacted_netloc(parts) -> str:  # type: ignore[no-untyped-def]
    if not (parts.username or parts.password):
        return parts.netloc

    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    return f"{REDACTED_USERINFO}@{host}"


def redact_query_credentials(query: str) -> str:
    """Redact known credential query values, preserving non-sensitive params."""
    if not query:
        return query
    prefix = "?" if query.startswith("?") else ""
    raw_query = query[1:] if prefix else query
    pairs = parse_qsl(raw_query, keep_blank_values=True)
    if not any(_is_sensitive_query_param(key) for key, _ in pairs):
        return query
    return prefix + urlencode(
        [
            (key, REDACTED_QUERY_VALUE if _is_sensitive_query_param(key) else value)
            for key, value in pairs
        ]
    )


def redact_url_credentials(url: str) -> str:
    """Redact known credential query values and userinfo in a URL-like string."""
    prefixed = _split_prefixed_url(url)
    if prefixed is not None:
        prefix, nested_url = prefixed
        return prefix + redact_url_credentials(nested_url)

    parts = urlsplit(url)
    # Only a scheme-less string (free text, GDAL stderr) goes to the regex
    # fallback. An http(s) URL with an EMPTY host (e.g. "https://?token=x") must
    # still be reconstructed below — routing it to the fallback would match the
    # whole string and recurse forever. fix(#429 review): guard empty-host URLs
    # against unbounded recursion; the reconstruct path terminates and redacts.
    if parts.scheme.lower() not in {"http", "https"}:
        return URL_LIKE_RE.sub(
            lambda match: redact_url_credentials(match.group(0)),
            url,
        )
    redacted_netloc = _redacted_netloc(parts)
    if not parts.query:
        if redacted_netloc == parts.netloc:
            return url
        return urlunsplit(
            (parts.scheme, redacted_netloc, parts.path, parts.query, parts.fragment)
        )
    redacted_query = redact_query_credentials(parts.query)
    if redacted_query == parts.query and redacted_netloc == parts.netloc:
        return url
    return urlunsplit(
        (parts.scheme, redacted_netloc, parts.path, redacted_query, parts.fragment)
    )
