"""Which service credential methods this build can actually carry.

feat(#1746). ``core/service_tokens.py`` says what a credential may LOOK like
and how it is composed. This module answers the narrower question every door
has to answer before it writes anything: of the methods a caller can now
describe in a request, which ones does the transport underneath support today.

Right now that is a bearer token and nothing else. A username and password or a
named API key parses, validates and then stops here with a 422, because no
writer composes a header line for them yet. A closed door is the point: the
alternative shape, accepting the request and sending an unauthenticated fetch,
fails later at the origin with a 401 and reads like a credential problem rather
than a missing feature.

Lives in ``platform/`` because all three callers are in different layers and
none may import another: ``modules/catalog`` for the probe, preview, re-upload
and refresh doors, ``processing/ingest`` for the queue-time check, and
``platform/refresh`` for the dispatch decision. All three may import here.

The gate is one function so the lane that adds a transport lifts it in one
place. Widening it means deleting a branch here, not finding four doors.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.service_tokens import CredentialMethod, ServiceCredential

UNSUPPORTED_AUTH_METHOD_CODE = "unsupported_auth_method"

# Describes the policy and never the input, on the same reasoning as
# HEADER_TOKEN_POLICY: this reaches a 422 body and a log line. No brace, so it
# cannot grow an interpolation later without failing the pin in
# tests/test_service_refresh_1220.py.
UNSUPPORTED_AUTH_METHOD_POLICY = (
    "This authentication method is not available yet for this service; "
    "use a bearer token."
)


def bearer_token_for_credential(credential: ServiceCredential | None) -> str | None:
    """The bearer token *credential* travels as, or None when there is none.

    Raises ``HTTPException`` 422 for every method this build cannot send, so a
    door that calls this has already refused everything it cannot honour by the
    time it reads the return value. An unrecognized method takes the same
    branch as a known-but-unsupported one: the request described something this
    build will not send, and the answer is the same either way.
    """
    if credential is None:
        return None
    method = credential.method
    if method == CredentialMethod.NONE:
        return None
    if method == CredentialMethod.BEARER:
        return credential.token
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": UNSUPPORTED_AUTH_METHOD_CODE,
            "message": UNSUPPORTED_AUTH_METHOD_POLICY,
        },
    )
