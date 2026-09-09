"""One definition of what a service credential may look like.

fix(#1277): the API door and the worker's
``_sanitize_authorization_token`` judged the same token differently — the
door accepted anything printable, the worker pinned header tokens to
base64url with an 8-char floor — so a token with ``+``/``/`` got a 202,
burned its single-use credential, and failed only later in the background.

Not negotiable down: the token becomes an ``Authorization`` header line
reaching libcurl through GDAL, so a disallowed character is a header-
smuggling primitive (SEC-FU-04). Both the door and the worker enforce this
module's policy, so the guarantee doesn't rest on a validator two processes
away.

Lives in ``core/``: ``modules/catalog`` (request schema) and
``processing/ingest`` (GDAL invocation) may not import each other, but both
may import here.
"""

from __future__ import annotations

import base64
import string
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum

# The services whose credential becomes a line in the 0600 GDAL header file.
# ArcGIS is deliberately absent: on the GDAL path its token stays a query
# parameter, urlencoded into the ESRIJSON source URL, so it never carries the
# smuggling risk this charset guards against. This set answers whether a
# format's credential is (a) judged by ``HEADER_TOKEN_CHARSET``, (b) written
# to ``GDAL_HTTP_HEADER_FILE``, and (c) checked by
# ``assert_endpoints_stay_on_origin``. All three exclude ArcGIS.
#
# feat(#1764): the fourth question, "crossed to the worker as a finished
# header LINE" (plan D9), is ``HEADER_LINE_SERVICE_FORMATS`` below.
#
# fix(#1840): (d) was missing here, producing a P1 —
# ``wire_credential`` picked its branch by whether ``build_credential_header``
# returned None, which stopped being equivalent once lane C2 added an ArcGIS
# header for the httpx transport.
#
# fix(#1840): a consumer that decides by FORMAT must ask
# ``requires_header_token_policy`` by name (``wire_credential``,
# ``sources/router.py::_probe_credential_line``,
# ``processing/ingest/ogr.py::_sanitize_authorization_token``), never infer
# from the builder's answer. Three others safely branch on ``pair is not
# None`` only because their caller already fences them to a WFS/OAPIF
# source; un-fencing any of those needs the predicate added back.
HEADER_AUTH_SERVICE_FORMATS: frozenset[str] = frozenset({"wfs", "ogcapi_features"})

# feat(C2): ArcGIS's own service format, spelled here (not imported from the
# adapter) because ``core/`` may not import ``app.modules.*``; the adapter
# re-exports this name.
ARCGIS_SERVICE_FORMAT = "arcgis_featureserver"

# feat(#1764): STAC's own service format, spelled here for the same reason.
# It matches ``datasets.source_format`` for a STAC-imported dataset, which is
# what the refresh door reads before it composes anything.
STAC_SERVICE_FORMAT = "stac"

# feat(#1764): formats whose credential is a header LINE rather than a URL
# query parameter, on every transport including the queue hop (plan D9). Also
# the question ``service_carries_method`` asks about basic and header-key.
#
# Wider than ``HEADER_AUTH_SERVICE_FORMATS`` by exactly STAC, whose reads are
# httpx and never GDAL, so no STAC credential reaches the 0600 header file.
#
# fix(#1764): STAC DOES follow service-described endpoints (an item's self
# link, its asset hrefs); they are checked by
# ``stac_resolve_identity.credential_for_read``, not by
# ``assert_endpoints_stay_on_origin``, which asks a GDAL question.
HEADER_LINE_SERVICE_FORMATS: frozenset[str] = HEADER_AUTH_SERVICE_FORMATS | {
    STAC_SERVICE_FORMAT
}

# feat(C2): formats whose credential travels as an HTTP header on GeoLens's
# OWN httpx requests — wider than the set above. ArcGIS Server has accepted a
# bearer token in a header since 10.5.1, and hosted ArcGIS Online always has;
# measured live 2026-09-04 against services6.arcgis.com (header and
# ``?token=`` forms return identical counts, no Referer needed). Sent as
# ``X-Esri-Authorization`` (see ``ESRI_AUTHORIZATION_HEADER`` for why not the
# standard name) to keep the token out of the request URL, and so out of
# httpx's INFO log line, proxy/load-balancer access logs, and echoed
# exception text.
#
# A separate set, not a widened ``HEADER_AUTH_SERVICE_FORMATS``, because all
# three of that set's questions are still no for ArcGIS: base64url would
# refuse tokens holding ``+``/``/``, nothing writes ArcGIS to the GDAL header
# file, and the adapter composes URLs from its own base rather than
# following a service-described endpoint.
HEADER_TRANSPORT_SERVICE_FORMATS: frozenset[str] = HEADER_LINE_SERVICE_FORMATS | {
    ARCGIS_SERVICE_FORMAT
}

