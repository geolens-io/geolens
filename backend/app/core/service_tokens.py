"""One definition of what a service credential may look like.

fix(#1277 review round 6). Two places judged the same token and disagreed. The
API door accepted anything printable and whitespace-free, while the worker's
``_sanitize_authorization_token`` pinned header-auth tokens to the base64url
charset with an 8-character floor — so a WFS token containing ``+`` or ``/``
got a 202, burned its single-use credential, and failed deterministically in
the background. Same shape as the renewal-versus-sweep disagreement one round
earlier: neither policy was wrong, they were just two.

The stricter policy exists for a real reason and is not negotiable down: the
token becomes an ``Authorization`` header line that reaches libcurl through
GDAL, so a character outside this set is a header-smuggling primitive (SEC-FU-04).
This module is therefore the policy, and both sides consume it — the door so
the caller learns immediately, the worker so the trust boundary still enforces
it at the point of use. Removing the worker's check would leave the guarantee
resting on a validator two processes away.

Lives in ``core/`` because the two consumers are in different layers:
``modules/catalog`` for the request schema and ``processing/ingest`` for the
GDAL invocation. Neither may import the other, and both may import here.
"""

from __future__ import annotations

import base64
import string
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum

# The services whose credential becomes a line in the 0600 GDAL header file.
# ArcGIS is deliberately absent, and stays absent: on the GDAL/ogr2ogr path its
# token is still a query parameter, urlencoded into the ESRIJSON source URL, so
# it never becomes a header line there and never carries the smuggling risk
# this charset exists to prevent. Constraining it to base64url would reject
# legitimate ArcGIS tokens for a danger that path does not have.
#
# This set answers three questions at once, and lane C2 changed none of them:
# it names the formats whose credential (a) is judged by
# ``HEADER_TOKEN_CHARSET``, (b) is written to ``GDAL_HTTP_HEADER_FILE``, and
# (c) is checked by ``assert_endpoints_stay_on_origin`` because GDAL follows
# the service's own description with the header attached. All three still
# exclude ArcGIS.
HEADER_AUTH_SERVICE_FORMATS: frozenset[str] = frozenset({"wfs", "ogcapi_features"})

# feat(C2). ArcGIS's own service format, spelled here rather than imported from
# ``modules/catalog/sources/adapters/arcgis.py`` because ``core/`` may not
# import ``app.modules.*``; the adapter re-exports this name, so its importers
# are unchanged.
ARCGIS_SERVICE_FORMAT = "arcgis_featureserver"

