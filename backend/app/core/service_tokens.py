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
from dataclasses import dataclass
from enum import StrEnum

# The services whose credential travels as an Authorization header. ArcGIS is
# deliberately absent: its token is a query parameter, urlencoded into the
# ESRIJSON source URL, so it never becomes a header line and never carries the
# smuggling risk this charset exists to prevent. Constraining it to base64url
# would reject legitimate ArcGIS tokens for a danger that path does not have.
HEADER_AUTH_SERVICE_FORMATS: frozenset[str] = frozenset({"wfs", "ogcapi_features"})

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
    """Whether *source_format*'s credential travels as an Authorization header."""
    return source_format in HEADER_AUTH_SERVICE_FORMATS


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


def build_credential_header(
    auth: ServiceCredential | None,
) -> tuple[str, str] | None:
    """The one producer of a credential header, as a name and value pair.

    Returns ``None`` when no header should be sent at all: no credential, or a
    service format whose credential does not travel as a header. That second
    case is the ArcGIS invariant, and it is expressed as an allowlist of the
    formats in ``HEADER_AUTH_SERVICE_FORMATS`` rather than as a denylist of
    ArcGIS, so a format nobody thought about degrades to no header rather than
    to a smuggled one. The cost is that a caller which does not set
    ``service_format`` gets no header, and the resulting failure is a 401 from
    the origin, which is loud, rather than an Authorization line inside a URL
    query, which is not.

    Raises ``ValueError`` when the inputs for the chosen method are unusable.
    The message is the policy and never the value, because it becomes a 422
    body as well as a log line.

    A pair rather than a finished string because two transports consume it: the
    GDAL header file wants a line, from ``credential_header_line``, and the
    probe adapters want a dict key. Returning only a string would put a second
    parser in each adapter, which is what the single-producer rule exists to
    prevent.
    """
    if auth is None:
        return None
    if not requires_header_token_policy(auth.service_format):
        return None

    method = auth.method
    if method == CredentialMethod.NONE:
        return None

    if method == CredentialMethod.BEARER:
        reason = header_token_rejection_reason(auth.token)
        if auth.token is None or reason is not None:
            raise ValueError(reason or HEADER_TOKEN_POLICY)
        return ("Authorization", f"Bearer {auth.token}")

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
        return ("Authorization", f"Basic {encoded.decode('ascii')}")

    if method == CredentialMethod.HEADER_KEY:
        name = auth.header_name
        value = auth.header_value
        reason = header_name_rejection_reason(name)
        if name is None or reason is not None:
            raise ValueError(reason or HEADER_NAME_POLICY)
        reason = credential_input_rejection_reason(value)
        if value is None or reason is not None:
            raise ValueError(reason or CREDENTIAL_INPUT_POLICY)
        return (name, value)

    raise ValueError(CREDENTIAL_METHOD_POLICY)


def credential_header_line(pair: tuple[str, str]) -> str:
    """One header line, with no trailing newline.

    The pair comes from ``build_credential_header`` and is not re-judged here:
    a second validator standing beside the first is how the two disagreeing
    policies this module exists to merge came about in the first place. The
    writers add their own newline, so this returns exactly one line.
    """
    name, value = pair
    return f"{name}: {value}"
