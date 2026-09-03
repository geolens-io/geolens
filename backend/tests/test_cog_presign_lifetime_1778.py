"""fix(#1778): the COG redirect must not outlive the token that authorized it.

The s3 branch of the COG download signed a bucket URL for 3600 seconds. The
credential that gates the route is deliberately short-lived: POST
/auth/download-token/{id} mints a typ='download', scope='dataset:{id}' JWT with
a 120s TTL. The presigned URL carries its SigV4 signature in the query string
and is bound to neither the caller, the session, nor the dataset grant, so
revoking the grant, flipping the record to private, disabling the account or
discarding the token does not invalidate it. The access gate above this branch
is the full RBAC path, so it is reached for private and internal datasets too.
"""

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace

import pytest

from app.modules.catalog.datasets.api.router_export import (
    _COG_PRESIGN_CEILING_SECONDS,
    _COG_PRESIGN_MINIMUM_SECONDS,
    _cog_presign_seconds,
    _resolve_download_user,
    _s3_cog_response,
)


def _request_with(exp) -> object:
    return SimpleNamespace(state=SimpleNamespace(download_token_exp=exp))


def test_the_ceiling_is_on_the_order_of_the_mint_ttl():
    """120s minted, 300s ceiling. 3600 was 30x the window SEC-04 enforces."""
    assert _COG_PRESIGN_CEILING_SECONDS <= 300


def test_there_is_no_floor_only_sigv4s_own_minimum():
    """fix(#1778 codex r8): a floor mints a URL that outlives its credential.

    `require_signable_job_lifetime` settled this for the upload doors: there is
    no `ExpiresIn` value meaning "already dead", so the only way not to hand
    out a live URL is not to sign one. The minimum here is SigV4's own bound on
    `X-Amz-Expires`, not a policy choice.
    """
    import app.modules.catalog.datasets.api.router_export as module

    assert _COG_PRESIGN_MINIMUM_SECONDS == 1
    assert not hasattr(module, "_COG_PRESIGN_FLOOR_SECONDS"), (
        "the floor is the defect; it must not come back under its old name"
    )


def test_presign_expires_with_the_download_token():
    request = _request_with(time.time() + 110)
    seconds = _cog_presign_seconds(request)
    assert 0 < seconds <= 110
    assert seconds < _COG_PRESIGN_CEILING_SECONDS


def test_a_long_lived_deadline_is_still_capped():
    request = _request_with(time.time() + 86400)
    assert _cog_presign_seconds(request) == _COG_PRESIGN_CEILING_SECONDS


@pytest.mark.parametrize(
    "remaining", [30.0, 5.0, 2.0, 1.9, 1.0, 0.9, 0.5, 0.0, -0.5, -120.0]
)
def test_the_signature_never_outlives_the_token(remaining: float) -> None:
    """fix(#1778 codex r8): the invariant, across the boundary.

    Signed now for N seconds, the URL dies at now+N, and that must land at or
    before the token's own expiry. The 60-second floor broke this for every
    token with under a minute left: one second of credential bought a minute of
    access to a private COG.

    Stated as raise-or-fit rather than as an outcome per input, because at
    exactly one second left the answer is a race between this function's clock
    read and the boundary -- and BOTH outcomes are safe, which is the point. A
    401 hands out nothing; a 1-second signature dies before the token does.
    `test_a_live_token_still_gets_a_signature` stops that being satisfied by
    always raising.
    """
    from fastapi import HTTPException

    token_expiry = time.time() + remaining
    # The clock BEFORE the call bounds the function's own read from below, so
    # this comparison is exact rather than racing it. Reading it again after
    # the call would be stricter than the code can be: `ExpiresIn` starts when
    # the signature is minted, and the residual between reading the clock and
    # signing is the one `sign_url_with_deadline` documents as irreducible.
    # Truncation is what covers it here -- int() discards the fraction, which
    # is headroom in the safe direction.
    before = time.time()
    try:
        signed_for = _cog_presign_seconds(_request_with(token_expiry))
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "expired" in exc.detail.lower()
        return

    assert signed_for >= _COG_PRESIGN_MINIMUM_SECONDS
    assert before + signed_for <= token_expiry, (
        f"a {remaining}s token bought {signed_for}s of bucket access"
    )


@pytest.mark.parametrize("remaining", [2.0, 10.0, 119.0])
def test_a_live_token_still_gets_a_signature(remaining: float) -> None:
    """The counterweight: refusing everything would satisfy the invariant."""
    signed_for = _cog_presign_seconds(_request_with(time.time() + remaining))
    assert _COG_PRESIGN_MINIMUM_SECONDS <= signed_for <= remaining


@pytest.mark.parametrize("remaining", [0.9, 0.0, -0.5, -120.0])
def test_a_token_with_nothing_left_is_refused_not_rounded_up(
    remaining: float,
) -> None:
    """Below SigV4's one-second minimum there is nothing safe to mint."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        _cog_presign_seconds(_request_with(time.time() + remaining))

    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail.lower()


def test_callers_without_a_download_token_get_the_ceiling():
    """Session JWT, API key, or anonymous on a public dataset."""
    assert _cog_presign_seconds(SimpleNamespace(state=SimpleNamespace())) == (
        _COG_PRESIGN_CEILING_SECONDS
    )
    for junk in (None, "not-a-number", object()):
        assert _cog_presign_seconds(_request_with(junk)) == (
            _COG_PRESIGN_CEILING_SECONDS
        )


def test_the_redirect_no_longer_signs_a_flat_hour():
    src = inspect.getsource(_s3_cog_response)
    assert "expiration=3600" not in src
    assert "_cog_presign_seconds(request)" in src


def test_the_dependency_records_the_token_deadline():
    """Without this the redirect has nothing to derive its window from."""
    src = inspect.getsource(_resolve_download_user)
    assert "request.state.download_token_exp" in src
