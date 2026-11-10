"""Shared pytest fixtures for cli/tests/.

Hand-maintained — NOT regenerated. Provides CliRunner + tmp_xdg_home +
mock_keyring fixtures used across every test module in this package, and
fake_geolens for commands that call the API through the SDK.
"""

from __future__ import annotations

import functools
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from .sdk_fake import FakeGeoLens

GEOLENS_INSTANCE = "https://geolens.example.org/api"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def tmp_xdg_home(monkeypatch, tmp_path) -> Path:
    """Point XDG_CONFIG_HOME at a tmp_path so config writes are isolated."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def mock_keyring(monkeypatch) -> dict:
    """In-memory keyring backend so tests never touch the host keychain."""
    store: dict[tuple[str, str], str] = {}

    def set_password(svc: str, user: str, pwd: str) -> None:
        store[(svc, user)] = pwd

    def get_password(svc: str, user: str) -> str | None:
        return store.get((svc, user))

    def delete_password(svc: str, user: str) -> None:
        store.pop((svc, user), None)

    monkeypatch.setattr("keyring.set_password", set_password)
    monkeypatch.setattr("keyring.get_password", get_password)
    monkeypatch.setattr("keyring.delete_password", delete_password)
    return store


@pytest.fixture
def fake_geolens(monkeypatch, tmp_xdg_home) -> FakeGeoLens:
    """Route every SDK client the CLI builds to a FakeGeoLens.

    The active instance is ``GEOLENS_INSTANCE`` with a generated bearer token
    (``fake.token``), so no stored login or network is involved.
    """
    import geolens

    fake = FakeGeoLens(GEOLENS_INSTANCE)
    monkeypatch.setenv("GEOLENS_INSTANCE", GEOLENS_INSTANCE)
    monkeypatch.setenv("GEOLENS_TOKEN", fake.token)
    monkeypatch.setattr(
        geolens,
        "GeolensClient",
        functools.partial(
            geolens.GeolensClient,
            httpx_args={"transport": httpx.MockTransport(fake.handle)},
        ),
    )
    return fake


@pytest.fixture(autouse=True)
def portal_unchanged_since_inventory(monkeypatch):
    """Cutover finds nothing changed in the portal unless a test says otherwise."""
    monkeypatch.setattr(
        "geolens_cli.arcgis_migrate.inventory_changes", lambda *args: None
    )
