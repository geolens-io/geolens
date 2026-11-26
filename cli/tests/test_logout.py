# SPDX-License-Identifier: Apache-2.0
"""logout credential + config teardown semantics.

Logging out of a non-default instance (via --instance / GEOLENS_INSTANCE
override) must remove ONLY that instance's stored credentials and must NOT delete
the global config.toml that points at the default instance.
"""
from __future__ import annotations

from geolens_cli import config as _config
from geolens_cli.main import app


class TestLogoutConfigPreservation:
    def test_logout_default_instance_clears_config(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        runner.invoke(app, ["login", "https://prod.example.com/api", "--token", "tok-prod"])
        assert _config.config_path().is_file()

        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        # Logging out of the default instance clears the global config.
        assert not _config.config_path().is_file()
        # And removes the credential (stored under the canonical /api key).
        assert mock_keyring.get(("geolens", "https://prod.example.com/api")) is None

    def test_logout_override_instance_preserves_default_config(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        # Default instance is prod; we are also logged into a staging instance.
        # Both stored under their canonical /api form.
        runner.invoke(app, ["login", "https://prod.example.com/api", "--token", "tok-prod"])
        mock_keyring[("geolens", "https://staging.example.com/api")] = "tok-staging"

        # Log out of staging via --instance override.
        result = runner.invoke(
            app,
            ["--instance", "https://staging.example.com/api", "logout"],
        )
        assert result.exit_code == 0, result.output

        # The global config (default = prod) MUST survive.
        assert _config.config_path().is_file(), "global config.toml was wiped"
        cfg = _config.load_config()
        assert cfg.instance == "https://prod.example.com/api"
        # Prod credential is untouched.
        assert mock_keyring.get(("geolens", "https://prod.example.com/api")) == "tok-prod"
        # Only the staging credential was removed.
        assert mock_keyring.get(("geolens", "https://staging.example.com/api")) is None


class TestLogoutRevokesServerSession:
    _LOGOUT = "geolens.api.auth.logout_current_session_auth_logout_session_post.sync_detailed"

    def _login_with_refresh(self, runner, mock_keyring):
        from geolens_cli import auth as _auth

        runner.invoke(app, ["login", "https://prod.example.com/api", "--token", "tok"])
        _auth.store_refresh_token("https://prod.example.com/api", "refresh-1", bearer_token="tok")

    def test_logout_sends_the_refresh_token_to_the_server(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        self._login_with_refresh(runner, mock_keyring)
        calls = []

        class _Resp:
            status_code = 204

        monkeypatch.setattr(self._LOGOUT, lambda **kw: calls.append(kw) or _Resp())
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["body"].refresh_token == "refresh-1"
        assert "may still be active" not in result.output

    def test_logout_still_clears_local_credentials_when_server_unreachable(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import httpx

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        self._login_with_refresh(runner, mock_keyring)

        def fail(**_kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(self._LOGOUT, fail)
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert "may still be active" in result.output
        assert mock_keyring.get(("geolens", "https://prod.example.com/api")) is None

    def test_api_key_login_makes_no_server_call(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        runner.invoke(app, ["login", "https://prod.example.com/api", "--api-key", "k"])
        calls = []
        monkeypatch.setattr(self._LOGOUT, lambda **kw: calls.append(kw))
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert calls == []

    def test_unpaired_refresh_token_is_not_used(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        runner.invoke(app, ["login", "https://prod.example.com/api", "--token", "tok"])
        _auth.store_refresh_token(
            "https://prod.example.com/api", "old-refresh", bearer_token="older-tok"
        )
        calls = []

        class _Resp:
            status_code = 204

        monkeypatch.setattr(self._LOGOUT, lambda **kw: calls.append(kw) or _Resp())
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert "body" not in calls[0]

    def test_rejected_bearer_warns(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        runner.invoke(app, ["login", "https://prod.example.com/api", "--token", "tok"])

        class _Resp:
            status_code = 401

        monkeypatch.setattr(self._LOGOUT, lambda **kw: _Resp())
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert "may still be active" in result.output

    def test_rejected_refresh_token_warns(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        self._login_with_refresh(runner, mock_keyring)

        class _Resp:
            status_code = 401

        monkeypatch.setattr(self._LOGOUT, lambda **kw: _Resp())
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert "may still be active" in result.output

    def test_unreadable_refresh_storage_still_revokes_the_bearer(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        runner.invoke(app, ["login", "https://prod.example.com/api", "--token", "tok"])

        def unreadable(_instance):
            raise _auth.KeyringCredentialUnreadable("refresh", "locked")

        monkeypatch.setattr(_auth, "load_refresh_token_strict", unreadable)
        calls = []

        class _Resp:
            status_code = 204

        monkeypatch.setattr(self._LOGOUT, lambda **kw: calls.append(kw) or _Resp())
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert "body" not in calls[0]