# SEC-FU-04 (sec-audit-20260519.md line 535, Phase 1063-03): JWT-shaped tokens
# use the base64url charset (RFC 4648 §5) plus dot separators (RFC 7519 —
# header.payload.signature). Restricting to this set prevents a token
# containing CR/LF from smuggling extra HTTP headers into libcurl.
HEADER_TOKEN_CHARSET: frozenset[str] = frozenset(
    string.ascii_letters + string.digits + "._-="
)

# The floor is intentional: a minimal three-segment JWT exceeds 20 characters,
# and accepting 1-7 character tokens lets an upstream truncation — a quoted
# JSON field cut at the wrong index, a short tracking token mistaken for a
# bearer — slip into the header pipeline unnoticed.
HEADER_TOKEN_MIN_LENGTH = 8

# Describes the policy and never the input. Both call sites render this: the
# API's 422 must not echo a rejected credential back to the caller, and a
# worker-side message ends up in logs and job rows.
HEADER_TOKEN_POLICY = (
    "This service authenticates with a header token, which must be at least "
    f"{HEADER_TOKEN_MIN_LENGTH} characters and use only the base64url "
    "alphabet: A-Z, a-z, 0-9, and the characters . _ - =. Characters outside "
    "that set cannot be sent safely in an HTTP header."
)


def header_token_rejection_reason(token: str | None) -> str | None:
    """Why *token* is unusable as a header credential, or None if it is fine.

    Returns a description of the POLICY, never a description of the token.
    Naming the offending character would be more helpful and would also put a
    fragment of a credential into an API response, a log line, and a job row —
    the caller already has the token and can compare it against the rule.
    """
    if token is None:
        return None
    if len(token) < HEADER_TOKEN_MIN_LENGTH:
        return HEADER_TOKEN_POLICY
    if any(character not in HEADER_TOKEN_CHARSET for character in token):
        return HEADER_TOKEN_POLICY
    return None


def requires_header_token_policy(source_format: str | None) -> bool:
    """Whether *source_format*'s credential becomes a GDAL header-file line.

    Which is also the question ``HEADER_TOKEN_CHARSET`` and
    ``assert_endpoints_stay_on_origin`` ask. Not the same question as
    :func:`sends_credential_as_header`, which is about GeoLens's own httpx
    requests and includes ArcGIS.
    """
    return source_format in HEADER_AUTH_SERVICE_FORMATS


def carries_credential_as_header_line(source_format: str | None) -> bool:
    """Whether *source_format*'s credential is a header line, not a query key.

    feat(#1764): the question a door asks before accepting a basic or
    header-key credential, and the one ``wire_credential`` asks before
    composing the line that crosses the queue. Wider than
    :func:`requires_header_token_policy` by exactly STAC, whose credential is
    a header on every hop and never reaches GDAL.
    """
    return source_format in HEADER_LINE_SERVICE_FORMATS


def sends_credential_as_header(source_format: str | None) -> bool:
    """Whether *source_format*'s credential travels as an HTTP header.

    feat(C2): the gate ``build_credential_header`` reads. Wider than
    :func:`requires_header_token_policy` by exactly ArcGIS, whose token
    became an ``X-Esri-Authorization: Bearer`` header on the httpx path
    while staying a query parameter on the GDAL path.
    """
    return source_format in HEADER_TRANSPORT_SERVICE_FORMATS


# fix(#1746): username/password and named API-key credentials for the two
# header-auth service formats, alongside the bearer token. The rules below
# judge the INPUTS a caller typed; ``build_credential_header`` composes the
# header afterward. That order matters: a composed Basic line contains a
# space and colon, which ``HEADER_TOKEN_CHARSET`` would reject — so that
# charset stays untouched, judging only a bare bearer token, while a
# validated username/password's base64 encoding is safe by construction.

