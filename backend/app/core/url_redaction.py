"""Helpers for rejecting and redacting credential-bearing URLs and secrets.

Two kinds of redaction live here, and they are complementary rather than
alternatives. The URL helpers scrub by PATTERN — anything shaped like a
credential query parameter or userinfo — and so cover strings nobody knew the
secret for, including a token that only ever existed inside a subprocess's
argv. :func:`scrub_secret_from_exception` scrubs by exact VALUE, for the
callers that do hold the secret, and so covers echoes the pattern cannot
recognise as a URL at all.
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
    registered_credential_secrets,
)

REDACTED_QUERY_VALUE = "<redacted>"
REDACTED_USERINFO = "redacted"
# Deliberately not "<redacted>": this one replaces a bare value wherever it
# appears rather than a name=value pair, so it needs to read as a redaction
# even with no surrounding context.
REDACTED_SECRET = "***"
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
    """Return True if a URL carries credential-like userinfo or query params.

    Also True when the authority is unparsable: callers use this to admit or
    refuse a string, so "cannot tell" has to resolve to refusal, not to "no".
    """
    # fix(#430 BA-04): strip GDAL-style prefixes (ESRIJSON:, WFS:, ...) before
    # inspecting userinfo — otherwise urlsplit sees no netloc and misses
    # `user:pass@` behind the prefix, mirroring redact_url_credentials.
    prefixed = _split_prefixed_url(url)
    if prefixed is not None:
        return has_url_credentials(prefixed[1])
    try:
        parts = urlsplit(url)
    except ValueError:
        # fix(#1132): the same malformed-authority raise #1119 fixed in
        # redact_url_credentials — the mirror stopped at the happy path. The
        # caller that makes it a bug is _metadata_contains_secret in
        # modules/catalog/sources/router.py, which asks this question of every
        # string in a connector config from OUTSIDE the handler's try block, so
        # a raise there is an unhandled 500 instead of the gate's 400.
        #
        # True, not False, and the asymmetry is the whole point: this is a
        # detector, so refusing an authority nobody can parse costs a rejected
        # config that fails loudly and gets fixed, while admitting it makes the
        # gate silently permissive on exactly the input an attacker controls.
        # No credential is reported as absent because the parser gave up.
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
#
# fix(#1119 review 2): they delimit on URL syntax — `/?#` for the authority,
# `&#` for a query value — and NOT on whitespace. An earlier `\s` in these
# classes made the fallback stop at a space that the parser keeps, so it leaked
# strictly MORE than the parsed path, breaking this module's own invariant that
# the fallback only ever keeps what the parsed path would have kept:
#
#   https://user:hunter 2@[::1        returned verbatim; urlsplit ends a netloc
#                                     at `/?#`, never at a space, so the parsed
#                                     path would have redacted the whole userinfo
#   https://[::1?token=prefix hunter2  became `token=<redacted> hunter2`; parse_qsl
#                                     takes the value to the next `&`/`#`, so the
#                                     parsed path would have redacted all of it
#
# Widening is the safe direction for a redactor and the reason is asymmetric:
# over-redaction costs a less informative log line, under-redaction leaks a
# credential and does it silently. Greedy is also correct here rather than
# incidental — urlsplit takes userinfo to the LAST `@` in the authority.
_UNPARSED_USERINFO_RE = re.compile(r"//[^/?#]*@")
_UNPARSED_QUERY_PAIR_RE = re.compile(r"([?&])([^?&=#]+)=([^&#]*)")

# fix(#1119 review): urlsplit DELETES these three characters from anywhere in the
# string before it parses (CPython's `_UNSAFE_URL_BYTES_TO_REMOVE`). Every reader
# in this module has to delete them too, or it is redacting a different string
# from the one the parser saw — and that gap leaked a credential in THREE
# positions, only one of which was reported:
#
#   https://user:hunter2\n@[::1      the fallback's `\s` stopped the userinfo
#                                    match at the control character
#   https://[::1?to\nken=hunter2     the same `\s` hid a sensitive parameter NAME
#   ogrinfo failed: https://user:hunter2\n@[::1 bad
#                                    URL_LIKE_RE stopped at the control character
#                                    and handed the recursion `https://user:hunter2`,
#                                    which has no `@` and so parses as host:port
#                                    with no credential in it at all
#
# The third is the one that matters most (it is the GDAL-stderr path) and it is
# not reachable from the fallback at all, so patching the fallback alone would
# have left the widest hole open. Stripping once at the entry point is what
# collapses the class: the direct parse, URL_LIKE_RE and the unparsable fallback
# then all read the identical string.
#
# The cost, accepted deliberately: a multi-line stderr blob comes back as one
# line. Replacing with a space instead would read better and would NOT fix this —
# a space re-breaks the token for URL_LIKE_RE and the credential survives again.
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

    Deletes credentials in place instead of reconstructing the URL: the caller is
    about to put this in a log line or an error message, and a string the parser
    refused is most useful to whoever reads it unchanged apart from the secrets.
    Handing it back to the URL_LIKE_RE fallback instead would recurse forever,
    because the match would be the same substring that just failed to parse.

    Reusing ``_is_sensitive_query_param`` is what keeps this honest: the fallback
    leaks a credential only in a parameter the parsed path would also have kept,
    so it adds no leak class of its own.

    fix(#1119 reviews 3+4): scrub BOTH lexical views, raw first and NFKC second,
    because normalisation cuts both ways and one pass is blind in one direction:

    - normalising REVEALS a delimiter, which is why the fallback is reached at
      all. ``urlsplit``'s ``_checknetloc`` (CPython ``urllib/parse.py:441``)
      refuses a netloc precisely because NFKC would introduce one of ``/?#@:``.
      The raw view cannot see it, so ``https://user:hunter2＠example.com/path``
      shows no ASCII ``@`` and comes back whole.
    - normalising also INTRODUCES a delimiter mid-credential, which truncates a
      match that was intact before. ``https://user:hunter2／@[::1`` normalises to
      ``…hunter2/@…``, and the userinfo pattern then stops at the new ``/``.
      Same for ``?token=prefix＃hunter2``, where only ``prefix`` gets redacted.

    Two passes, so a credential is redacted when EITHER view shows its bounds.
    Evading both needs a delimiter at the same position in both views — and a
    delimiter present in the RAW view is ASCII, so urlsplit draws that same
    boundary and the parsed path (the reference this fallback is measured
    against) treats it identically. The invariant therefore still holds: the
    fallback never keeps more than the parsed path would.

    The returned string is the normalised one — a fullwidth character reads as
    its ASCII form in the log. That only affects strings that already failed to
    parse, and mapping offsets back through a length-changing normalisation to
    preserve them would be a far better way to introduce a bug than to avoid one.
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
    # fix(#1119 review): normalise to urlsplit's own view FIRST, so every reader
    # below judges the same string the parser does. See _URLSPLIT_STRIPS.
    url = _strip_urlsplit_removals(url)
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


def scrub_registered_credentials(text: str) -> str:
    """Exact-scrub every credential secret registered so far in this
    request/job's context.

    fix(#1770 round 43 P2). The pattern-based helpers in this module
    (``redact_url_credentials`` and, in ``core/logging_config.py``,
    ``_scrub_text``) only ever redact a KNOWN shape: a query parameter whose
    NAME is in ``SENSITIVE_QUERY_PARAMS``, or userinfo. A same-origin
    redirect that reflects the credential into the URL PATH, or into an
    arbitrary query key not on that list (``?echo=<value>``, say), carries
    the secret straight through either pattern untouched, and each new
    reflection SHAPE used to cost its own review round rather than closing
    as a class.

    ``app.core.service_tokens.register_credential_secret`` is called at the
    one place a credential header is ever composed
    (``build_credential_header``), so by the time anything downstream calls
    this, every secret in play for this request/job is already registered --
    exact-value redaction (``scrub_secret_value``, which also expands to the
    Basic cleartext and every URL-encoded form) then finds it wherever it
    was reflected, independent of shape.
    """
    for secret in registered_credential_secrets():
        text = scrub_secret_value(text, secret)
    return text


def redact_exception_text(exc: BaseException) -> str:
    """``str(exc)``, with any URL-shaped substring redacted.

    fix(#1770 round 39): ``httpx.HTTPStatusError`` -- what ``raise_for_status``
    raises -- puts the WHOLE request URL, query string included, into its own
    message: ``"Client error '401 Unauthorized' for url '<url>'"``. A caller
    that reads a response chosen by an untrusted service and logs the caught
    exception's text was logging that URL verbatim, so a service that
    reflects a query parameter shaped like a credential into its own error
    page gets it echoed straight into the log -- the free-text sibling of the
    ``href=`` leak `redact_url_credentials` already closes for a value read
    directly off a link.

    ``redact_url_credentials`` already redacts a URL embedded in arbitrary
    text (its ``URL_LIKE_RE`` fallback for anything that is not, as a WHOLE
    string, a bare ``http``/``https`` URL), so this is that function applied
    to the one shape an exception's text actually has. Safe to call
    unconditionally: an exception whose message carries no URL at all --
    ``httpx.RequestError`` and its connection-level subclasses generally
    don't, the address lives on ``exc.request.url`` instead and is never read
    here -- passes through unchanged.

    fix(#1770 round 43 P2): ``scrub_registered_credentials`` runs second, so a
    reflection the pattern-based pass above cannot see by shape (an arbitrary
    query key, or the URL path) is still caught by exact value.
    """
    return scrub_registered_credentials(redact_url_credentials(str(exc)))


def _basic_cleartext(blob: str) -> set[str]:
    """The username and password inside a base64 basic credential.

    fix(#1746 B2b review r11). Empty on anything it cannot read, and it never
    raises: the value reaching here is whatever a worker was handed, so a blob
    that is truncated, re-encoded, not base64 at all, or not a colon-separated
    pair must degrade to "nothing extra to scrub" rather than replacing a
    failure message with a decoder traceback.

    Padding is restored before decoding because a caller that stripped it is
    the ordinary case for base64 carried in text, and ``validate=True`` so a
    blob with characters outside the alphabet is refused here rather than
    silently decoding to something that is not the credential.

    Nothing is logged, here or by the caller. The whole point of the return
    value is that it is a secret; a decode failure that named the blob would
    put a credential in a log line to explain why it could not be kept out of
    one.
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

    A credential does not necessarily reach stderr in the form the caller
    holds. ``build_gdal_source`` composes the ArcGIS query with ``urlencode``,
    which percent-encodes the value, so a token containing ``/`` or ``+``
    appears encoded in the subprocess argv and therefore in anything GDAL
    echoes back. Scrubbing only the raw form would leave exactly those tokens
    exposed, and they are the ones an operator is least likely to notice.

    Longest first, so a variant that contains another (``a%2Fb`` and its raw
    ``a/b`` share no prefix, but ``quote`` and ``quote_plus`` often agree)
    cannot leave a partial match behind after the first replacement.

    fix(#1746) plan D9: what a worker holds for a header-auth service is a
    finished header line, so the exact value it would scrub is
    ``Authorization: Bearer abc``. An origin that echoes the credential back
    echoes the credential, not the line GeoLens wrapped it in, so the halves
    are scrubbed too: everything after the first ``": "``, and then everything
    after the authentication scheme. The second one restores exactly what this
    function scrubbed before the wire format changed, which is the bare token.
    A secret containing ``": "`` is a line by construction — a username,
    password, header value and bearer token may none of them contain
    whitespace — so this cannot mistake a bare credential for one.

    fix(#1746 B2b review r11): and for basic authentication the encoded blob is
    not the only spelling that can come back. The credential the ORIGIN knows
    is a username and a password, so its own error text says so: "authentication
    failed for user alice", "bad password for alice". GDAL propagates that body
    to stderr, the preview path logs it and the worker paths carry it into
    ``IngestJob.error_message`` and the queue's recorded exception, and base64
    of the pair matches none of it. So the pair is decoded and both halves join
    the variants, alongside every encoded form.
    """
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

    Exact-value redaction, for callers that hold the credential. It is the
    stronger of the two mechanisms in this module precisely because it needs
    no theory about the shape of what it is scrubbing: an echo is caught
    whether it arrives in a query string, a header dump, a driver diagnostic,
    or prose.

    A pathologically short secret over-scrubs the surrounding text. That is
    the safe direction and is left deliberate rather than floored: refusing to
    scrub a four-character token to keep a log tidy is the wrong trade, and the
    pattern-based helpers above still cover it as a query parameter.
    """
    if not secret or not text:
        return text
    for variant in _secret_variants(secret):
        if variant:
            text = text.replace(variant, REDACTED_SECRET)
    return text


def scrub_secret_from_exception(exc: BaseException, secret: str | None) -> None:
    """Scrub *secret* out of an exception's message, in place.

    Rewrites ``args`` rather than raising a replacement, which keeps the
    exception's type, traceback and ``__cause__`` intact — all three matter to
    the callers here: ``_run_service_import_with_wfs_fallback`` dispatches on
    ``IngestionError`` for its namespace retry, and the failure handlers key
    error codes off the class. Constructing a new exception would also fail for
    any class whose ``__init__`` takes more than a message.

    Mutating in place is what makes this reliable at a single call site: every
    downstream reader of that exception — the persisted ``error_message``, the
    log record, the notification reason, and the re-raise the queue records —
    sees the scrubbed text, without each of them having to remember to scrub.

    Covers the whole chain (fix(#1746 B2b review r32)): ``__context__``,
    ``__cause__``, the members of a ``BaseExceptionGroup``, and ``__notes__``
    on each. A traceback renders all of them, so scrubbing only the outermost
    ``args`` left the secret visible in exactly the case that produces a chain
    here — a WFS import that fails, retries unqualified, and fails again.
    """
    if not secret:
        return
    # fix(#1746 B2b review r32): the WHOLE chain, not just the top. A
    # namespace-qualified WFS import that fails twice leaves the first
    # attempt's `IngestionError` as the retry's `__context__`, and the retry's
    # `__cause__` when the auth hint replaces it. Scrubbing only the outermost
    # `args` left a username or password the first GDAL attempt echoed sitting
    # in the chained traceback that exception logging renders and the queue's
    # bare re-raise records. Every reader of the outer exception is a reader of
    # its chain.
    #
    # `id()` rather than the exception itself: `__eq__` is not defined for most
    # exception types, and a set of them would compare by identity anyway, but
    # saying so removes the question. A cycle is not hypothetical -- assigning
    # `e.__context__ = e` is legal and `raise X from Y` inside a handler for Y
    # builds a two-node one -- so the visited set is what terminates this, and
    # the depth bound is a second floor under a chain that is merely long.
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
                # A group carries its members beside the chain rather than in
                # it, so following only `__context__`/`__cause__` walks past
                # them. `anyio` and `asyncio.TaskGroup` raise these, and this
                # module's callers run under both.
                getattr(current, "exceptions", None) or ()
                if isinstance(current, BaseExceptionGroup)
                else ()
            ),
        ):
            if isinstance(linked, BaseException):
                pending.append((linked, depth + 1))


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
