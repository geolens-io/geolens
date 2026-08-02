"""Helpers for rejecting and redacting credential-bearing URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

REDACTED_QUERY_VALUE = "<redacted>"
REDACTED_USERINFO = "redacted"
# fix(#1116): the optional scheme prefix is bounded to 64 characters, which is
# longer than any registered URI scheme. An unbounded `+` here is ambiguous
# against the `https?` that follows, so a long run of prefix-class characters
# that never completes a match made the engine retry every prefix length at
# every start position — O(n²) on a fallback that is fed GDAL stderr and
# uploaded-VRT paths. A longer prefix still redacts: the match simply starts
# later in the string and still spans the whole URL.
URL_LIKE_RE = re.compile(r"(?:(?:[A-Za-z0-9_+.-]{1,64}:)?https?://)[^\s\"'<>]+")

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


# fix(#1119): urlsplit raises ValueError on a malformed bracketed authority
# ("https://.[::1]", "https://[::1"), and redact_url_credentials let it escape —
# so a call whose whole contract is "return something safe to log" raised
# instead. sources/preview.py and the three processing/ingest/validation.py sites
# interpolate the result into an IngestionError, so a malformed authority in GDAL
# stderr or in an uploaded VRT's <SourceFilename> became an unhandled 500.
#
# These two patterns are enough to cover the fallback, because urlsplit reaches
# its bracket and NFKC checks only inside `if url[:2] == '//'`: a string that
# raised always has a `//` authority for the userinfo pattern to anchor on.
_UNPARSED_USERINFO_RE = re.compile(r"//[^/?#\s]*@")
_UNPARSED_QUERY_PAIR_RE = re.compile(r"([?&])([^?&=#\s]+)=([^&#\s]*)")


def _redact_unparsed_query_pair(match: re.Match[str]) -> str:
    delimiter, name, _value = match.groups()
    # unquote_plus mirrors what parse_qsl does on the parsed path, so an encoded
    # name ("%74oken") is judged sensitive by both and cannot slip through here.
    if not _is_sensitive_query_param(unquote_plus(name)):
        return match.group(0)
    return f"{delimiter}{name}={REDACTED_QUERY_VALUE}"


def _redact_without_parsing(value: str) -> str:
    """Redact a string ``urlsplit`` rejects, lexically and without recursing.

    Deletes credentials in place instead of reconstructing the URL: the caller is
    about to put this in a log line or an error message, and a string the parser
    refused is most useful to whoever reads it unchanged apart from the secrets.
    Handing it back to the URL_LIKE_RE fallback instead would recurse forever,
    because the match would be the same substring that just failed to parse.

    Reusing ``_is_sensitive_query_param`` is what keeps this honest: the fallback
    leaks a credential only in a parameter the parsed path would also have kept,
    so it adds no leak class of its own.
    """
    scrubbed = _UNPARSED_USERINFO_RE.sub(
        lambda _match: f"//{REDACTED_USERINFO}@", value
    )
    return _UNPARSED_QUERY_PAIR_RE.sub(_redact_unparsed_query_pair, scrubbed)


def redact_url_credentials(url: str) -> str:
    """Redact known credential query values and userinfo in a URL-like string."""
    prefixed = _split_prefixed_url(url)
    if prefixed is not None:
        prefix, nested_url = prefixed
        return prefix + redact_url_credentials(nested_url)

    try:
        parts = urlsplit(url)
    except ValueError:
        # fix(#1119): a malformed authority must not turn a redaction call into a
        # raise. Reached both directly and from the URL_LIKE_RE.sub callback
        # below, which recurses here on each matched substring of free text.
        return _redact_without_parsing(url)
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
