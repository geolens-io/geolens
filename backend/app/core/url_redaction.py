"""Helpers for rejecting and redacting credential-bearing URLs and secrets.

Two complementary mechanisms: the URL helpers scrub by PATTERN (a credential
query parameter or userinfo shape), covering secrets nobody holds directly.
:func:`scrub_secret_from_exception` scrubs by exact VALUE, for callers that
do hold the secret, covering echoes the pattern can't recognise as a URL.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from urllib.parse import (
    parse_qsl,
    quote,
    quote_plus,
    unquote_plus,
    urlencode,
    urlsplit,
    urlunsplit,
)

from app.core.service_tokens import (
    BASIC_SCHEME,
    HEADER_LINE_SEPARATOR,
    HEADER_TOKEN_MIN_LENGTH,
    registered_credential_secrets,
)

REDACTED_QUERY_VALUE = "<redacted>"
REDACTED_USERINFO = "redacted"
# Deliberately not "<redacted>": this one replaces a bare value wherever it
# appears rather than a name=value pair, so it needs to read as a redaction
# even with no surrounding context.
REDACTED_SECRET = "***"
# fix(#1116): scheme prefix bounded to 64 chars (longer than any real URI
# scheme) — an unbounded `+` here is ReDoS-ambiguous against `https?` and was
# O(n²) on GDAL stderr/VRT paths. A longer prefix still redacts correctly.
URL_LIKE_RE = re.compile(r"(?:(?:[A-Za-z0-9_+.-]{1,64}:)?https?://)[^\s\"'<>]+")

# fix(#2044 review x3/x4/x9): matches "<scheme>://<userinfo>@" anywhere, for
# ANY scheme. `\s` excluded on purpose: free text has no /?# to stop an
# unbounded authority scan at, so allowing it swallows later unrelated prose.
_ANY_SCHEME_USERINFO_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9+.-]{0,63}://)[^\s\"'<>/?#]*@"
)

# fix(#2044 review x13): "<scheme>://...?..." for any NON-http(s) scheme
# with a `?` (http(s) is URL_LIKE_RE's job; re-matching its output here once
# misread a truncated leftover as unredacted). Bounded like URL_LIKE_RE — can't exclude `/`, was quadratic without it.
_ANY_SCHEME_QUERY_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])(?!https?://)"
    r"[A-Za-z][A-Za-z0-9+.-]{0,63}://[^\s\"'<>?]{0,2048}\?[^\s\"'<>]*"
)

SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        # fix(#1755): ArcGIS's own token query param, distinct
        # from the generic "api_key"/"token" already here.
        "authkey",
        "client_secret",
        "code",
        "key",
        # fix(#1755): Maxar's named API key query parameter,
        # for the same reason as "authkey" above.
        "maxar_api_key",
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
    # fix(#1770): a redactor must never raise on its own input —
    # `max_num_fields` would crash INSIDE exception handling. See
    # `service_endpoints.bounded_parse_qsl` for sites that DO need the bound.
    pairs = parse_qsl(query, keep_blank_values=True)  # parse_qs: unbounded
    return any(_is_sensitive_query_param(key) for key, _ in pairs)


def has_url_credentials(url: str) -> bool:
    """Return True if a URL carries credential-like userinfo or query params.

    Also True when the authority is unparsable: callers use this to admit or
    refuse a string, so "cannot tell" has to resolve to refusal, not to "no".
    """
    # fix(#430): strip GDAL-style prefixes (ESRIJSON:, WFS:, ...) before
    # inspecting userinfo — otherwise urlsplit sees no netloc and misses
    # `user:pass@` behind the prefix, mirroring redact_url_credentials.
    prefixed = _split_prefixed_url(url)
    if prefixed is not None:
        return has_url_credentials(prefixed[1])
    try:
        parts = urlsplit(url)
    except ValueError:
        # fix(#1132): mirrors #1119. Caller (_metadata_contains_secret) calls
        # this outside its try block, so a raise is an unhandled 500. Return
        # True, not False: "can't parse" must refuse, never silently admit.
        return True
    return bool(parts.username or parts.password) or query_has_credentials(parts.query)


def _split_prefixed_url(value: str) -> tuple[str, str] | None:
    """Split GDAL-style prefixes such as ``ESRIJSON:https://...``."""
    prefix, sep, rest = value.partition(":")
    if not sep or prefix.lower() in {"http", "https"}:
        return None
    if rest.startswith(("http://", "https://")):
        return f"{prefix}:", rest
    return None


