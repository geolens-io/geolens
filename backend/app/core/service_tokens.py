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

import string

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
