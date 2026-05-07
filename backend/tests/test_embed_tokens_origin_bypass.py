"""Unit-level regression tests for Phase 268 H-31 — embed-token Origin bypass.

The legacy localhost-Origin bypass was trivially forgeable by non-browser
callers: a curl/CLI/server-side caller could set ``Origin: http://localhost``
and skip any allowed_origins whitelist. The fix gates the bypass on
``request.client.host`` being a loopback IP — this is the actual TCP peer
address from the ASGI socket, not a header, and cannot be spoofed by a
remote attacker.

These tests exercise the helpers + the validation function via mocks so
they do not require a database.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.embed_tokens import service as embed_service


def _make_request(*, origin: str | None, client_host: str | None) -> MagicMock:
    """Construct a mock Request with the given Origin header and client.host."""
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    request = MagicMock()
    request.headers = headers
    request.client = (
        SimpleNamespace(host=client_host) if client_host is not None else None
    )
    return request


class TestClientIsLoopback:
    """Phase 268 H-31: _client_is_loopback gates bypass on TCP peer."""

    def test_127_0_0_1_is_loopback(self):
        request = _make_request(origin=None, client_host="127.0.0.1")
        assert embed_service._client_is_loopback(request) is True

    def test_ipv6_loopback_is_loopback(self):
        request = _make_request(origin=None, client_host="::1")
        assert embed_service._client_is_loopback(request) is True

    def test_remote_address_is_not_loopback(self):
        request = _make_request(origin=None, client_host="8.8.8.8")
        assert embed_service._client_is_loopback(request) is False

    def test_attacker_lan_address_is_not_loopback(self):
        request = _make_request(origin=None, client_host="10.0.0.5")
        assert embed_service._client_is_loopback(request) is False

    def test_missing_client_returns_false(self):
        request = _make_request(origin=None, client_host=None)
        assert embed_service._client_is_loopback(request) is False


class TestEmbedTokenOriginBypassRequiresLoopbackPeer:
    """Phase 268 H-31: validate_embed_token_access must NOT honor a forged
    ``Origin: http://localhost`` from a non-loopback TCP peer."""

    @pytest.mark.anyio
    async def test_remote_caller_forging_localhost_origin_is_rejected(
        self, monkeypatch
    ):
        """An attacker on a remote host who sets ``Origin: http://localhost``
        must fail the allowed_origins check — the legacy bypass is now
        gated on TCP peer being loopback."""
        # Patch the cache to return a positive cache hit with allowed_origins.
        cache = AsyncMock()
        cache.get = AsyncMock(
            return_value={
                "is_valid": True,
                "scoped_dataset_ids": ["00000000-0000-0000-0000-000000000001"],
                "allowed_origins": ["https://customer.example.com"],
                "map_id": "00000000-0000-0000-0000-000000000002",
            }
        )
        cache.set = AsyncMock()
        monkeypatch.setattr(embed_service, "get_cache", lambda: cache)

        # Forged Origin from a REMOTE peer.
        request = _make_request(
            origin="http://localhost:3000", client_host="8.8.8.8"
        )

        result = await embed_service.validate_embed_token_access(
            raw_token="any-raw-token",
            dataset_id="00000000-0000-0000-0000-000000000001",
            db=AsyncMock(),
            request=request,
        )
        assert result is False, (
            "H-31 regression: a remote caller who forges Origin: localhost "
            "must be rejected when the token has an allowed_origins list."
        )

    @pytest.mark.anyio
    async def test_localhost_origin_from_loopback_peer_is_allowed(
        self, monkeypatch
    ):
        """Local-development scenario: same-host caller with localhost
        Origin and loopback TCP peer is allowed (preserves the original
        dev-ergonomics goal)."""
        import uuid

        dataset_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        cache = AsyncMock()
        cache.get = AsyncMock(
            return_value={
                "is_valid": True,
                "scoped_dataset_ids": [str(dataset_id)],
                "allowed_origins": ["https://customer.example.com"],
                "map_id": "00000000-0000-0000-0000-000000000002",
            }
        )
        cache.set = AsyncMock()
        monkeypatch.setattr(embed_service, "get_cache", lambda: cache)

        request = _make_request(
            origin="http://localhost:3000", client_host="127.0.0.1"
        )

        result = await embed_service.validate_embed_token_access(
            raw_token="any-raw-token",
            dataset_id=dataset_id,
            db=AsyncMock(),
            request=request,
        )
        assert result is True

    @pytest.mark.anyio
    async def test_unlisted_origin_from_loopback_peer_still_rejected(
        self, monkeypatch
    ):
        """A loopback TCP peer with a non-localhost, non-allowlisted Origin
        is still rejected — the bypass only applies to localhost Origins."""
        cache = AsyncMock()
        cache.get = AsyncMock(
            return_value={
                "is_valid": True,
                "scoped_dataset_ids": ["00000000-0000-0000-0000-000000000001"],
                "allowed_origins": ["https://customer.example.com"],
                "map_id": "00000000-0000-0000-0000-000000000002",
            }
        )
        cache.set = AsyncMock()
        monkeypatch.setattr(embed_service, "get_cache", lambda: cache)

        request = _make_request(
            origin="https://evil.example.com", client_host="127.0.0.1"
        )

        result = await embed_service.validate_embed_token_access(
            raw_token="any-raw-token",
            dataset_id="00000000-0000-0000-0000-000000000001",
            db=AsyncMock(),
            request=request,
        )
        assert result is False