def redact_query_credentials(query: str) -> str:
    """Redact known credential query values, preserving non-sensitive params."""
    if not query:
        return query
    prefix = "?" if query.startswith("?") else ""
    raw_query = query[1:] if prefix else query
    # fix(#1770): same reasoning as `query_has_credentials`
    # above -- a redactor must never raise on its own input.
    pairs = parse_qsl(raw_query, keep_blank_values=True)  # parse_qs: unbounded
    if not any(_is_sensitive_query_param(key) for key, _ in pairs):
        return query
    return prefix + urlencode(
        [
            (key, REDACTED_QUERY_VALUE if _is_sensitive_query_param(key) else value)
            for key, value in pairs
        ]
    )


# fix(#1119): urlsplit raises ValueError on a malformed bracketed authority
# (e.g. "https://[::1"); redact_url_credentials must return a safe string to
# log, never raise. Two patterns suffice: urlsplit only reaches its bracket
# and NFKC checks inside `if url[:2] == '//'`, so a string that raised always
# has a `//` authority for the userinfo pattern to anchor on.
#
# fix(#1119): both patterns delimit on URL syntax (`/?#` for the
# authority, `&#` for a query value), never on whitespace — a `\s` class
# stops early and leaks MORE than the parsed path would have redacted.
# Widening is always the safe direction here: under-redaction leaks silently.
_UNPARSED_USERINFO_RE = re.compile(r"//[^/?#]*@")
_UNPARSED_QUERY_PAIR_RE = re.compile(r"([?&])([^?&=#]+)=([^&#]*)")

# fix(#1119): urlsplit deletes \t\r\n from anywhere in the string
# before parsing (CPython's `_UNSAFE_URL_BYTES_TO_REMOVE`); every reader here
# must strip them too or it scrubs a different string than urlsplit saw —
# this gap let a credential through past a stray control char in the GDAL-
# stderr path. Cost accepted: a multi-line blob collapses to one line.
_URLSPLIT_STRIPS = ("\t", "\r", "\n")


def _strip_urlsplit_removals(value: str) -> str:
    for removed in _URLSPLIT_STRIPS:
        value = value.replace(removed, "")
    return value


def _redact_unparsed_query_pair(match: re.Match[str]) -> str:
    delimiter, name, _value = match.groups()
    # unquote_plus mirrors what parse_qsl does on the parsed path, so an encoded
    # name ("%74oken") is judged sensitive by both and cannot slip through here.
    if not _is_sensitive_query_param(unquote_plus(name)):
        return match.group(0)
    return f"{delimiter}{name}={REDACTED_QUERY_VALUE}"


def _redact_without_parsing(value: str) -> str:
    """Redact a string ``urlsplit`` rejects, lexically and without recursing.

    Deletes credentials in place rather than reconstructing the URL, and never
    hands the result back to the URL_LIKE_RE fallback — the same substring
    just failed to parse, so that would recurse forever.

    fix(#1119): scrubs both the raw string and its NFKC-normalised
    form. Normalisation cuts both ways: it can REVEAL a delimiter ``urlsplit``
    would have rejected (e.g. a fullwidth ``＠``), or INTRODUCE one mid-
    credential that truncates an otherwise-intact match. Either view showing a
    boundary is enough to redact, so evading both needs an ASCII delimiter at
    the same position in both — which the parsed path would also catch.

    Returns the normalised string, so a fullwidth character reads as ASCII in
    the log; only affects strings that already failed to parse.
    """
    # Pass 2 normalises the OUTPUT of pass 1, not the original: chaining is what
    # keeps pass 1's redactions: `//redacted@` survives NFKC unchanged, so the
    # second pass adds to the first rather than replacing it.
    scrubbed = _scrub_one_view(value)
    return _scrub_one_view(unicodedata.normalize("NFKC", scrubbed))


def _scrub_one_view(value: str) -> str:
    """Apply both fallback patterns to a single lexical view of the string."""
    userinfo_scrubbed = _UNPARSED_USERINFO_RE.sub(
        lambda _match: f"//{REDACTED_USERINFO}@", value
    )
    return _UNPARSED_QUERY_PAIR_RE.sub(_redact_unparsed_query_pair, userinfo_scrubbed)


