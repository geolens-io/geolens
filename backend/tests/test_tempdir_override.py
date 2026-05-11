"""Regression test for GH-101: tempfile.tempdir override.

Source: .planning/quick/260508-rr5-fix-tmp-tmpfs-cap-blocking-large-uploads/

Asserts that importing app.api.main has the side effect of redirecting
Python's stdlib tempfile to settings.upload_staging_dir, so Starlette's
MultiPartParser SpooledTemporaryFile rollover lands on the staging
volume instead of /tmp tmpfs (which is sized 512m on the api service).
"""

from __future__ import annotations

import importlib
import sys
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _restore_tempfile_tempdir():
    """Restore tempfile.tempdir after each test to prevent cross-test contamination.

    Tests in this module intentionally mutate tempfile.tempdir (via module
    re-import side effects). Without teardown, the modified tempdir bleeds into
    subsequent tests that rely on tmp_path, breaking their setup.
    """
    original = tempfile.tempdir
    yield
    tempfile.tempdir = original
    _unregister_prometheus_collector("http_requests_inprogress")
    # Also reset the module cache so the next test always gets a fresh import.
    sys.modules.pop("app.api.main", None)


def _unregister_prometheus_collector(metric_name: str) -> None:
    """Remove reload-sensitive collectors created by app import tests."""
    from prometheus_client import REGISTRY

    for collector, names in list(REGISTRY._collector_to_names.items()):
        if metric_name in names:
            REGISTRY.unregister(collector)


def test_tempdir_override_uses_staging_dir(tmp_path, monkeypatch) -> None:
    """After importing app.api.main, tempfile.gettempdir() returns settings.upload_staging_dir."""
    # Ensure a clean import — drop any cached module so the side effect re-runs.
    sys.modules.pop("app.api.main", None)

    from app.core.config import settings  # noqa: WPS433 — intentional late import

    staging = tmp_path / "staging"
    monkeypatch.setattr(settings, "upload_staging_dir", str(staging))

    importlib.import_module("app.api.main")

    assert tempfile.gettempdir() == settings.upload_staging_dir, (
        "GH-101 regression: tempfile.tempdir was not redirected to "
        f"settings.upload_staging_dir (got {tempfile.gettempdir()!r}, "
        f"expected {settings.upload_staging_dir!r}). "
        "Multipart uploads >511 MiB will fail on /tmp tmpfs again."
    )


def test_tempdir_override_does_not_crash_when_dir_missing(
    tmp_path, monkeypatch
) -> None:
    """Module import survives when upload_staging_dir does not yet exist on disk.

    Guards against breaking unit-test runs / alembic-only containers where
    the /app/staging volume is not mounted.
    """
    missing = tmp_path / "does-not-exist-yet" / "staging"
    assert not missing.exists()

    from app.core.config import settings  # noqa: WPS433

    # Monkeypatch the settings field BEFORE re-importing the module so the
    # side-effect block reads the patched value.
    monkeypatch.setattr(settings, "upload_staging_dir", str(missing))
    sys.modules.pop("app.api.main", None)

    importlib.import_module("app.api.main")

    assert missing.exists(), "Defensive mkdir guard did not create the staging dir"
    assert tempfile.gettempdir() == str(missing)


def test_tempdir_redirect_noops_when_dir_unavailable(monkeypatch) -> None:
    """Do not point tempfile at an unavailable staging path during local collection."""
    from app.core.runtime import staging

    original = tempfile.tempdir

    def raise_permission_error(*_args, **_kwargs):
        raise PermissionError("unavailable")

    monkeypatch.setattr(staging.Path, "mkdir", raise_permission_error)
    monkeypatch.setattr(staging.Path, "is_dir", lambda _self: False)

    staging.redirect_tempfile_to_staging("/app/staging")

    assert tempfile.tempdir == original


def test_tempdir_override_no_hardcoded_path() -> None:
    """The override sources its value from settings, not a hardcoded literal."""
    # Read the source so we fail loudly if a future refactor regresses to '/app/staging'.
    from pathlib import Path as _P

    main_py = _P(__file__).resolve().parents[1] / "app" / "api" / "main.py"
    source = main_py.read_text(encoding="utf-8")

    # The exact override line must reference settings.upload_staging_dir.
    assert "settings.upload_staging_dir" in source, (
        "main.py tempdir override must source settings.upload_staging_dir, "
        "not a hardcoded path."
    )
    # No bare hardcoded '/app/staging' string assignment to tempfile.tempdir.
    # (This is a substring check, deliberately conservative — comments may
    # still contain '/app/staging'.)
    forbidden = 'tempfile.tempdir = "/app/staging"'
    assert forbidden not in source, (
        'main.py contains a hardcoded tempfile.tempdir = "/app/staging" '
        "assignment; route through settings.upload_staging_dir instead."
    )