# Printable ASCII with no whitespace (0x21-0x7E). Non-ASCII is rejected
# deliberately: both header-file writers encode with ``.encode("ascii")``,
# so an accented character would raise UnicodeEncodeError in the worker,
# after the single-use credential is already spent. Narrower than RFC 7617's
# UTF-8 default on purpose — the failure this avoids needs re-entering the
# credential to recover from.
CREDENTIAL_INPUT_CHARSET: frozenset[str] = frozenset(
    character for character in string.printable if not character.isspace()
)

# RFC 7230 tchar — what an HTTP field name may contain. No colon or space,
# so a name carrying either can't smuggle a second header line or a value.
HEADER_NAME_CHARSET: frozenset[str] = frozenset(
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~"
)

# fix(#1746): a composed line's VALUE charset — the input charset plus a
# space, since a value carries a scheme prefix (``Bearer <token>``, ``Basic
# <blob>``). Still no line break, so it can't smuggle a second header.
HEADER_LINE_VALUE_CHARSET: frozenset[str] = CREDENTIAL_INPUT_CHARSET | {" "}

# The one separator ``credential_header_line`` joins with and the worker
# splits on. Named so the joiner and the parser cannot drift into two
# spellings of the same rule.
HEADER_LINE_SEPARATOR = ": "

# The scheme prefix the bearer branch composes, and the prefix the worker
# recognizes to decide that the stricter base64url charset applies.
BEARER_SCHEME = "Bearer "

# fix(#1840): the header ArcGIS's own bearer token travels under.
# Esri documents this name because a deployment may consume the standard
# one: ArcGIS Enterprise behind a Web Adaptor or web-tier auth (IWA/PKI in
# IIS) answers 401/403 to `Authorization` before ArcGIS ever sees it. Hosted
# ArcGIS Online accepts either (measured 2026-09-04). Safe on a cross-origin
# redirect: this name is in `_ALWAYS_CREDENTIAL_HEADERS`
# (`app/platform/security.py`) and `_refuse_cross_origin_credential` refuses
# such a hop rather than following it — louder than httpx's silent strip of
# `Authorization`. GDAL never sends this: the ArcGIS ingest path still
# percent-encodes the token into the ESRIJSON source URL.
ESRI_AUTHORIZATION_HEADER = "X-Esri-Authorization"

# Named for the same reason: the redactor recognizes it to know what follows
# is base64 of a username and password, with a cleartext form an origin can
# echo back (fix(#1746), core/url_redaction.py).
BASIC_SCHEME = "Basic "

# Header names a caller may not send a credential under. Compared
# case-insensitively, because HTTP field names are case-insensitive and a
# reviewer will try ``AUTHORIZATION``. Two groups, for two different reasons.
RESERVED_HEADER_NAMES: frozenset[str] = frozenset(
    {
        # GeoLens sets these itself on outbound requests; accepting one would
        # let a caller overwrite the request's own framing, and
        # ``authorization`` would collide with the bearer/basic branches.
        "authorization",
        "x-esri-authorization",
        "accept",
        # fix(#1770): `service_endpoints.py::credential_headers`
        # and `probe_bounds.py::bounded_probe_read` build headers as
        # `{name: value, "Accept-Encoding": "identity"}` — caller's pair
        # first, so a credential literally named `Accept-Encoding` was
        # silently overwritten by `"identity"`, reaching the origin as an
        # anonymous read. Refused at input instead.
        "accept-encoding",
        "content-type",
        "content-length",
        "host",
        "cookie",
        "set-cookie",
        "user-agent",
        "referer",
        # Frame/route/terminate the request rather than carry a credential.
        # `transfer-encoding: chunked` re-frames the body under the caller;
        # `proxy-authorization`/`proxy-connection` address a forward proxy,
        # not the service; the rest are RFC 9110 hop-by-hop names plus
        # `expect`, which can stall on a 100-continue that never comes.
        "transfer-encoding",
        "connection",
        "proxy-authorization",
        "proxy-connection",
        "keep-alive",
        "te",
        "trailer",
        "upgrade",
        "expect",
    }
)

# HTTP/2 and HTTP/3 pseudo-headers are protocol framing rather than fields, and
# the set is open-ended (:authority, :method, :path, :scheme, :status), so this
# is a prefix rule rather than another list of names. The charset above already
# refuses a colon; this exists so the caller is told which rule they hit.
PSEUDO_HEADER_PREFIX = ":"