def redact_url_credentials(url: str) -> str:
    """Redact known credential query values and userinfo in a URL-like string."""
    # fix(#1119): normalise to urlsplit's own view FIRST, so every reader
    # below judges the same string the parser does. See _URLSPLIT_STRIPS.
    url = _strip_urlsplit_removals(url)
    prefixed = _split_prefixed_url(url)
    if prefixed is not None:
        prefix, nested_url = prefixed
        return prefix + redact_url_credentials(nested_url)

    try:
        parts = urlsplit(url)
    except ValueError:
        # fix(#1119): a malformed authority must not turn a redaction call into
        # a raise. A malformed http(s) SPAN inside free text is instead caught
        # by _redact_http_span below, without recursing back through here.
        return _redact_without_parsing(url)
    redacted = url
    is_http = parts.scheme.lower() in {"http", "https"}
    # fix(#2044 review x9/x10): trust this split's netloc with a real /?#
    # boundary, or at most one `@` — either way no OTHER `@` it could have
    # reached past prose to (review x9's two-`@` case couldn't say that).
    has_boundary = bool(parts.path or parts.query or parts.fragment)
    unambiguous = has_boundary or parts.netloc.count("@") <= 1
    # fix(#2044 review x11/x12): a genuinely recognised scheme is what tells
    # a real (if opaque/no-authority, e.g. myapp:/callback) URI apart from
    # the bare `?` urlsplit finds in scheme-less free text (scheme='') too.
    has_real_url = bool(parts.scheme)
    if has_real_url and (
        is_http or parts.query or (unambiguous and (parts.username or parts.password))
    ):
        redacted = _redact_netloc_and_query(url, parts, scan_fragment=True)
    redacted = _scan_embedded_url_credentials(redacted)
    return redacted if redacted != url else url


def _scan_embedded_url_credentials(text: str, *, scan_fragment: bool = True) -> str:
    """Redact a credential in an EMBEDDED URL anywhere in ``text``: an
    http(s) URL (full treatment), any scheme with a query (full treatment,
    fix #2044 review x13), or any scheme's bare userinfo.

    fix(#2044 review x7): urlsplit's split of the OUTER string can put a
    second scheme's authority in the wrong component (reviews x1-x6) — this
    scans the raw text instead.

    ``scan_fragment`` threads the same bound as ``_redact_netloc_and_query``
    (review x12) into each match's own redaction, so chained or nested
    input can't grow the call stack either way (review x5/x6).
    """
    text = URL_LIKE_RE.sub(
        lambda match: _redact_http_span(match.group(0), scan_fragment=scan_fragment),
        text,
    )
    text = _ANY_SCHEME_QUERY_RE.sub(
        lambda match: _redact_http_span(match.group(0), scan_fragment=scan_fragment),
        text,
    )
    return _ANY_SCHEME_USERINFO_RE.sub(rf"\1{REDACTED_USERINFO}@", text)


def _redact_netloc_and_query(  # type: ignore[no-untyped-def]
    url: str, parts, *, scan_fragment: bool
) -> str:
    """Redact one recognised URL's userinfo, sensitive query params, and
    (if ``scan_fragment``) a nested credential hiding in the fragment.

    Slices ``parts.netloc`` at its last ``@`` rather than rebuilding through
    ``.hostname``/``.port`` — those normalise and silently drop a character
    (fix #2044 review x2) when netloc absorbed text that isn't really a host.

    fix(#2044 review x11): query redaction applies to any scheme, not just
    http — ``?password=`` is a connection-string convention, and
    SENSITIVE_QUERY_PARAMS already names params no http service defines.
    """
    _, sep, host_part = parts.netloc.rpartition("@")
    redacted_netloc = f"{REDACTED_USERINFO}@{host_part}" if sep else parts.netloc
    redacted_query = parts.query
    if parts.query:
        # fix(#2044 review x6): scan BEFORE redact_query_credentials — once
        # any one param is sensitive it re-urlencodes every value, which
        # would percent-escape an embedded credential's "://" out of reach.
        redacted_query = redact_query_credentials(
            _scan_query_value_credentials(parts.query)
        )
    redacted_fragment = parts.fragment
    if scan_fragment and parts.fragment:
        # fix(#2044 review x12): a credential can hide in the fragment with
        # no whitespace to separate it from this URL — scan_fragment=False
        # here bounds it to one extra level (see _scan_embedded_url_credentials).
        redacted_fragment = _scan_embedded_url_credentials(
            parts.fragment, scan_fragment=False
        )
    if (
        redacted_netloc == parts.netloc
        and redacted_query == parts.query
        and redacted_fragment == parts.fragment
    ):
        return url
    return urlunsplit(
        (parts.scheme, redacted_netloc, parts.path, redacted_query, redacted_fragment)
    )


