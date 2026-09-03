# SPDX-License-Identifier: Apache-2.0
"""BUG-033: --instance / GEOLENS_INSTANCE are normalized at resolution.

A trailing-slash or missing-/api override must canonicalize to the same key
login stored, so credential lookups hit instead of silently falling back to an
anonymous client.
"""
from __future__ import annotations

import pytest

from geolens_cli import auth as _auth
from geolens_cli import config as _config
from geolens_cli import output as _output
from geolens_cli.main import AppState


def _make_state(*, instance_override=None, config_instance=None) -> AppState:
    return AppState(
        output=_output.Formatter(json_mode=False, quiet=True, verbose=False),
        config=_config.AppConfig(instance=config_instance),
        instance_override=instance_override,
    )


CANONICAL = "https://x.example.com/api"


class TestActiveInstanceNormalization:
    @pytest.mark.parametrize(
        "override",
        [
            "https://x.example.com/api/",  # trailing slash
            "https://x.example.com/api",  # already canonical
            "https://x.example.com",  # missing /api
            "https://x.example.com/",  # missing /api + trailing slash
            "  https://x.example.com  ",  # surrounding whitespace
        ],
    )
    def test_override_variants_canonicalize(self, override) -> None:
        state = _make_state(instance_override=override)
        assert state.active_instance() == CANONICAL

    def test_env_variant_canonicalizes(self, monkeypatch) -> None:
        monkeypatch.setenv("GEOLENS_INSTANCE", "https://x.example.com/")
        state = _make_state()
        assert state.active_instance() == CANONICAL

    def test_malformed_override_passed_through(self) -> None:
        state = _make_state(instance_override="ftp://x.example.com")
        # Bad scheme: returned verbatim (resolver does not swallow it).
        assert state.active_instance() == "ftp://x.example.com"

    def test_config_instance_returned_unchanged(self) -> None:
        # config.instance was normalized at login time; returned as-is.
        state = _make_state(config_instance=CANONICAL)
        assert state.active_instance() == CANONICAL


class TestTrailingSlashOverrideFindsStoredCredential:
    """End-to-end: stored creds resolve through a slash-variant override."""

    def test_sdk_finds_bearer_via_slash_override(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        # Login stores the credential under the canonical /api key.
        _auth.store_bearer_token(CANONICAL, "tok-xyz")

        # Override with a trailing-slash variant of the same instance.
        state = _make_state(instance_override="https://x.example.com/api/")
        resolved = state.active_instance()
        assert resolved == CANONICAL
        # The credential is found under the normalized key (BUG-033).
        token = _auth.load_bearer_token(resolved)
        assert token is not None
        assert token.value == "tok-xyz"


class TestSdkHasADefaultHttpTimeout:
    """fix(#1778): AppState.sdk() built its client with the SDK's default
    timeout=None (unbounded) — every command hung forever against a host
    that black-holes packets instead of exiting EXIT_NETWORK, and
    _sdk_helpers.call_sdk's httpx.TimeoutException branch could never
    fire. No login/keyring state is needed: AppState.sdk() constructs an
    anonymous client whenever no bearer token or API key is stored."""

    def test_sdk_client_transport_has_a_bound(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import httpx

        from geolens_cli import _sdk_helpers

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        state = _make_state(config_instance=CANONICAL)

        transport = state.sdk().client.get_httpx_client()

        assert transport.timeout != httpx.Timeout(None)
        assert transport.timeout == httpx.Timeout(
            _sdk_helpers.DEFAULT_HTTP_TIMEOUT_SECONDS
        )