# Every message below describes the policy and never the input, on the same
# reasoning as HEADER_TOKEN_POLICY: these reach a 422 body, a log line and a
# job row. None of them may contain a brace, so none can grow an interpolation
# later without failing the pin in tests/test_service_refresh_1220.py.
CREDENTIAL_INPUT_POLICY = (
    "A username, password or header value must not be empty, and may use "
    "only printable ASCII characters with no spaces and no line breaks. "
    "Accented letters and other characters outside ASCII cannot be written "
    "into the credential header this service needs."
)

BASIC_USERNAME_POLICY = (
    "A username used with a password must not contain a colon, because the "
    "colon is what separates the username from the password in the encoded "
    "credential."
)

HEADER_NAME_POLICY = (
    "A header name must not be empty, and may use only letters, digits and "
    "the characters ! # $ % & ' * + - . ^ _ ` | ~ . Spaces, colons and "
    "anything outside that set are not valid in an HTTP header name."
)

RESERVED_HEADER_NAME_POLICY = (
    "A credential cannot be sent under that header name: GeoLens either sets "
    "it on every request of its own, or it controls how the request is framed "
    "and routed rather than what the request carries. Use the header name the "
    "service documents for its API key."
)

CREDENTIAL_METHOD_POLICY = (
    "Unrecognized authentication method. The supported methods are none, "
    "bearer, basic and header."
)


class CredentialMethod(StrEnum):
    """How a caller says a service credential should be presented.

    Values are the wire literals, so a request schema validates against them
    directly. ``HEADER_KEY`` spells ``header`` (the taxonomy's user-facing
    name for an API key in a header); the member name distinguishes it since
    bearer and basic also produce a header.
    """

    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    HEADER_KEY = "header"


@dataclass(frozen=True, slots=True)
class ServiceCredential:
    """What a caller supplied for one remote service, before validation.

    Carries ``service_format`` because that, not the method, decides whether
    a credential may become a header at all — see ``build_credential_header``.

    A frozen dataclass rather than a pydantic model so both layers can hold
    one: ``core/`` may not import ``app.modules.*``, neither may
    ``processing/``, but both may import here.
    """

    method: CredentialMethod | str = CredentialMethod.NONE
    service_format: str | None = None
    token: str | None = None
    username: str | None = None
    password: str | None = None
    header_name: str | None = None
    header_value: str | None = None


def credential_input_rejection_reason(value: str | None) -> str | None:
    """Why *value* is unusable as a username, password or header value.

    Returns a description of the POLICY, never a description of the value.

    ``None`` is a rejection here, unlike in ``header_token_rejection_reason``
    where it means that no token was supplied and none is required. This
    function only ever judges a field the chosen method requires, so a missing
    one is a rejection rather than an absence.
    """
    if not value:
        return CREDENTIAL_INPUT_POLICY
    if any(character not in CREDENTIAL_INPUT_CHARSET for character in value):
        return CREDENTIAL_INPUT_POLICY
    return None


def header_name_rejection_reason(name: str | None) -> str | None:
    """Why *name* is unusable as the header a credential is sent under."""
    if not name:
        return HEADER_NAME_POLICY
    # Before the charset rule, which would also refuse a pseudo-header but
    # would tell the caller the colon was a typo rather than the point.
    if name.startswith(PSEUDO_HEADER_PREFIX):
        return RESERVED_HEADER_NAME_POLICY
    if any(character not in HEADER_NAME_CHARSET for character in name):
        return HEADER_NAME_POLICY
    if name.lower() in RESERVED_HEADER_NAMES:
        return RESERVED_HEADER_NAME_POLICY
    return None


# fix(#1770): the pattern-based redactors (`redact_exception_text`,
# `logging_config._scrub_text`) only catch a known query-param NAME or
# userinfo — a reflected credential in the URL PATH or an unlisted query key
# slipped through. This registry closes the class instead of each instance:
# the one producer (`build_credential_header` below) registers the exact
# line it composes HERE, so every reader is found by EXACT VALUE.
#
# A `ContextVar`, not a module-level set: scoped to one request/job, not the
# process — a set that outlived one request would grow unbounded and let
# request B's log line get scrubbed of request A's finished secret
# (over-redaction, not a leak, but still needs resetting). Reset at the same
# two boundaries `app.api.middleware.logging` and
# `tasks_common._bind_task_log_context` already reset structlog's contextvars.
_REGISTERED_CREDENTIAL_SECRETS: ContextVar[frozenset[str]] = ContextVar(
    "registered_credential_secrets", default=frozenset()
)


