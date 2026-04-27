"""Auth module — keyring + file fallback + refresh-retry."""
from __future__ import annotations

import os
import stat

import pytest

from geolens_cli import auth as _auth
from geolens_cli import config as _config


INSTANCE = "https://test.example.com"


class TestKeyringStore:
    def test_store_bearer_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_bearer_token(INSTANCE, "tok-1")
        assert backend == "keyring"
        assert mock_keyring[("geolens", INSTANCE)] == "tok-1"

    def test_store_api_key_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_api_key(INSTANCE, "key-1")
        assert backend == "keyring"
        assert mock_keyring[("geolens", f"{INSTANCE}:api_key")] == "key-1"

    def test_store_refresh_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_refresh_token(INSTANCE, "ref-1")
        assert backend == "keyring"
        assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == "ref-1"

    def test_load_bearer_from_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        mock_keyring[("geolens", INSTANCE)] = "tok-2"
        tok = _auth.load_bearer_token(INSTANCE)
        assert tok is not None
        assert tok.value == "tok-2"

    def test_load_returns_none_when_missing(self, tmp_xdg_home, mock_keyring) -> None:
        assert _auth.load_bearer_token(INSTANCE) is None
        assert _auth.load_api_key(INSTANCE) is None
        assert _auth.load_refresh_token(INSTANCE) is None


class TestNoKeyringFallback:
    def test_store_bearer_no_keyring_writes_file(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_bearer_token(INSTANCE, "tok-3", no_keyring=True)
        assert backend == "file"
        # Token should NOT be in keyring
        assert ("geolens", INSTANCE) not in mock_keyring
        # File should contain the token
        text = _config.credentials_path().read_text()
        assert "tok-3" in text

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
    def test_credentials_file_mode_0600(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.store_bearer_token(INSTANCE, "tok-4", no_keyring=True)
        actual_mode = stat.S_IMODE(_config.credentials_path().stat().st_mode)
        assert actual_mode == 0o600

    def test_load_bearer_from_file(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.store_bearer_token(INSTANCE, "tok-5", no_keyring=True)
        tok = _auth.load_bearer_token(INSTANCE)
        assert tok is not None
        assert tok.value == "tok-5"


class TestKeyringErrorAutoFallback:
    def test_keyring_error_falls_back_to_file(self, tmp_xdg_home, monkeypatch) -> None:
        from keyring.errors import NoKeyringError

        def explode(*args, **kwargs):
            raise NoKeyringError("no backend")

        monkeypatch.setattr("keyring.set_password", explode)
        backend = _auth.store_bearer_token(INSTANCE, "tok-6")
        assert backend == "file"
        text = _config.credentials_path().read_text()
        assert "tok-6" in text


class TestEnvOverride:
    def test_env_token_takes_precedence(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        mock_keyring[("geolens", INSTANCE)] = "tok-from-keyring"
        monkeypatch.setenv("GEOLENS_TOKEN", "tok-from-env")
        tok = _auth.load_bearer_token(INSTANCE)
        assert tok is not None
        assert tok.value == "tok-from-env"


class TestDeleteCredentials:
    def test_delete_clears_keyring_and_file(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.store_bearer_token(INSTANCE, "tok", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "ref", no_keyring=False)
        _auth.store_api_key(INSTANCE, "key", no_keyring=True)  # this one in file
        _auth.delete_credentials(INSTANCE)
        # Keyring entries gone
        assert ("geolens", INSTANCE) not in mock_keyring
        assert ("geolens", f"{INSTANCE}:refresh") not in mock_keyring
        # File entry gone
        assert _auth.load_api_key(INSTANCE) is None

    def test_delete_idempotent_when_nothing_stored(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.delete_credentials(INSTANCE)  # should not raise
