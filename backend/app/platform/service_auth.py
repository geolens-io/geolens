"""Which service credential methods this build can carry, and on what.

``core/service_tokens.py`` says what a credential may LOOK
like and how one header is composed from it. This module answers the
narrower question every door has to answer before it writes anything: of
the methods a caller can describe, which can the transport under this
particular service actually carry, and are the typed values usable.

The answer is per service format, not per build. WFS and OGC API Features
send their credential as a header, so all three methods reach them. An
ArcGIS token is percent-encoded into a URL query, so only a bearer token
reaches that one; a username/password or named API key is refused with a
422 rather than dropped — accepting the request and fetching anonymously
fails later at the origin with a 401 and reads like a credential problem
rather than a missing feature.

Lives in ``platform/`` because the callers are in layers that may not
import each other: ``modules/catalog`` for the probe/preview/re-upload/
refresh doors, ``processing/ingest`` for the queue-time check, and
``platform/refresh`` for the dispatch decision. All of them may import here.

Two entry points. :func:`credential_or_422` judges the
INPUTS and hands back the credential for a transport that composes its
own header at the write site (the two probe adapters, two GDAL
header-file writers) — the single-producer rule
(``tests/test_credential_producer_structural.py``) keeps composition
there rather than letting a finished line travel to it.
:func:`wire_credential` is for the one hop that can't compose at the
write site, the queue: it returns the finished ASCII string crossing to
the worker under kwarg ``token``, so the queued-row purge, terminal-row
sweep, and ``token`` log scrubber keep covering a basic or header-key
credential without any of the three being edited.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.coded_errors import CodedValueError
from app.core.config import canonical_service_host, settings
from app.core.service_tokens import (
    BASIC_USERNAME_POLICY,
    CREDENTIAL_METHOD_POLICY,
    CredentialMethod,
    ServiceCredential,
    build_credential_header,
    credential_header_line,
    carries_credential_as_header_line,
    credential_input_rejection_reason,
    header_name_rejection_reason,
    bearer_token_rejection_reason,
)

UNSUPPORTED_AUTH_METHOD_CODE = "unsupported_auth_method"

# The code every door already returns for a credential it won't send, which
# the client already maps. A refused input is the same kind of answer, so
# it reuses that code rather than minting a second one.
INVALID_SERVICE_TOKEN_CODE = "invalid_service_token"

# Names the policy, never the input, per HEADER_TOKEN_POLICY: these reach a
# 422 body and a log line. No brace in either, so neither can grow an
# interpolation later without failing the pin in test_service_refresh_1220.py.
UNSUPPORTED_AUTH_METHOD_POLICY = (
    "This service carries its credential in the request URL, which has room "
    "for a token and nothing else. Use a bearer token for it."
)

# The request schema's rule, restated for callers that never pass through
# it, under the same `invalid_service_token` code.
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

    Raises ``HTTPException`` 422 for every method that can't be spelled as
    a bare token, so a caller reaching a URL-query transport has already
    refused everything that transport can't honour by the time it reads
    the return value. An unrecognized method takes the same branch as a
    known-but-unsendable one — the answer is the same either way.

    A bearer credential carrying no token is refused rather than returned
    as a falsy value: every caller tests the return for truthiness, so
    ``""`` would send an anonymous request on behalf of someone who named
    a method. The request schema already refuses that shape, so this
    branch is unreachable over HTTP and exists for the in-process caller
    that builds a :class:`ServiceCredential` directly.
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

    Judges what the caller TYPED, letting composition happen afterwards.
    A composed basic line contains a space
    and a colon, so a validator applied to the line instead would reject
    the very thing it exists to protect — at the door or, worse, in the
    worker after the single-use credential has been spent.

    Every branch returns a policy constant, never the value: this string
    becomes a 422 body, a log line, and a job row.
    ``build_credential_header`` raises on the same inputs and is the
    actual enforcement; this exists so a caller learns before anything is
    composed, reserved, or dispatched.
    """
    method = credential.method
    if method == CredentialMethod.BEARER:
        if not credential.token:
            return BLANK_BEARER_TOKEN_POLICY
        # Through the builder's own rule, which picks the charset by service
        # format; the GDAL header-file charset would refuse a STAC key holding
        # `+` or `/` that the builder accepts.
        return bearer_token_rejection_reason(credential)
    if method == CredentialMethod.BASIC:
        for supplied in (credential.username, credential.password):
            reason = credential_input_rejection_reason(supplied)
            if reason is not None:
                return reason
        # RFC 7617: a colon in the user-id moves the split point rather
        # than failing, so the origin would authenticate a different user.
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

    The one mapping, so the probe door and the probe itself can't disagree.
    Inferring the service kind from URL text instead would refuse a WFS
    served from a path containing `FeatureServer` a credential it supports.

    Bearer travels either way: it fits a URL query and a header line.
    Basic and a named API key exist only as a header, so they need a
    service kind whose credential travels as one. Anything else is a
    method this build doesn't know how to send anywhere.

    The header-or-query question is
    ``carries_credential_as_header_line``, not the GDAL header-file one —
    STAC carries all three methods and writes no header file.
    """
    if method in (CredentialMethod.NONE, CredentialMethod.BEARER):
        return True
    if method in (CredentialMethod.BASIC, CredentialMethod.HEADER_KEY):
        return carries_credential_as_header_line(service_format)
    return False


def credential_or_422(
    credential: ServiceCredential | None, *, service_format: str | None
) -> ServiceCredential | None:
    """The credential this door may now send, bound to *service_format*.

    Returns None when there's nothing to send. Raises 422
    ``unsupported_auth_method`` for a method the named service can't
    carry, and 422 ``invalid_service_token`` for an input the credential
    rules refuse. The caller composes afterwards, at the site that writes
    the header, keeping one producer in the tree.

    ``service_format`` is bound onto the returned credential rather than
    left to the caller to pass again, since it decides whether a header
    may be composed at all: ``build_credential_header`` reads it and
    answers None outside ``HEADER_TRANSPORT_SERVICE_FORMATS``, the
    ArcGIS invariant expressed as an allowlist.
    """
    if credential is None or credential.method == CredentialMethod.NONE:
        return None
    bound = replace(credential, service_format=service_format)
    if not carries_credential_as_header_line(service_format):
        # A URL-query transport, or a format nobody has taught this to
        # carry. Bearer is the only spelling that fits a query parameter.
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

    For the two header-auth formats that's a finished ASCII header
    line, composed here since the queue hop has no site to compose it
    later; for ArcGIS it's the bare token, percent-encoded into the query.
    Validation happens first either way, so a
    credential that can't work never reserves a run or burns a
    single-use stash.

    ``service_format`` defaults to the one already on the credential,
    which is what an in-process caller sets when constructing
    one directly.

    The ArcGIS branch is selected by ``carries_credential_as_header_line``,
    NOT by "the builder answered None": ``build_credential_header`` composes
    an ``X-Esri-Authorization: Bearer`` header for ArcGIS (for GeoLens's own
    httpx requests, a different transport). Handed to the worker as
    ``token``, that line would be percent-encoded by ``build_gdal_source``
    into ``&token=Authorization%3A+Bearer+...`` and fail at the origin after
    the single-use credential is spent.

    That predicate is wider than ``requires_header_token_policy`` by
    exactly STAC, so a STAC refresh crosses as a
    line too; its worker recovers the credential with
    ``credential_from_header_line`` and composes at each write site.
    """
    resolved = (
        service_format
        if service_format is not None
        else (credential.service_format if credential is not None else None)
    )
    bound = credential_or_422(credential, service_format=resolved)
    if bound is None:
        return None
    if not carries_credential_as_header_line(resolved):
        # A URL-query transport: ArcGIS, whose worker-side token is the
        # bare value `build_gdal_source` percent-encodes into ESRIJSON.
        return bearer_token_for_credential(bound)
    pair = build_credential_header(bound)
    if pair is None:
        return bearer_token_for_credential(bound)
    return credential_header_line(pair)