def _scan_query_value_credentials(query: str) -> str:
    """Redact an embedded userinfo credential inside each query VALUE.

    fix(#2044 review x9): scanning the raw query let a match cross the `&`
    pair boundary, swallowing a sibling param as "userinfo" — scanning each
    already-split value (parse_qsl) instead keeps the match inside it.
    """
    # fix(#1770): same reasoning as `query_has_credentials` above -- a
    # redactor must never raise on its own input.
    pairs = parse_qsl(query, keep_blank_values=True)  # parse_qs: unbounded
    if not pairs:
        return query
    scanned = [
        (key, _ANY_SCHEME_USERINFO_RE.sub(rf"\1{REDACTED_USERINFO}@", value))
        for key, value in pairs
    ]
    return query if scanned == pairs else urlencode(scanned)


def _redact_http_span(span: str, *, scan_fragment: bool = True) -> str:
    """Redact userinfo and sensitive query params in one URL-shaped span
    matched by ``_scan_embedded_url_credentials``'s two URL regexes.

    Never calls back into ``redact_url_credentials``. ``scan_fragment``
    just threads through to ``_redact_netloc_and_query`` — see its own
    docstring for the depth bound this keeps.
    """
    prefixed = _split_prefixed_url(span)
    prefix, rest = prefixed if prefixed is not None else ("", span)
    try:
        parts = urlsplit(rest)
    except ValueError:
        return prefix + _redact_without_parsing(rest)
    return prefix + _redact_netloc_and_query(rest, parts, scan_fragment=scan_fragment)


def scrub_registered_credentials(text: str) -> str:
    """Exact-scrub every credential secret registered so far in this
    request/job's context.

    fix(#1770): the pattern-based helpers (``redact_url_credentials``,
    ``logging_config._scrub_text``) only catch a KNOWN shape — a listed query
    param name or userinfo. A reflected credential in the URL path or an
    unlisted query key slips through untouched.

    ``register_credential_secret`` is called wherever a credential header or
    URL is composed (``build_credential_header``; fix(#1840): also
    ``adapters/arcgis.py::_query_form_credential``), so by the time this runs
    every secret in play is registered and ``scrub_secret_value`` finds it
    regardless of shape.
    """
    for secret in registered_credential_secrets():
        text = scrub_secret_value(text, secret)
    return text


# fix(#1953): libpq keyword/value connection detail. GDAL echoes the `PG:`
# destination it was handed on a connection failure, and that DSN carries the
# password, which is no URL and no registered request credential, beside the
# database topology fix(#1953) keeps out of a stored reason with it.
_LIBPQ_VALUE_RE = re.compile(
    r"(?i)\b(password|sslpassword|host|hostaddr|port|dbname|user|sslrootcert)"
    r"\s*=\s*(?:'(?:[^'\\]|\\.)*'|\S*)"
)

# fix(#1953): a path GDAL echoes back names the server's layout, `/vsi` handles
# included. The lookbehind keeps a URL's own path out of it: there the slash
# follows the host, never a space or a quote.
_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w/:])(?:/[\w.+-]+){2,}/?")


def redact_libpq_credentials(text: str) -> str:
    """Mask the values in a libpq keyword/value connection string.

    Handles both spellings ``libpq_value`` emits: a bare token, and a
    single-quoted value with backslash escapes.
    """
    return _LIBPQ_VALUE_RE.sub(rf"\1={REDACTED_QUERY_VALUE}", text)


def redact_filesystem_paths(text: str) -> str:
    """Mask absolute paths and ``/vsi`` handles, keeping the text around them."""
    return _ABSOLUTE_PATH_RE.sub(REDACTED_QUERY_VALUE, text)


def redact_exception_text(exc: BaseException) -> str:
    """``str(exc)``, with any URL-shaped substring redacted.

    fix(#1770): ``httpx.HTTPStatusError`` embeds the WHOLE request
    URL, query string included, in its message — an untrusted service that
    reflects a credential-shaped query param into its own error page gets it
    logged verbatim. Reuses ``redact_url_credentials``'s ``URL_LIKE_RE``
    fallback for text that isn't, as a whole, a bare URL. Safe on exceptions
    with no URL in their message (e.g. ``httpx.RequestError``, whose address
    lives on ``exc.request.url`` and is never read here).

    fix(#1770): ``scrub_registered_credentials`` runs second, to
    catch reflections the pattern pass above can't see by shape.
    """
    return scrub_registered_credentials(redact_url_credentials(str(exc)))


