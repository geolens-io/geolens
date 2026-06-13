# SPDX-License-Identifier: Apache-2.0
"""logout credential + config teardown semantics.

BUG-032: logging out of a non-default instance (via --instance / GEOLENS_INSTANCE
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
        runner.invoke(app, ["login", "https://prod.example.com", "--token", "tok-prod"])
        assert _config.config_path().is_file()

        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output
        # Logging out of the default instance clears the global config.
        assert not _config.config_path().is_file()
        # And removes the credential.
        assert mock_keyring.get(("geolens", "https://prod.example.com")) is None

    def test_logout_override_instance_preserves_default_config(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        # Default instance is prod; we are also logged into a staging instance.
        runner.invoke(app, ["login", "https://prod.example.com", "--token", "tok-prod"])
        mock_keyring[("geolens", "https://staging.example.com")] = "tok-staging"

        # Log out of staging via --instance override.
        result = runner.invoke(
            app,
            ["--instance", "https://staging.example.com", "logout"],
        )
        assert result.exit_code == 0, result.output

        # BUG-032: the global config (default = prod) MUST survive.
        assert _config.config_path().is_file(), "global config.toml was wiped"
        cfg = _config.load_config()
        assert cfg.instance == "https://prod.example.com"
        # Prod credential is untouched.
        assert mock_keyring.get(("geolens", "https://prod.example.com")) == "tok-prod"
        # Only the staging credential was removed.
        assert mock_keyring.get(("geolens", "https://staging.example.com")) is None
