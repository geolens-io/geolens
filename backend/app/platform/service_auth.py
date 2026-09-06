"""Which service credential methods this build can carry, and on what.

feat(#1746). ``core/service_tokens.py`` says what a credential may LOOK like
and how one header is composed from it. This module answers the narrower
question every door has to answer before it writes anything: of the methods a
caller can describe in a request, which ones can the transport underneath this
particular service actually carry, and are the values the caller typed usable.

The answer is per service format rather than per build. WFS and OGC API
Features send their credential as a header, so all three methods reach them.
An ArcGIS token is percent-encoded into a URL query, so only a bearer token
reaches that one, and a username and password or a named API key is refused
with a 422 rather than dropped: accepting the request and fetching
anonymously fails later at the origin with a 401 and reads like a credential
problem rather than a missing feature.

Lives in ``platform/`` because the callers are in layers that may not import
each other: ``modules/catalog`` for the probe, preview, re-upload and refresh
doors, ``processing/ingest`` for the queue-time check, and ``platform/refresh``
for the dispatch decision. All of them may import here.

Two entry points, and the split between them is plan D9's.
:func:`credential_or_422` judges the INPUTS and hands back the credential the
caller may now send, for a transport that composes its own header at the site
that writes it: the two probe adapters and the two GDAL header-file writers.
The single-producer rule (``tests/test_credential_producer_structural.py``) is
what keeps that composition at the write site rather than letting a finished
line travel to it. :func:`wire_credential` is for the one hop that cannot
compose at the write site, the queue: it returns the finished ASCII string
that crosses to the worker under the kwarg name ``token``, so the queued-row
purge, the terminal-row sweep and the ``token`` log scrubber keep covering a
basic or header-key credential without any of the three being edited.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.coded_errors import CodedValueError
from app.core.service_tokens import (
    BASIC_USERNAME_POLICY,
    CREDENTIAL_METHOD_POLICY,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
    credential_header_line,
    credential_input_rejection_reason,
    header_name_rejection_reason,
    header_token_rejection_reason,
    requires_header_token_policy,
)

UNSUPPORTED_AUTH_METHOD_CODE = "unsupported_auth_method"

# The code every door already returns for a credential it will not send, and
# the one the client already maps. A refused input is the same kind of answer,
# so it reuses that code rather than minting a second one.
INVALID_SERVICE_TOKEN_CODE = "invalid_service_token"

# Describes the policy and never the input, on the same reasoning as
# HEADER_TOKEN_POLICY: these reach a 422 body and a log line. No brace in any
# of them, so none can grow an interpolation later without failing the pin in
# tests/test_service_refresh_1220.py.
UNSUPPORTED_AUTH_METHOD_POLICY = (
    "This service carries its credential in the request URL, which has room "
    "for a token and nothing else. Use a bearer token for it."
)

# fix(#1760 codex r1): the same rule the request schema applies, restated for
# the callers that never pass through it. Reuses `invalid_service_token`, which
# every door already returns and the client already maps, rather than minting a
# code for a case that means what that one means.
BLANK_BEARER_TOKEN_CODE = INVALID_SERVICE_TOKEN_CODE

BLANK_BEARER_TOKEN_POLICY = (
    "A bearer credential needs a token. Leave the credential out entirely for "
    "a service that does not need one."
)


def _unsupported_method() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": UNSUPPORTED_AUTH_METHOD_CODE,
            "message": UNSUPPORTED_AUTH_METHOD_POLICY,
        },
    )


def _refused(policy: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": INVALID_SERVICE_TOKEN_CODE, "message": policy},
    )


def bearer_token_for_credential(credential: ServiceCredential | None) -> str | None:
    """The bearer token *credential* travels as, or None when there is none.

    Raises ``HTTPException`` 422 for every method that cannot be spelled as a
    bare token, so a caller that reaches a URL-query transport with this has
    already refused everything that transport cannot honour by the time it
    reads the return value. An unrecognized method takes the same branch as a
    known-but-unsendable one: the request described something this build will
    not send there, and the answer is the same either way.

    A bearer credential carrying no token is refused rather than returned as a
    falsy value. Every caller tests the return for truthiness, so returning
    ``""`` would send an anonymous request on behalf of someone who named a
    method. The request schema already refuses that shape, so this branch is
    unreachable over HTTP and exists for the in-process caller of plan D2,
    which builds a :class:`ServiceCredential` directly and never meets a
    pydantic model.
    """
    if credential is None:
        return None
    method = credential.method
    if method == CredentialMethod.NONE:
        return None
    if method == CredentialMethod.BEARER:
        token = credential.token
        if token is None or token.strip() == "":
            raise _refused(BLANK_BEARER_TOKEN_POLICY)
        return token
    raise _unsupported_method()


def credential_input_rejection(credential: ServiceCredential) -> str | None:
    """Why the values in *credential* cannot become a header, or None.

    The door's half of plan 3.5: judge what the caller TYPED, and let the
    composition happen afterwards. A composed basic line contains a space and
    a colon, so a validator applied to the line instead would reject the very
    thing it exists to protect, at the door or, worse, in the worker after the
    single-use credential has been spent.

    Every branch returns a policy constant and never the value, because this
    string becomes a 422 body, a log line and a job row.
    ``build_credential_header`` raises on the same inputs and is the actual
    enforcement; this exists so a caller learns before anything is composed,
    reserved or dispatched.
    """
    method = credential.method
    if method == CredentialMethod.BEARER:
        if not credential.token:
            return BLANK_BEARER_TOKEN_POLICY
        return header_token_rejection_reason(credential.token)
    if method == CredentialMethod.BASIC:
        for supplied in (credential.username, credential.password):
            reason = credential_input_rejection_reason(supplied)
            if reason is not None:
                return reason
        # RFC 7617: a colon in the user-id moves the split point rather than
        # failing, so the origin would authenticate a different user than the
        # one that was typed.
        if ":" in (credential.username or ""):
            return BASIC_USERNAME_POLICY
        return None
    if method == CredentialMethod.HEADER_KEY:
        return header_name_rejection_reason(
            credential.header_name
        ) or credential_input_rejection_reason(credential.header_value)
    return CREDENTIAL_METHOD_POLICY


def service_carries_method(
    service_format: str | None, method: CredentialMethod
) -> bool:
    """Whether a service of this KIND can present a credential of this METHOD.

    fix(#1746 B2b review r27): the one mapping, so the probe door and the
    probe itself cannot disagree about it. It had been expressed twice and
    differently: the door inferred the service kind from the URL text and
    refused there, while `detect_service_type` refused the same methods after
    detection. A WFS served from a path containing `FeatureServer` was
    therefore refused a credential it supports, before anything had asked the
    service what it is.

    Bearer travels either way: it fits a URL query and it fits a header line.
    Basic and a named API key exist only as a header, so they need a service
    kind whose credential travels as one. Anything else is a method this build
    does not know how to send anywhere.
    """
    if method in (CredentialMethod.NONE, CredentialMethod.BEARER):
        return True
    if method in (CredentialMethod.BASIC, CredentialMethod.HEADER_KEY):
        return requires_header_token_policy(service_format)
    return False


def credential_or_422(
    credential: ServiceCredential | None, *, service_format: str | None
) -> ServiceCredential | None:
    """The credential this door may now send, bound to *service_format*.

    Returns None when there is nothing to send at all. Raises 422
    ``unsupported_auth_method`` for a method the named service cannot carry,
    and 422 ``invalid_service_token`` carrying the policy for an input the
    credential rules refuse. The caller composes afterwards, at the site that
    writes the header, which is what keeps one producer in the tree.

    ``service_format`` is bound onto the returned credential rather than left
    to the caller to pass again, because it is what decides whether a header
    may be composed at all: ``build_credential_header`` reads it and answers
    None for anything outside ``HEADER_AUTH_SERVICE_FORMATS``, which is plan
    D9's ArcGIS invariant expressed as an allowlist.
    """
    if credential is None or credential.method == CredentialMethod.NONE:
        return None
    bound = replace(credential, service_format=service_format)
    if not requires_header_token_policy(service_format):
        # A URL-query transport, or a format nobody has taught this to carry.
        # Bearer is the only spelling that fits in a query parameter, and the
        # bare token keeps its wider vocabulary there because it never becomes
        # a header line.
        bearer_token_for_credential(bound)
        return bound
    reason = credential_input_rejection(bound)
    if reason is not None:
        raise _refused(reason)
    return bound


def wire_credential(
    credential: ServiceCredential | None, *, service_format: str | None = None
) -> str | None:
    """The one string that crosses to the worker under the kwarg ``token``.

    Plan D9. For the two header-auth formats that is a finished ASCII header
    line, composed here because the queue hop has no site at which to compose
    it later; for ArcGIS it is the bare token that gets percent-encoded into
    the query, exactly as before. Validation happens first either way, so a
    credential that cannot work never reserves a run or burns a single-use
    stash.

    ``service_format`` defaults to the one already on the credential, which is
    what an in-process caller of plan D2 sets when it constructs one directly.

    fix(#1840 audit round 1): the ArcGIS branch is selected by
    ``requires_header_token_policy`` and NOT by "the builder answered None".
    Lane C2 taught ``build_credential_header`` to compose an
    ``X-Esri-Authorization: Bearer`` header for ArcGIS -- for GeoLens's own httpx
    requests, which is a different transport from this one -- and that silently
    killed the branch below, so this handed the worker the string
    ``Authorization: Bearer <token>`` as ``token``. ``build_gdal_source`` then
    percent-encoded the whole line into ``&token=Authorization%3A+Bearer+...``
    and every authenticated ArcGIS ingest, refresh and reupload failed at the
    origin, after the single-use credential had already been spent. The
    question this function asks is whether the credential becomes a header
    LINE, which is what ``requires_header_token_policy`` answers and what
    ``HEADER_AUTH_SERVICE_FORMATS`` is the set for; asking the builder was a
    proxy for it that stopped being equivalent.
    """
    resolved = (
        service_format
        if service_format is not None
        else (credential.service_format if credential is not None else None)
    )
    bound = credential_or_422(credential, service_format=resolved)
    if bound is None:
        return None
    if not requires_header_token_policy(resolved):
        # A URL-query transport: ArcGIS, whose worker-side token is the bare
        # value `build_gdal_source` percent-encodes into the ESRIJSON source.
        return bearer_token_for_credential(bound)
    pair = build_credential_header(bound)
    if pair is None:
        return bearer_token_for_credential(bound)
    return credential_header_line(pair)


def url_query_token(credential: ServiceCredential | None) -> str | None:
    """The bare token a URL-query transport can carry, or None.

    Never raises, unlike :func:`bearer_token_for_credential`. By the time a
    door reads this, :func:`credential_or_422` has already refused every method
    the named service cannot carry, so a credential that is not a bearer one
    here is a header credential travelling by its own route rather than an
    error. The one caller that has no service type yet, the probe, reaches all
    three adapters with one credential and this is how the ArcGIS branch takes
    the only spelling that fits in a query parameter.
    """
    if credential is None or credential.method != CredentialMethod.BEARER:
        return None
    return credential.token


def custom_credential_header_name(
    credential: ServiceCredential | None,
) -> str | None:
    """The header name an httpx client must refuse to follow a redirect with.

    Plan section 5 rule A, httpx half. ``Authorization`` needs nothing: httpx
    drops it on a cross-origin redirect by itself. A name the SERVICE chose is
    forwarded verbatim, so ``make_safe_client`` has to be told about it, and
    it then fails the hop closed rather than handing the key to whatever
    origin the 302 names.
    """
    if credential is None or credential.method != CredentialMethod.HEADER_KEY:
        return None
    return credential.header_name


def bearer_credential(token: str | None) -> ServiceCredential | None:
    """A credential for a caller that still holds only the flat bearer token.

    The deprecated spelling has one meaning, and this is where it acquires it,
    so a caller that has not been converted to the structured object yet still
    reaches the same validation and the same composer.
    """
    if not token:
        return None
    return ServiceCredential(method=CredentialMethod.BEARER, token=token)


# ---------------------------------------------------------------------------
# The request-side spelling of the same thing.
#
# feat(#1746). Moved here from ``modules/catalog/sources/schemas.py`` in lane
# B2b, unchanged. It lives in ``platform/`` for the same reason the gate above
# does: the doors that accept one are in ``modules/catalog`` and in
# ``processing/ingest``, and ``processing/`` may not import
# ``app.modules.catalog.*`` at any scope. ``sources/schemas.py`` imports it
# back, so every existing import path and the OpenAPI component name are
# unchanged.
# ---------------------------------------------------------------------------


def _validate_safe_token(v: str | None) -> str | None:
    """Reject control characters / whitespace in auth tokens (SEC-021).

    Tokens flow into a GDAL_HTTP_HEADER_FILE (WFS/OAPIF bearer) and into service
    query URLs (ArcGIS). A CR/LF or other control character could smuggle
    additional outbound HTTP headers through the libcurl pipeline. Legitimate
    JWT / base64url / ArcGIS tokens never contain control characters or
    whitespace, so reject them at the API boundary (422).

    The refusal carries ``invalid_service_token``, the code a door-layer
    refusal returns and the clients map, so a caller reads the same message
    whichever layer judges the credential.
    """
    if v is None:
        return v
    if not v.isprintable():
        raise CodedValueError(
            INVALID_SERVICE_TOKEN_CODE,
            "token contains control characters (possible header injection)",
        )
    if any(c.isspace() for c in v):
        raise CodedValueError(INVALID_SERVICE_TOKEN_CODE, "token contains whitespace")
    return v


# ---------------------------------------------------------------------------
# feat(#1746): the structured `auth` object every service door accepts, and the
# deprecated flat `token` that means the same thing for a bearer credential.
#
# One model, imported by the re-upload and refresh request models as well, so
# the four doors cannot describe the same credential four ways. The pydantic
# layer judges SHAPE only: which fields belong to which method, and that a
# request does not say the same thing twice. What a username or a header value
# may CONTAIN is `core/service_tokens.py`'s rule, applied at the door once the
# method has been accepted, because those rules exist to protect a composed
# header line and no line is composed here.
# ---------------------------------------------------------------------------

SERVICE_AUTH_METHOD_DESCRIPTION = (
    "How the credential is presented to the remote service. Omit the whole "
    "auth object for a public service."
)

# Every message below describes the policy and never the input. A validator
# whose ValueError interpolated a value would defeat the 422 flattener in
# standards/ogc/errors.py, which drops pydantic's `input` and keeps the
# message.
SERVICE_AUTH_BEARER_POLICY = (
    "A bearer credential is described by the token field alone. Remove the "
    "username, password, header name and header value."
)

SERVICE_AUTH_BASIC_POLICY = (
    "A username-and-password credential is described by the username and "
    "password fields, and needs both. Remove the token, header name and "
    "header value."
)

SERVICE_AUTH_HEADER_POLICY = (
    "An API-key credential is described by the header name and header value "
    "fields, and needs both. Remove the token, username and password."
)

SERVICE_AUTH_CONFLICT_POLICY = (
    "Set either the auth object or the deprecated token field, not both. The "
    "token field means the same as an auth object with method bearer."
)

SERVICE_AUTH_FIELD_DESCRIPTION = (
    "Structured credential for a protected service. Mutually exclusive with "
    "the token field."
)

DEPRECATED_TOKEN_SUFFIX = " Deprecated: use the auth object with method bearer."

_SERVICE_AUTH_CREDENTIAL_FIELDS = (
    "token",
    "username",
    "password",
    "header_name",
    "header_value",
)

# What each method is described by, exactly. The comparison in the validator is
# equality rather than a subset test, so a body that also sets a field
# belonging to another method is refused instead of having that field silently
# discarded.
_SERVICE_AUTH_SHAPES: dict[str, tuple[frozenset[str], str]] = {
    "bearer": (frozenset({"token"}), SERVICE_AUTH_BEARER_POLICY),
    "basic": (frozenset({"username", "password"}), SERVICE_AUTH_BASIC_POLICY),
    "header": (
        frozenset({"header_name", "header_value"}),
        SERVICE_AUTH_HEADER_POLICY,
    ),
}


def _names_a_credential(value: str | None) -> bool:
    """Whether *value* is a credential the caller actually supplied.

    fix(#1760 codex r1): an empty or whitespace-only string is not one. It used
    to count as supplied, so ``{"method": "bearer", "token": ""}`` passed the
    shape check, and every downstream test is a truthiness test, so the door
    then contacted the origin with no credential at all. The caller had named a
    method, which makes an anonymous request the one outcome they did not ask
    for: a public service needs no ``auth`` object, and a protected one answers
    401 in a way that reads like a broken service rather than a blank field.

    Whitespace as well as empty, because none of these values may contain
    whitespace anywhere: a blank-looking one is a typo, never a credential.
    """
    return value is not None and value.strip() != ""


class ServiceAuthRequest(BaseModel):
    """How one request authenticates to the remote service it names."""

    method: Literal["bearer", "basic", "header"] = Field(
        description=SERVICE_AUTH_METHOD_DESCRIPTION
    )
    token: str | None = Field(
        default=None,
        max_length=1000,
        description="Bearer token or API key, for method bearer.",
    )
    _validate_token = field_validator("token")(_validate_safe_token)
    username: str | None = Field(
        default=None, max_length=255, description="Username, for method basic."
    )
    password: str | None = Field(
        default=None, max_length=1000, description="Password, for method basic."
    )
    header_name: str | None = Field(
        default=None,
        max_length=255,
        description="Name of the header the key is sent under, for method header.",
    )
    header_value: str | None = Field(
        default=None,
        max_length=1000,
        description="Value of the header the key is sent under, for method header.",
    )

    @model_validator(mode="after")
    def _fields_must_match_the_method(self) -> "ServiceAuthRequest":
        required, policy = _SERVICE_AUTH_SHAPES[self.method]
        supplied = {
            name
            for name in _SERVICE_AUTH_CREDENTIAL_FIELDS
            if _names_a_credential(getattr(self, name))
        }
        if supplied != required:
            raise ValueError(policy)
        return self

    def to_credential(self, service_format: str | None = None) -> ServiceCredential:
        """The layer-neutral credential this request describes."""
        return ServiceCredential(
            method=CredentialMethod(self.method),
            service_format=service_format,
            token=self.token,
            username=self.username,
            password=self.password,
            header_name=self.header_name,
            header_value=self.header_value,
        )


def reject_service_auth_conflict(model: Any) -> Any:
    """Refuse a body that describes its credential twice.

    Used as an ``@model_validator(mode="after")`` on every request model that
    carries both spellings. Honouring one and dropping the other would make
    which credential was actually sent depend on an ordering nobody wrote down.
    """
    if model.auth is not None and model.token is not None:
        raise ValueError(SERVICE_AUTH_CONFLICT_POLICY)
    return model


def service_credential_from_request(
    auth: ServiceAuthRequest | None,
    token: str | None,
    *,
    service_format: str | None = None,
) -> ServiceCredential | None:
    """The credential a request carries, from either spelling.

    ``None`` when the request named no credential at all, so a caller can tell
    a public service from a credentialed one without inspecting a method.
    """
    if auth is not None:
        return auth.to_credential(service_format)
    if token:
        return ServiceCredential(
            method=CredentialMethod.BEARER,
            service_format=service_format,
            token=token,
        )
    return None
