"""Startup warning for a POSTGRES_PASSWORD equal to the published default."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import app.platform.extensions.bootstrap as bootstrap_module
from app.core.config import Settings
from tests.conftest import _reset_registry


class _RecordingLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def warning(self, event: str, **fields) -> None:
        self.warnings.append((event, fields))

    def info(self, *args, **kwargs) -> None:
        pass

    def debug(self, *args, **kwargs) -> None:
        pass


def _settings(password: str, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        postgres_password=password,
        **overrides,
        jwt_secret_key="x" * 40,
        geolens_admin_username="admin",
        geolens_admin_password="test-admin-password-value",
    )


def _events(recorder: _RecordingLogger) -> list[str]:
    return [
        event
        for event, _ in recorder.warnings
        if event == "postgres_password_published_default"
    ]


def test_published_default_validates_and_warns_once_without_the_value(monkeypatch):
    """The default value still validates, logs one warning, and the log holds no password."""
    recorder = _RecordingLogger()
    monkeypatch.setattr(bootstrap_module, "logger", recorder)

    bootstrap_module.warn_if_published_default_postgres_password(_settings("geolens"))

    assert _events(recorder) == ["postgres_password_published_default"]
    dumped = json.dumps(recorder.warnings).lower()
    assert "geolens" not in dumped
    assert "a later release will refuse" in dumped


@pytest.mark.parametrize(
    "password", ["Aa0123456789abcdef_1", "geolens_test", "GEOLENS"]
)
def test_other_passwords_do_not_warn(monkeypatch, password):
    """Any value other than the exact published default logs nothing."""
    recorder = _RecordingLogger()
    monkeypatch.setattr(bootstrap_module, "logger", recorder)

    bootstrap_module.warn_if_published_default_postgres_password(_settings(password))

    assert _events(recorder) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url_override": "postgresql://geolens:geolens@db.example.test/gl"},
        {"tile_database_url_override": "postgresql://tiles:geolens@db.example.test/gl"},
        {
            "database_url_override": "postgresql+asyncpg://u:%67eolens@db.example.test/gl"
        },
    ],
)
def test_url_override_with_published_default_warns_once(monkeypatch, overrides):
    """A main or tile URL override that signs in with the default warns once, without the value."""
    recorder = _RecordingLogger()
    monkeypatch.setattr(bootstrap_module, "logger", recorder)

    bootstrap_module.warn_if_published_default_postgres_password(
        _settings("Aa0123456789abcdef_1", **overrides)
    )

    assert _events(recorder) == ["postgres_password_published_default"]
    assert "geolens" not in json.dumps(recorder.warnings).lower()


@pytest.mark.parametrize("url", ["not a url", "postgresql://u:p@h:notaport/db"])
def test_unparsable_url_override_does_not_raise(monkeypatch, url):
    """An override SQLAlchemy can't parse is skipped rather than failing startup."""
    recorder = _RecordingLogger()
    monkeypatch.setattr(bootstrap_module, "logger", recorder)
    settings_obj = SimpleNamespace(
        postgres_password=SecretStr("Aa0123456789abcdef_1"),
        database_url_override=url,
        tile_database_url_override=url,
    )

    bootstrap_module.warn_if_published_default_postgres_password(settings_obj)

    assert _events(recorder) == []


def test_bootstrap_warns_once_per_start(monkeypatch):
    """bootstrap(), which the API and the worker each run once, emits the warning once."""
    from app.core.config import settings
    import app.core.edition as edition_module

    recorder = _RecordingLogger()
    monkeypatch.setattr(bootstrap_module, "logger", recorder)
    monkeypatch.setattr(settings, "postgres_password", SecretStr("geolens"))
    _reset_registry()
    edition_module._info = None
    try:
        with (
            patch("app.platform.extensions.entry_points", return_value=[]),
            patch("app.platform.extensions.bootstrap.init_storage"),
            patch("app.platform.extensions.bootstrap.init_cache"),
            patch("app.platform.extensions.bootstrap.init_tile_cache"),
            patch("app.core.db.rls.apply_tenancy_rls_from_engine"),
        ):
            asyncio.run(bootstrap_module.bootstrap(app=None))
    finally:
        _reset_registry()
        edition_module._info = None

    assert _events(recorder) == ["postgres_password_published_default"]
