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


class TestMakeClientBindsTheDefaultTimeout:
    """fix(#1778 review round 2): _sdk_helpers.make_client() is the single
    construction point for every GeolensClient in this package (see
    tests/test_client_construction.py for the structural gate). This pins
    what it actually does: bind the request to DEFAULT_HTTP_TIMEOUT_SECONDS."""

    def test_make_client_sets_the_default_timeout(self) -> None:
        import httpx

        from geolens_cli import _sdk_helpers

        client = _sdk_helpers.make_client("https://x.example.com/api")

        transport = client.client.get_httpx_client()
        assert transport.timeout == httpx.Timeout(
            _sdk_helpers.DEFAULT_HTTP_TIMEOUT_SECONDS
        )

    def test_make_client_passes_through_bearer_and_api_key(self) -> None:
        from geolens_cli import _sdk_helpers

        bearer_client = _sdk_helpers.make_client(
            "https://x.example.com/api", bearer_token="tok-abc"
        )
        assert bearer_client.client.token == "tok-abc"

        api_key_client = _sdk_helpers.make_client(
            "https://x.example.com/api", api_key="key-abc"
        )
        assert api_key_client.client.token == "key-abc"


class TestActiveCredentialKindMarkerPrecedence:
    """fix(#1778 review round 10): AppState.sdk() now consults the
    active-credential-kind marker login writes unconditionally (see
    auth.load_active_credential_kind), so a stale competing credential
    surviving in the OTHER backend can never outrank the credential
    that was actually just stored -- cleanup at login time is
    best-effort tidiness, not what this decision depends on."""

    def test_api_key_login_wins_over_a_stale_bearer_once_the_keyring_is_readable_again(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The regression this round fixes: an API-key login that fell
        back to the file while the keyring was unavailable (round 9
        tolerates that rather than failing the login) leaves an old
        bearer token untouched in the keyring. Once the keyring is
        readable again, the marker -- not the old bearer-first
        precedence -- decides.

        fix(#1778 review round 12): this test briefly needed an explicit
        --no-keyring flag here, because replace_credentials() had
        started refusing outright whenever it could not read the
        account it was about to overwrite -- a PLAIN login's automatic
        file fallback was gone for that case.

        fix(#1778 review round 13): round 12's refusal broke the
        documented automatic fallback for a real headless install, so
        it forces the keyring-free file path instead of aborting (see
        TestSnapshotUnknownForcesFileBackend in test_exit_codes.py).
        This test is back to a PLAIN login -- no --no-keyring needed --
        exercising the actual regression path: an ordinary login that
        cannot read the keyring falls back to the file on its own.
        _delete_stale_credentials' cleanup read of the bearer account
        still hits the broken keyring, and is still tolerated (not
        raised) because keep_backend == "file" -- round 9's behavior
        for that part is unchanged, which is the point of this test."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        original_set = keyring.set_password
        original_get = keyring.get_password

        _auth.store_bearer_token(canonical, "old-bearer-token")

        def locked(*args, **kwargs):
            raise KeyringError("keychain is locked")

        monkeypatch.setattr("keyring.set_password", locked)
        monkeypatch.setattr("keyring.get_password", locked)

        result = runner.invoke(app, ["login", instance, "--api-key", "new-key"])
        assert result.exit_code == 0, result.output

        # The keyring becomes readable again -- the stale bearer token
        # is still sitting there, untouched (cleanup never ran, per
        # round 9's tolerance for an unreadable keyring).
        monkeypatch.setattr("keyring.set_password", original_set)
        monkeypatch.setattr("keyring.get_password", original_get)
        assert _auth.load_bearer_token(canonical) is not None

        state = _make_state(config_instance=canonical)
        sdk = state.sdk()

        assert sdk.credential_kind == "api_key"
        assert sdk.client.token == "new-key"

    def test_bearer_login_wins_over_a_stale_api_key_in_the_file(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The mirror case: a stale api_key left in credentials.toml
        (from an earlier --no-keyring login, say) must not outrank a
        freshly-stored bearer token either."""
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        result = runner.invoke(app, ["login", instance, "--token", "new-bearer"])
        assert result.exit_code == 0, result.output

        # A stale api_key sitting in the file, however it got there --
        # the marker must defend against it regardless of cleanup's
        # own outcome.
        file_data = _auth._read_credentials_file()
        file_data.setdefault(canonical, {})["api_key"] = "stale-file-api-key"
        _auth._write_credentials_file(file_data)

        state = _make_state(config_instance=canonical)
        sdk = state.sdk()

        assert sdk.credential_kind == "bearer"
        assert sdk.client.token == "new-bearer"