def url_query_token(credential: ServiceCredential | None) -> str | None:
    """The bare token a URL-query transport can carry, or None.

    Never raises, unlike :func:`bearer_token_for_credential`. By the time
    a door reads this, :func:`credential_or_422` has already refused
    every method the named service can't carry, so a non-bearer
    credential here is a header credential travelling its own route, not
    an error. The one caller with no service type yet, the probe, reaches
    all three adapters with one credential, and this is how the ArcGIS
    branch takes the only spelling that fits a query parameter.
    """
    if credential is None or credential.method != CredentialMethod.BEARER:
        return None
    return credential.token


CREDENTIAL_OVER_HTTP_CODE = "credential_over_http"

CREDENTIAL_OVER_HTTP_POLICY = (
    "This service address uses plain HTTP, so GeoLens won't send a credential "
    "to it. Use the service's https:// address, or ask an administrator to "
    "list its host in SERVICE_CREDENTIALS_ALLOW_HTTP_HOSTS."
)


class CredentialOverHttpError(CodedValueError):
    """A credential was about to be sent to an address that isn't https."""

    field = "url"

    def __init__(self) -> None:
        super().__init__(CREDENTIAL_OVER_HTTP_CODE, CREDENTIAL_OVER_HTTP_POLICY)


def _http_host_allowed(url: str) -> bool:
    """Whether the operator listed *url*'s host, or host and port, for http."""
    try:
        parts = urlsplit(url)
        host, port = canonical_service_host(parts.hostname or ""), parts.port or 80
    except ValueError:
        return False
    return host is not None and any(
        allowed == host and allowed_port in (None, port)
        for allowed, allowed_port in settings.http_credential_hosts
    )