# feat(C2): the formats whose credential travels as an HTTP header on
# GeoLens's OWN httpx requests, which is a wider set than the one above.
# ArcGIS Server has accepted ``Authorization: Bearer <token>`` since 10.5.1 and
# hosted ArcGIS Online always has; measured live on 2026-09-04 with a
# referer-bound token against services6.arcgis.com, where the header form and
# the ``?token=`` form return the same count and no ``Referer`` is needed.
# Sending it as a header keeps the token out of the request URL, and so out of
# httpx's ``HTTP Request: GET ...`` INFO log line, out of proxy and
# load-balancer access logs, and out of the exception text an origin quotes
# back.
#
# A separate set rather than a widened ``HEADER_AUTH_SERVICE_FORMATS`` because
# all three of that set's questions are still no for ArcGIS: the base64url
# charset would refuse ArcGIS tokens holding ``+`` or ``/``, nothing writes an
# ArcGIS credential to the GDAL header file, and the ArcGIS adapter composes
# every URL it reads from the base URL rather than following an endpoint the
# service describes, so there is no foreign-operation-endpoint class for
# ``assert_endpoints_stay_on_origin`` to bound.
HEADER_TRANSPORT_SERVICE_FORMATS: frozenset[str] = HEADER_AUTH_SERVICE_FORMATS | {
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


def sends_credential_as_header(source_format: str | None) -> bool:
    """Whether *source_format*'s credential travels as an HTTP header.

    feat(C2). The gate ``build_credential_header`` reads. Wider than
    :func:`requires_header_token_policy` by exactly ArcGIS, whose token became
    an ``Authorization: Bearer`` header on the httpx path in lane C2 while
    staying a query parameter on the GDAL path.
    """
    return source_format in HEADER_TRANSPORT_SERVICE_FORMATS


# ---------------------------------------------------------------------------
# fix(#1746): username-and-password and named API-key credentials for the two
# header-auth service formats.
#
# A bearer token is one shape of service credential; a username and password
# and a named API key are two more, and all three end up in the same two
# places: one ASCII line in a 0600 GDAL header file, and one key in a probe
# adapter's header dict. The rules below judge the INPUTS a caller typed, and
# ``build_credential_header`` composes the header afterwards.
#
# That order is the whole point of the split. A composed Basic line contains a
# space and a colon, so ``HEADER_TOKEN_CHARSET`` would reject the very line it
# exists to protect, at the door or, worse, in the worker after the single-use
# credential was already spent. So the charset above is untouched and keeps
# judging exactly one thing, a bare bearer token, and the encoded output of a
# validated username and password is safe by construction rather than by a
# second charset check: standard base64 emits ``+`` or ``/`` only when the byte
# at an offset congruent to 2 mod 3 is ``>``, ``?`` or ``~``, which is why the
# same password passes or fails depending on the length of the username.
# ---------------------------------------------------------------------------

# Printable ASCII with no whitespace, which is 0x21 through 0x7E. Non-ASCII is
# rejected deliberately rather than by omission: both header-file writers
# encode the line with ``.encode("ascii")``, so an accented letter in an API
# key would raise UnicodeEncodeError inside the worker, after the single-use
# credential has been claimed. RFC 7617 makes UTF-8 the default charset for
# basic authentication and this is narrower than that on purpose; the failure
# it prevents is unrecoverable without re-entering the credential.
CREDENTIAL_INPUT_CHARSET: frozenset[str] = frozenset(
    character for character in string.printable if not character.isspace()
)

# RFC 7230 tchar, which is what an HTTP field name may contain. A colon and a
# space are both absent from it, so a name carrying either cannot smuggle a
# second header line or a value into the file.
HEADER_NAME_CHARSET: frozenset[str] = frozenset(
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~"
)

# fix(#1746): what a composed line's VALUE may contain, which is the input
# charset plus one character. The space is there because a composed value
# carries an authentication scheme (``Bearer <token>``, ``Basic <blob>``),
# and it is the only difference: a value is still printable ASCII with no
# line break, so it cannot smuggle a second header.
HEADER_LINE_VALUE_CHARSET: frozenset[str] = CREDENTIAL_INPUT_CHARSET | {" "}

# The one separator ``credential_header_line`` joins with and the worker
# splits on. Named so the joiner and the parser cannot drift into two
# spellings of the same rule.
HEADER_LINE_SEPARATOR = ": "

# The scheme prefix the bearer branch composes, and the prefix the worker
# recognizes to decide that the stricter base64url charset applies.
BEARER_SCHEME = "Bearer "

# The basic branch's, named for the same reason: the redactor recognizes it to
# decide that what follows is base64 of a username and password, and so has a
# cleartext form an origin can echo back
# (fix(#1746 B2b review r11), core/url_redaction.py).
BASIC_SCHEME = "Basic "

# Header names a caller may not send a credential under. Compared
# case-insensitively, because HTTP field names are case-insensitive and a
# reviewer will try ``AUTHORIZATION``. Two groups, for two different reasons.
RESERVED_HEADER_NAMES: frozenset[str] = frozenset(
    {
        # GeoLens sets these itself on outbound requests. Accepting one would
        # let a caller overwrite what the request says about itself rather
        # than add a credential to it, and ``authorization`` in particular
        # would collide with the header the bearer and basic branches compose.
        "authorization",
        "x-esri-authorization",
        "accept",
        # fix(#1770 round 49 P2): both `service_endpoints.py::credential_
        # headers` and `probe_bounds.py::bounded_probe_read` build their
        # request headers as `{name: value, "Accept-Encoding": "identity"}`
        # -- the caller's pair FIRST, GeoLens's own encoding pin SECOND, so a
        # credential named exactly `Accept-Encoding` (any case; the dict
        # keys collide because both call sites spell the literal the same
        # way) is silently overwritten by `"identity"` before the request
        # goes out. The credentialed read then reaches the origin with no
        # real credential value at all -- an anonymous read on exactly the
        # path r14's fail-closed design exists to keep from happening, and
        # `next(iter(headers))` still names the right header for `make_safe_
        # client`'s cross-origin strip, which is what made this reachable
        # without a single obviously-wrong log line anywhere in the request
        # path. Refused at input instead of ever reaching those dicts.
        "accept-encoding",
        "content-type",
        "content-length",
        "host",
        "cookie",
        "set-cookie",
        "user-agent",
        "referer",
        # These change how the request is framed, routed or terminated rather
        # than what it carries, so none of them is ever the header a service
        # key travels in. ``transfer-encoding: chunked`` is honoured both by
        # httpx and by the libcurl header file GDAL reads, so it re-frames the
        # request body from under the caller. ``proxy-authorization`` and
        # ``proxy-connection`` are read by a configured forward proxy, which
        # is a different party than the service being addressed. The rest are
        # the RFC 9110 hop-by-hop names, plus ``expect``, which can stall a
        # request waiting for a 100-continue that never comes.
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

    The values are the wire literals, so a request schema can validate against
    them directly and pass the string straight through. ``HEADER_KEY`` spells
    its value ``header`` because that is the name the taxonomy gives the user,
    an API key in a header; the member name says which of the header branches
    it is, since bearer and basic also produce one.
    """

    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    HEADER_KEY = "header"


@dataclass(frozen=True, slots=True)
class ServiceCredential:
    """What a caller supplied for one remote service, before validation.

    Carries ``service_format`` because that, and not the method, is what
    decides whether a credential may become a header at all. An ArcGIS token
    is percent-encoded into a URL query, so a header composed for it would put
    an Authorization line inside a query string; see
    ``build_credential_header``.

    A frozen dataclass rather than a pydantic model so both layers can hold
    one: ``core/`` may not import ``app.modules.*`` and neither may
    ``processing/``, but both may import here. A request schema converts into
    this at the door, and a caller that already holds the values, such as a
    refresh service invoked in process rather than over HTTP, constructs one
    directly.
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


# fix(#1770 round 43 P2). `redact_exception_text`/the structlog `_scrub_text`
# processor (`core/logging_config.py`) only ever redacted by PATTERN: a known
# credential query-parameter NAME, or userinfo. A same-origin redirect that
# reflects the credential into the URL PATH, or into a query key not on that
# list (`?echo=<value>`, say), carried the secret straight through both --
# each new reflection site was its own review round rather than a closed
# class. This registry is what closes the class instead of the instance: the
# one producer of a credential header (`build_credential_header` below)
# registers the exact line it composes, HERE, so every reader of this secret
# is registered at the one place it is ever produced -- no caller of the
# builder has to remember to thread the raw value through to a log call for
# it to be found by EXACT VALUE rather than by guessing its shape.
#
# A `ContextVar` rather than a module-level set: this has to be scoped to one
# request or one job, not to the process. A worker or an API instance handles
# many callers' credentials over its lifetime, and a set that outlived one
# request would grow without bound and would let request B's log line be
# scrubbed of request A's already-finished secret -- over-redaction, not a
# leak, but still a resource that has to be reset somewhere.
# `app.api.middleware.logging` and
# `app.processing.ingest.tasks_common._bind_task_log_context` are that
# somewhere: both already reset the request/job's structlog contextvars at
# the same two boundaries this reuses.
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

    Three refusals, kept out of the builder so its own body stays one branch
    per method. A format whose credential does not travel as a header, the
    ``none`` method, and -- feat(C2) -- ArcGIS asked for a method it has no
    spelling for. Basic and a named API key have no ArcGIS form at all
    (``service_carries_method`` refuses them at every door), so answering
    False keeps the builder from composing a header the service could never
    read rather than trusting that the doors refused first.
    """
    if not sends_credential_as_header(service_format):
        return False
    if method == CredentialMethod.NONE:
        return False
    return not (
        service_format == ARCGIS_SERVICE_FORMAT and method != CredentialMethod.BEARER
    )


def _bearer_token_rejection(auth: ServiceCredential) -> str | None:
    """Why *auth*'s bearer token cannot become an Authorization value.

    feat(C2): two charsets, one per transport, chosen by the service format.

    A WFS or OGC API Features token becomes a line in a 0600 file libcurl
    parses, where a stray CR or LF is a header-smuggling primitive, so it is
    held to ``HEADER_TOKEN_CHARSET`` (base64url plus a length floor). An
    ArcGIS token never reaches that file -- the GDAL path percent-encodes it
    into the ESRIJSON source URL instead -- and legitimately holds ``+`` or
    ``/``, which base64url refuses, so it is judged as a header VALUE:
    printable ASCII with no whitespace. That still bans every whitespace
    character, CR and LF included, so the smuggling class is closed on both
    paths; only the collateral damage differs.

    Returns the POLICY and never the token, on the same reasoning as every
    other message in this module.
    """
    if auth.service_format == ARCGIS_SERVICE_FORMAT:
        # Rejects ``None`` on its own, unlike its header-token sibling, which
        # reads ``None`` as "no token supplied and none required".
        return credential_input_rejection_reason(auth.token)
    return header_token_rejection_reason(auth.token)


def build_credential_header(
    auth: ServiceCredential | None,
) -> tuple[str, str] | None:
    """The one producer of a credential header, as a name and value pair.

    Returns ``None`` when no header should be sent at all: no credential, or a
    service format whose credential does not travel as a header. That is
    expressed as an allowlist, ``HEADER_TRANSPORT_SERVICE_FORMATS``, rather
    than as a denylist, so a format nobody thought about degrades to no header
    rather than to a smuggled one. The cost is that a caller which does not set
    ``service_format`` gets no header, and the resulting failure is a 401 from
    the origin, which is loud, rather than an Authorization line inside a URL
    query, which is not.

    feat(C2): ArcGIS is in that allowlist now, for its bearer token only. What
    is composed here is what GeoLens's own httpx requests send; the GDAL path
    still percent-encodes the same token into the ESRIJSON source URL and never
    reaches this function, which is why ``HEADER_AUTH_SERVICE_FORMATS`` (the
    header-FILE set, and the base64url charset that goes with it) is unchanged.

    Raises ``ValueError`` when the inputs for the chosen method are unusable.
    The message is the policy and never the value, because it becomes a 422
    body as well as a log line.

    A pair rather than a finished string because two transports consume it: the
    GDAL header file wants a line, from ``credential_header_line``, and the
    probe adapters want a dict key. Returning only a string would put a second
    parser in each adapter, which is what the single-producer rule exists to
    prevent.

    fix(#1770 round 43 P2): being the single producer is also why this is the
    one place ``register_credential_secret`` needs calling at all -- every
    header line this function composes is registered, HERE, on every branch
    that returns one, so ``redact_exception_text`` and the structlog
    ``_scrub_text`` processor can exact-scrub it out of anything that later
    echoes it back, regardless of WHERE it gets reflected (a query parameter
    name neither of them already knows to look for, or the URL path, not only
    the ones a pattern-based redactor recognises by shape).
    ``test_credential_producer_structural.py``'s
    ``TestBuildCredentialHeaderRegistersEverythingItProduces`` pins the shape
    structurally: one registration call per branch that returns a pair.
    """
    if auth is None:
        return None

    method = auth.method
    if not _composes_a_header(auth.service_format, method):
        return None

    if method == CredentialMethod.BEARER:
        reason = _bearer_token_rejection(auth)
        if auth.token is None or reason is not None:
            raise ValueError(reason or HEADER_TOKEN_POLICY)
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