def register_credential_secret(secret: str | None) -> None:
    """Register *secret* for exact-scrub redaction for the rest of this
    request/job's context.

    A no-op on ``None``/empty, so a caller that has nothing to register (no
    credential at all) need not guard the call itself.
    """
    if not secret:
        return
    _REGISTERED_CREDENTIAL_SECRETS.set(_REGISTERED_CREDENTIAL_SECRETS.get() | {secret})


def registered_credential_secrets() -> frozenset[str]:
    """Every secret registered so far in this request/job's context."""
    return _REGISTERED_CREDENTIAL_SECRETS.get()


def reset_registered_credential_secrets() -> None:
    """Clear the registry. Call once at the start of each request/job scope,
    the same moment structlog's own contextvars are cleared, so a re-used
    worker or a subsequent request cannot inherit a prior one's secrets."""
    _REGISTERED_CREDENTIAL_SECRETS.set(frozenset())


def _composes_a_header(
    service_format: str | None, method: CredentialMethod | str
) -> bool:
    """Whether ``build_credential_header`` should compose anything at all.

    Three refusals kept out of the builder so its body stays one branch per
    method: a format whose credential isn't a header, the ``none`` method,
    and — feat(C2) — ArcGIS asked for a method it has no spelling for (basic
    and header-key have no ArcGIS form; ``service_carries_method`` refuses
    them at every door, this is the second line of defense).
    """
    if not sends_credential_as_header(service_format):
        return False
    if method == CredentialMethod.NONE:
        return False
    return not (
        service_format == ARCGIS_SERVICE_FORMAT and method != CredentialMethod.BEARER
    )


def bearer_token_rejection_reason(auth: ServiceCredential) -> str | None:
    """Why *auth*'s bearer token cannot become an Authorization value.

    feat(C2): two charsets, chosen by service format. A WFS/OAPIF token
    becomes a line in a 0600 file libcurl parses, so it's held to
    ``HEADER_TOKEN_CHARSET`` (base64url, CR/LF banned as smuggling). An
    ArcGIS token never reaches that file — percent-encoded into the URL
    instead — and legitimately holds ``+``/``/``, so it's judged as a header
    VALUE (printable ASCII, no whitespace) instead: CR/LF still banned, only
    the collateral damage differs.

    feat(#1764): the branch asks ``requires_header_token_policy`` rather than
    naming ArcGIS, so STAC takes the wider charset too — its credential is
    httpx-only, and httpx refuses a CR/LF header value itself.

    fix(#1764): public, because the DOOR has to reach the same verdict this
    builder will. Judging the door's bearer token by the GDAL charset alone
    refused a STAC key holding ``+`` or ``/`` that the builder accepts.
    """
    if not requires_header_token_policy(auth.service_format):
        # Rejects ``None`` on its own, unlike its header-token sibling, which
        # reads ``None`` as "no token supplied and none required".
        return credential_input_rejection_reason(auth.token)
    return header_token_rejection_reason(auth.token)


