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

from app.modules.catalog.datasets.api.router_export import (
    _COG_PRESIGN_CEILING_SECONDS,
    _COG_PRESIGN_FLOOR_SECONDS,
    _cog_presign_seconds,
    _resolve_download_user,
    _s3_cog_response,
)


def _request_with(exp) -> object:
    return SimpleNamespace(state=SimpleNamespace(download_token_exp=exp))


def test_the_ceiling_is_on_the_order_of_the_mint_ttl():
    """120s minted, 300s ceiling. 3600 was 30x the window SEC-04 enforces."""
    assert _COG_PRESIGN_CEILING_SECONDS <= 300
    assert _COG_PRESIGN_FLOOR_SECONDS <= _COG_PRESIGN_CEILING_SECONDS


def test_presign_expires_with_the_download_token():
    request = _request_with(time.time() + 110)
    seconds = _cog_presign_seconds(request)
    assert _COG_PRESIGN_FLOOR_SECONDS <= seconds <= 111
    assert seconds < _COG_PRESIGN_CEILING_SECONDS


def test_a_long_lived_deadline_is_still_capped():
    request = _request_with(time.time() + 86400)
    assert _cog_presign_seconds(request) == _COG_PRESIGN_CEILING_SECONDS


def test_an_almost_expired_token_still_gets_a_usable_window():
    """The bucket evaluates the deadline on arrival, and clocks disagree."""
    request = _request_with(time.time() + 1)
    assert _cog_presign_seconds(request) == _COG_PRESIGN_FLOOR_SECONDS


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
