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