def build_credential_header(
    auth: ServiceCredential | None,
) -> tuple[str, str] | None:
    """The one producer of a credential header, as a name and value pair.

    Returns ``None`` when no header should be sent: no credential, or a
    format whose credential doesn't travel as a header. Expressed as the
    allowlist ``HEADER_TRANSPORT_SERVICE_FORMATS`` rather than a denylist, so
    an unrecognised format degrades to no header (a loud 401) rather than a
    smuggled one.

    feat(C2): ArcGIS is in that allowlist for its bearer token only — what's
    composed here is for GeoLens's own httpx requests; the GDAL path still
    percent-encodes the token into the URL and never reaches this function.

    Raises ``ValueError`` when the chosen method's inputs are unusable; the
    message is the policy, never the value, since it becomes a 422 body.

    Returns a pair, not a finished string, because two transports consume it
    differently: the GDAL header file wants a line
    (``credential_header_line``), the probe adapters want a dict key.

    fix(#1770): as the single producer, this is also the one
    place ``register_credential_secret`` is called — every branch that
    returns a pair registers it, so the exact-value redactors catch it
    wherever it's later reflected. ``test_credential_producer_structural.py``
    pins one registration call per returning branch.
    """
    if auth is None:
        return None

    method = auth.method
    if not _composes_a_header(auth.service_format, method):
        return None

    if method == CredentialMethod.BEARER:
        reason = bearer_token_rejection_reason(auth)
        if auth.token is None or reason is not None:
            raise ValueError(reason or HEADER_TOKEN_POLICY)
        if auth.service_format == ARCGIS_SERVICE_FORMAT:
            esri_pair = (ESRI_AUTHORIZATION_HEADER, f"{BEARER_SCHEME}{auth.token}")
            register_credential_secret(credential_header_line(esri_pair))
            return esri_pair
        pair = ("Authorization", f"{BEARER_SCHEME}{auth.token}")
        register_credential_secret(credential_header_line(pair))
        return pair

    if method == CredentialMethod.BASIC:
        username = auth.username
        password = auth.password
        if username is None or password is None:
            raise ValueError(CREDENTIAL_INPUT_POLICY)
        for supplied in (username, password):
            reason = credential_input_rejection_reason(supplied)
            if reason is not None:
                raise ValueError(reason)
        # RFC 7617: a user-id containing a colon is invalid, and accepting one
        # would move the split point rather than fail, so the origin would
        # authenticate a different user than the one that was typed.
        if ":" in username:
            raise ValueError(BASIC_USERNAME_POLICY)
        encoded = base64.b64encode(f"{username}:{password}".encode("ascii"))
        pair = ("Authorization", f"{BASIC_SCHEME}{encoded.decode('ascii')}")
        register_credential_secret(credential_header_line(pair))
        return pair

    if method == CredentialMethod.HEADER_KEY:
        name = auth.header_name
        value = auth.header_value
        reason = header_name_rejection_reason(name)
        if name is None or reason is not None:
            raise ValueError(reason or HEADER_NAME_POLICY)
        reason = credential_input_rejection_reason(value)
        if value is None or reason is not None:
            raise ValueError(reason or CREDENTIAL_INPUT_POLICY)
        pair = (name, value)
        register_credential_secret(credential_header_line(pair))
        return pair

    raise ValueError(CREDENTIAL_METHOD_POLICY)


def credential_header_line(pair: tuple[str, str]) -> str:
    """One header line, with no trailing newline.

    The pair comes from ``build_credential_header`` and is not re-judged here:
    a second validator standing beside the first is how the two disagreeing
    policies this module exists to merge came about in the first place. The
    writers add their own newline, so this returns exactly one line.
    """
    name, value = pair
    return f"{name}{HEADER_LINE_SEPARATOR}{value}"


def credential_from_header_line(
    line: str | None, *, service_format: str | None = None
) -> ServiceCredential | None:
    """The credential a D9 wire line describes, or None if it describes none.

    feat(#1764): the inverse of ``build_credential_header`` +
    :func:`credential_header_line`, for the one hop that cannot compose at
    the write site. A WFS/OAPIF worker writes the line straight to the GDAL
    header file; a STAC worker issues httpx requests of its own, and every
    one of those has to compose through the single producer like any other
    write site. Recovering the credential here is what lets it.

    Round-trips exactly: recomposing the result yields the same line, which
    ``test_stac_service_auth_1764`` pins. Basic is base64-decoded back to the
    username and password the builder encoded, and the builder already
    refused a colon in the username, so the split point is unambiguous.

    Returns None for anything this cannot round-trip — no separator, an empty
    name or value, an unrecognized ``Authorization`` scheme, or a Basic blob
    that is not ASCII base64 of ``user:password``. None means "no credential",
    which sends an anonymous request rather than a mis-composed one.
    """
    if not line:
        return None
    name, separator, value = line.partition(HEADER_LINE_SEPARATOR)
    if not separator or not name or not value:
        return None
    if name.lower() != "authorization":
        return ServiceCredential(
            method=CredentialMethod.HEADER_KEY,
            service_format=service_format,
            header_name=name,
            header_value=value,
        )
    if value.startswith(BEARER_SCHEME):
        return ServiceCredential(
            method=CredentialMethod.BEARER,
            service_format=service_format,
            token=value[len(BEARER_SCHEME) :],
        )
    if not value.startswith(BASIC_SCHEME):
        return None
    try:
        decoded = base64.b64decode(
            value[len(BASIC_SCHEME) :].encode("ascii"), validate=True
        ).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    username, colon, password = decoded.partition(":")
    if not colon:
        return None
    return ServiceCredential(
        method=CredentialMethod.BASIC,
        service_format=service_format,
        username=username,
        password=password,
    )