def refuse_credential_over_http(
    url: str | None, credential: ServiceCredential | str | None
) -> None:
    """Raise :class:`CredentialOverHttpError` when *credential* would go to
    *url* unencrypted.

    *credential* is a :class:`ServiceCredential` or the string that carries
    one (a token or a header line). Nothing is refused without both a URL and
    a credential, and an http host listed in
    ``SERVICE_CREDENTIALS_ALLOW_HTTP_HOSTS`` passes.
    """
    if isinstance(credential, ServiceCredential):
        carries = credential.method != CredentialMethod.NONE
    else:
        carries = bool(credential)
    if not url or not carries:
        return
    scheme = urlsplit(url).scheme.lower()
    if scheme == "https" or (scheme == "http" and _http_host_allowed(url)):
        return
    raise CredentialOverHttpError


def credential_over_http_or_422(
    url: str | None, credential: ServiceCredential | str | None
) -> None:
    """:func:`refuse_credential_over_http` as a door's coded 422."""
    try:
        refuse_credential_over_http(url, credential)
    except CredentialOverHttpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.message, "field": exc.field},
        ) from None


def custom_credential_header_name(
    credential: ServiceCredential | None,
) -> str | None:
    """The header name an httpx client must refuse to follow a redirect with.

    ``Authorization`` needs nothing:
    httpx drops it on a cross-origin redirect by itself. A name the
    SERVICE chose is forwarded verbatim, so ``make_safe_client`` must be
    told about it, and fails the hop closed rather than handing the key
    to whatever origin the 302 names.
    """
    if credential is None or credential.method != CredentialMethod.HEADER_KEY:
        return None
    return credential.header_name


def bearer_credential(token: str | None) -> ServiceCredential | None:
    """A credential for a caller that still holds only the flat bearer token.

    The deprecated spelling has one meaning, acquired here, so a caller
    not yet converted to the structured object still reaches the same
    validation and composer.
    """
    if not token:
        return None
    return ServiceCredential(method=CredentialMethod.BEARER, token=token)


# The request-side spelling of the same thing. It lives here for the same
# reason the gate above does: `processing/ingest` may not import
# `app.modules.catalog.*`. `sources/schemas.py` imports it back, so every
# import path and the OpenAPI component name stay the same.


def _validate_safe_token(v: str | None) -> str | None:
    """Reject control characters / whitespace in auth tokens.

    Tokens flow into a GDAL_HTTP_HEADER_FILE (WFS/OAPIF bearer) and into
    service query URLs (ArcGIS). A CR/LF or other control character could
    smuggle additional outbound HTTP headers through the libcurl pipeline.
    Legitimate JWT/base64url/ArcGIS tokens never contain control
    characters or whitespace, so reject them at the API boundary (422).

    Carries ``invalid_service_token``, the code a door-layer refusal
    returns and clients map, so a caller reads the same message whichever
    layer judges the credential.
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


# The structured `auth` object every service door accepts, and the
# deprecated flat `token` that means the same thing for a bearer credential.
#
# One model, imported by the re-upload and refresh request models too, so
# the four doors can't describe the same credential four ways. The
# pydantic layer judges SHAPE only — which fields belong to which method,
# and that a request doesn't say the same thing twice. What a username or
# header value may CONTAIN is `core/service_tokens.py`'s rule, applied at
# the door once the method is accepted, since those rules protect a
# composed header line and no line is composed here.

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

# What each method is described by, exactly. The validator's comparison is
# equality, not a subset test, so a body also setting a field from another
# method is refused instead of having that field silently discarded.
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

    An empty or whitespace-only string is not one. Counting it as
    supplied would let ``{"method": "bearer", "token": ""}`` pass the
    shape check, every downstream test being a truthiness test, and the
    door would contact the origin with no credential at all: anonymous
    despite a named method, answering 401 in a way that reads like a
    broken service rather than a blank field.

    Whitespace as well as empty: none of these values may contain
    whitespace anywhere, so a blank-looking one is a typo, never a credential.
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