def _basic_cleartext(blob: str) -> set[str]:
    """The username and password inside a base64 basic credential.

    fix(#1746): never raises — a blob that's truncated, not
    base64, or not a colon-separated pair degrades to an empty set rather than
    surfacing a decoder traceback. Padding is restored before decoding;
    ``validate=True`` refuses out-of-alphabet input. Nothing is logged here: a
    decode-failure message naming the blob would itself leak the credential.
    """
    try:
        decoded = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode(
            "utf-8"
        )
    except (ValueError, TypeError):
        # binascii.Error and UnicodeDecodeError are both ValueError subclasses;
        # TypeError is belt to those braces for a non-str blob.
        return set()
    username, separator, password = decoded.partition(":")
    if not separator:
        return set()
    # Empties dropped: a blank half scrubs nothing and `str.replace` with an
    # empty needle would insert the marker between every character.
    return {half for half in (username, password) if half}


def _secret_variants(secret: str) -> list[str]:
    """Every spelling of *secret* that could appear in a captured string.

    Percent-encoded forms too: ``build_gdal_source`` composes the ArcGIS
    query with ``urlencode``, so a token with ``/`` or ``+`` shows up encoded
    in subprocess argv and GDAL's echo of it. Longest first, so a variant
    containing another can't leave a partial match after the first
    replacement.

    fix(#1746) plan D9: a worker holds a finished header line
    (``Authorization: Bearer abc``), not the bare secret, so an origin that
    echoes it back echoes the line's tail after ``": "``, and after the auth
    scheme — both added as variants alongside the bare token.

    fix(#1746): basic-auth failures can also come back as
    cleartext prose ("bad password for alice") rather than the base64 blob,
    so the decoded username/password join the variants too.
    """
    # fix(#1844): no length floor here or on the secret — round 1
    # added one and it silently stopped scrubbing short-but-valid credentials
    # (e.g. an 8-char API key). Under-scrubbing a valid secret is not a trade.
    forms = {secret}
    _, separator, tail = secret.partition(HEADER_LINE_SEPARATOR)
    if separator and tail:
        forms.add(tail)
        _, space, rest = tail.partition(" ")
        if space and rest:
            forms.add(rest)
        if tail.startswith(BASIC_SCHEME):
            forms.update(_basic_cleartext(tail[len(BASIC_SCHEME) :]))
    variants = set()
    for form in forms:
        variants.update({form, quote(form, safe=""), quote_plus(form)})
    return sorted(variants, key=len, reverse=True)


def scrub_secret_value(text: str, secret: str | None) -> str:
    """Replace every spelling of *secret* in *text* with :data:`REDACTED_SECRET`.

    Exact-value redaction: catches an echo in a query string, header dump,
    driver diagnostic, or prose, with no theory needed about its shape.

    A short secret over-scrubs surrounding text — the safe direction, left
    unfloored deliberately; the pattern-based helpers above still cover it as
    a query parameter.
    """
    if not secret or not text:
        return text
    for variant in _secret_variants(secret):
        if variant:
            text = text.replace(variant, REDACTED_SECRET)
    return text


# fix(#1764): a refusal gate is not a redactor. `scrub_secret_value` matches
# any substring on purpose, because over-scrubbing costs nothing; refusing a
# URL that way would strand every legitimate refresh once a credential is
# short enough to occur by accident (a one-character Basic username matches
# almost any URL). So a SHORT variant has to BE a whole token, and only a
# variant at least this long is matched loose.
_CREDENTIAL_MATCH_FLOOR = HEADER_TOKEN_MIN_LENGTH

# What can surround a credential value in a URL or a JSON document. Splitting
# on it turns `?key=abc` and `"k":"abc"` alike into the token `abc`. The kept
# characters are the unreserved set plus the percent-encoding and base64
# spellings a variant can carry, so an encoded form stays one token.
_CREDENTIAL_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9._~%+-]+")


