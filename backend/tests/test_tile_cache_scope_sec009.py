"""Regression tests for SEC-009: non-public vector tiles get a private cache scope.

`_authorize_vector_tile_request` returned "public" for a valid NON-public signed
request (it fell through past the signature check), so `_tile_headers` emitted
`Cache-Control: public` + `Access-Control-Allow-Origin: *` and a shared cache
could retain private vector-tile bytes under an auth-less key. The fix returns
"private" for the non-public signed path.

These are pure-function tests (no DB / pool / Titiler): they call the authorizer
directly with a valid signature mocked and assert the resolved cache scope.
"""

import uuid

import pytest

import app.processing.tiles.router as tile_router
from app.processing.tiles.router import (
    _DatasetMeta,
    _authorize_vector_tile_request,
    _tile_headers,
)


class _FakeRequest:
    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


def _meta(visibility: str, record_status: str = "published") -> _DatasetMeta:
    return _DatasetMeta(
        dataset_id=uuid.uuid4(),
        record_id=uuid.uuid4(),
        table_name="vt_test",
        visibility=visibility,
        record_status=record_status,
        created_by=uuid.uuid4(),
        record_type="vector_dataset",
        geometry_type="Point",
        column_info=[],
        tile_cache_ttl=None,
        tile_columns=None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("visibility", ["private", "restricted", "internal"])
async def test_non_public_signed_tile_is_private_scope(monkeypatch, visibility: str):
    """A valid signature on a non-public dataset resolves to cache scope 'private'.

    Fails on main, which returned 'public' (-> Cache-Control: public).
    """
    monkeypatch.setattr(
        tile_router, "verify_tile_signature", lambda scope, exp, sig: True
    )
    scope = await _authorize_vector_tile_request(
        _FakeRequest(),
        _meta(visibility),
        db=None,
        sig="validsig",
        exp=9999999999,
        scope="vt_test",
        user=None,
    )
    assert scope == "private", (
        f"{visibility} tile resolved to non-private scope: {scope}"
    )
    cache_control = _tile_headers(scope, 300)["Cache-Control"]
    assert cache_control.startswith("private")
    assert "public" not in cache_control


@pytest.mark.anyio
async def test_public_published_tile_stays_public_scope():
    """GUARD: public + published tiles stay shared-cacheable (scope 'public')."""
    scope = await _authorize_vector_tile_request(
        _FakeRequest(),
        _meta("public", "published"),
        db=None,
        sig=None,
        exp=None,
        scope=None,
        user=None,
    )
    assert scope == "public"
    assert _tile_headers(scope, 300)["Cache-Control"].startswith("public")


@pytest.mark.anyio
async def test_non_public_without_signature_is_rejected(monkeypatch):
    """GUARD: a non-public dataset with no signature is still 403 (not cached)."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _authorize_vector_tile_request(
            _FakeRequest(),
            _meta("private"),
            db=None,
            sig=None,
            exp=None,
            scope=None,
            user=None,
        )
    assert exc.value.status_code == 403
