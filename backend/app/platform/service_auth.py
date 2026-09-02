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

from fastapi import HTTPException, status

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
    """
    resolved = (
        service_format
        if service_format is not None
        else (credential.service_format if credential is not None else None)
    )
    bound = credential_or_422(credential, service_format=resolved)
    if bound is None:
        return None
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
