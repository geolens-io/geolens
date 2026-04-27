"""Config module — XDG paths, TOML round-trip, atomic write, mode 0600."""
from __future__ import annotations

import os
import stat

import pytest
import tomllib

from geolens_cli.config import (
    AppConfig,
    atomic_write_text,
    config_path,
    credentials_path,
    get_instance_from_env,
    get_token_from_env,
    load_config,
    normalize_instance_url,
    write_default_instance,
)


class TestXdgPaths:
    def test_config_path_under_xdg_home(self, tmp_xdg_home) -> None:
        assert config_path() == tmp_xdg_home / "geolens" / "config.toml"

    def test_credentials_path_under_xdg_home(self, tmp_xdg_home) -> None:
        assert credentials_path() == tmp_xdg_home / "geolens" / "credentials.toml"


class TestConfigRoundTrip:
    def test_load_when_missing_returns_empty(self, tmp_xdg_home) -> None:
        cfg = load_config()
        assert cfg.instance is None
        assert cfg.username is None

    def test_write_then_load_roundtrip(self, tmp_xdg_home) -> None:
        write_default_instance("https://x.example.com", username="alice")
        cfg = load_config()
        assert cfg.instance == "https://x.example.com"
        assert cfg.username == "alice"

    def test_write_omits_username_when_none(self, tmp_xdg_home) -> None:
        write_default_instance("https://x.example.com", username=None)
        data = tomllib.loads(config_path().read_text())
        assert data["default"]["instance"] == "https://x.example.com"
        assert "username" not in data["default"]

    def test_config_toml_never_contains_token(self, tmp_xdg_home) -> None:
        """D-11: tokens never appear in config.toml."""
        write_default_instance("https://x.example.com", username="alice")
        text = config_path().read_text()
        assert "token" not in text.lower()
        assert "api_key" not in text.lower()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
class TestFileModes:
    def test_credentials_file_mode_0600(self, tmp_xdg_home) -> None:
        atomic_write_text(credentials_path(), "x = 1\n", mode=0o600)
        actual_mode = stat.S_IMODE(credentials_path().stat().st_mode)
        assert actual_mode == 0o600, f"got {oct(actual_mode)}"

    def test_parent_dir_mode_0700(self, tmp_xdg_home) -> None:
        atomic_write_text(credentials_path(), "x = 1\n", mode=0o600)
        actual_mode = stat.S_IMODE(credentials_path().parent.stat().st_mode)
        assert actual_mode == 0o700, f"got {oct(actual_mode)}"


class TestEnvOverrides:
    def test_get_instance_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GEOLENS_INSTANCE", "https://from-env.example.com")
        assert get_instance_from_env() == "https://from-env.example.com"

    def test_get_token_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GEOLENS_TOKEN", "abc.def.ghi")
        assert get_token_from_env() == "abc.def.ghi"

    def test_env_unset_returns_none(self, monkeypatch) -> None:
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        assert get_instance_from_env() is None
        assert get_token_from_env() is None


class TestNormalizeInstanceUrl:
    def test_strips_trailing_slash(self) -> None:
        assert normalize_instance_url("https://x.example.com/") == "https://x.example.com"

    def test_strips_whitespace(self) -> None:
        assert normalize_instance_url("  https://x.example.com  ") == "https://x.example.com"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_instance_url("")

    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            normalize_instance_url("ftp://x.example.com")