def carries_registered_credential(text: str) -> bool:
    """Whether *text* contains a credential composed in this request/job.

    fix(#1764): the non-destructive form of :func:`scrub_secret_value`, for a
    caller deciding whether to STORE a string rather than whether to log one.
    An origin can reflect the credential it was sent into a URL it publishes,
    under any parameter name, and ``has_url_credentials`` is an allowlist of
    NAMES rather than a check of values.

    Reads the same ``_secret_variants`` vocabulary, so the tail after ``": "``,
    the part after an auth scheme, a Basic blob's cleartext and every
    percent-encoded spelling all count. Empty registry, so no credential in
    this context, means False.

    See ``_CREDENTIAL_MATCH_FLOOR`` for why a short variant is matched as a
    whole token rather than as any substring.
    """
    if not text:
        return False
    tokens: set[str] | None = None
    for secret in registered_credential_secrets():
        for variant in _secret_variants(secret):
            if not variant:
                continue
            if len(variant) >= _CREDENTIAL_MATCH_FLOOR:
                if variant in text:
                    return True
                continue
            # Computed once, and only when a short variant is in play.
            if tokens is None:
                tokens = set(_CREDENTIAL_TOKEN_SPLIT.split(text))
            if variant in tokens:
                return True
    return False


def scrub_secret_from_exception(exc: BaseException, secret: str | None) -> None:
    """Scrub *secret* out of an exception's message, in place.

    Mutates ``args`` rather than raising a replacement, keeping type,
    traceback and ``__cause__`` intact — callers dispatch on exception class
    (``_run_service_import_with_wfs_fallback``'s namespace retry) and key
    error codes off it. A single mutation site means every downstream reader
    (persisted ``error_message``, log record, re-raise) sees scrubbed text.

    fix(#1746): walks the whole chain — ``__context__``,
    ``__cause__``, ``BaseExceptionGroup`` members, and their ``__notes__`` —
    since a traceback renders all of them and a retried WFS import chains.
    """
    if not secret:
        return
    # fix(#1746): `id()` not equality — most exception types
    # don't define `__eq__`. A cycle is real (`e.__context__ = e` is legal),
    # so `seen` plus a depth bound terminate the walk.
    seen: set[int] = set()
    pending: list[tuple[BaseException, int]] = [(exc, 0)]
    while pending:
        current, depth = pending.pop()
        if id(current) in seen or depth > _MAX_EXCEPTION_CHAIN_DEPTH:
            continue
        seen.add(id(current))
        _scrub_one_exception(current, secret)
        for linked in (
            current.__context__,
            current.__cause__,
            *(
                # A group carries members beside the chain, not in it —
                # __context__/__cause__ alone misses them (anyio, TaskGroup).
                getattr(current, "exceptions", None) or ()
                if isinstance(current, BaseExceptionGroup)
                else ()
            ),
        ):
            if isinstance(linked, BaseException):
                pending.append((linked, depth + 1))


def scrub_registered_credentials_from_exception(exc: BaseException) -> None:
    """Scrub every credential secret registered so far in this request/job's
    context out of *exc*, in place, over its whole chain.

    fix(#1770): the string form's ``registered_credential_secrets()``
    reads a plain ``ContextVar``, which only answers correctly inside the SAME
    async task that registered it. Starlette's ``BaseHTTPMiddleware.dispatch``
    runs the route handler in a separate spawned task, so an exception handler
    or middleware ``except`` clause outside that task always reads the
    registry as empty — measured directly, this fails silently.

    Closed by calling this from ``CredentialScrubASGIMiddleware``
    (``api/middleware/credential_scrub.py``), a plain ASGI callable that spawns
    no task of its own, so as long as it's the INNERMOST middleware it shares
    the handler's task and can read what it registered. Exact-value mutation,
    same as ``scrub_secret_from_exception``, so the object already carries
    scrubbed text by the time anything outside this task reads it.
    """
    for secret in registered_credential_secrets():
        scrub_secret_from_exception(exc, secret)


# A chain longer than this is a runaway rather than a diagnosis, and walking it
# is work done while a job is already failing.
_MAX_EXCEPTION_CHAIN_DEPTH = 50


def _scrub_one_exception(exc: BaseException, secret: str) -> None:
    """Scrub the two places an exception carries text of its own."""
    if exc.args:
        exc.args = tuple(
            scrub_secret_value(arg, secret) if isinstance(arg, str) else arg
            for arg in exc.args
        )
    # `add_note` text is rendered by the traceback machinery exactly like the
    # message is, and nothing else scrubs it.
    notes = getattr(exc, "__notes__", None)
    if isinstance(notes, list):
        exc.__notes__ = [
            scrub_secret_value(note, secret) if isinstance(note, str) else note
            for note in notes
        ]
