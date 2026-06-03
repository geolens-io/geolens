"""Shared pytest fixtures for cli/tests/.

Hand-maintained — NOT regenerated. Provides CliRunner + tmp_xdg_home +
mock_keyring fixtures used across every test module in this package.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


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
