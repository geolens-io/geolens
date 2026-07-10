"""Regression tests for the shared exports temp-dir sweep (ING-04 / P2-04, fix(#435)).

The sweeper lives in ``app.core.runtime.staging`` so the API lifespan and the
worker share one age-aware implementation; entries younger than 1 hour survive.
"""

import os
import time
from pathlib import Path

import structlog


def test_sweep_deletes_only_old_entries(tmp_path: Path) -> None:
    """Old entries (mtime >1h) are deleted; recent entries (<1h) survive.

    Pre-fix: every entry was wiped unconditionally on worker startup,
    truncating in-flight large exports mid-download. Post-fix: the
    sweep gates on `stat.st_mtime` and only deletes entries older
    than `EXPORTS_SWEEP_AGE_SECONDS = 3600`.
    """
    from app.core.runtime.staging import (
        EXPORTS_SWEEP_AGE_SECONDS,
        sweep_orphaned_exports,
    )

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    old_file = exports_dir / "old_export.tif"
    old_file.write_bytes(b"old")
    new_file = exports_dir / "new_export.tif"
    new_file.write_bytes(b"new")

    now = time.time()
    # 2 hours old — must be deleted
    os.utime(old_file, (now - 2 * 3600, now - 2 * 3600))
    # 10 minutes old — must survive
    os.utime(new_file, (now - 600, now - 600))

    assert EXPORTS_SWEEP_AGE_SECONDS == 3600, (
        "EXPORTS_SWEEP_AGE_SECONDS must be 1 hour to match the audit's "
        "rolling-deploy safety window"
    )

    deleted, skipped = sweep_orphaned_exports(exports_dir)

    assert not old_file.exists(), "2-hour-old entry should have been swept"
    assert new_file.exists(), (
        "10-minute-old entry should have survived — this is the in-flight "
        "export the audit's mtime guard protects"
    )
    assert deleted == 1
    assert skipped == 1


def test_sweep_handles_subdirectories(tmp_path: Path) -> None:
    """Subdirectory entries older than threshold are removed recursively (shutil.rmtree)."""
    from app.core.runtime.staging import sweep_orphaned_exports

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    old_dir = exports_dir / "old_export_temp"
    old_dir.mkdir()
    (old_dir / "data.bin").write_bytes(b"x")

    now = time.time()
    # Set mtime on the directory itself
    os.utime(old_dir, (now - 2 * 3600, now - 2 * 3600))

    deleted, skipped = sweep_orphaned_exports(exports_dir)

    assert not old_dir.exists(), "Old subdirectory should have been removed recursively"
    assert deleted == 1
    assert skipped == 0


def test_sweep_skipped_recent_export_logs(tmp_path: Path) -> None:
    """The skip branch emits a structured `sweep_skipped_recent_export` log event."""
    from app.core.runtime.staging import sweep_orphaned_exports

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    new_file = exports_dir / "in_flight_export.tif"
    new_file.write_bytes(b"streaming")
    now = time.time()
    os.utime(new_file, (now - 600, now - 600))  # 10 minutes old

    with structlog.testing.capture_logs() as captured:
        deleted, skipped = sweep_orphaned_exports(exports_dir)

    assert deleted == 0
    assert skipped == 1
    assert new_file.exists()

    skipped_events = [
        record
        for record in captured
        if record.get("event") == "sweep_skipped_recent_export"
    ]
    assert len(skipped_events) == 1, (
        f"Expected exactly one sweep_skipped_recent_export event; got: {captured}"
    )
    skipped_event = skipped_events[0]
    assert skipped_event["path"] == str(new_file)
    assert "age_seconds" in skipped_event
    assert skipped_event["threshold_seconds"] == 3600


def test_sweep_empty_dir_noop(tmp_path: Path) -> None:
    """An empty exports directory yields no deletions, no skips, and no errors."""
    from app.core.runtime.staging import sweep_orphaned_exports

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    deleted, skipped = sweep_orphaned_exports(exports_dir)

    assert deleted == 0
    assert skipped == 0


def test_sweep_missing_dir_is_noop(tmp_path: Path) -> None:
    """If the exports dir does not exist, sweep is a no-op (no FileNotFoundError)."""
    from app.core.runtime.staging import sweep_orphaned_exports

    exports_dir = tmp_path / "exports"
    # Deliberately do NOT create exports_dir
    assert not exports_dir.exists()

    deleted, skipped = sweep_orphaned_exports(exports_dir)

    assert deleted == 0
    assert skipped == 0


def test_api_and_worker_share_one_sweeper() -> None:
    """fix(#435): both startup paths bind the same age-aware sweeper.

    The API lifespan used to delete every `exports/` entry unconditionally, which
    truncated exports owned by a surviving sibling Uvicorn worker on the shared
    staging volume. If someone reintroduces a bespoke cleanup loop, they will drop
    this import and this test fails.
    """
    import app.api.main as api_main
    import app.platform.jobs.worker as worker_main
    from app.core.runtime import staging

    assert api_main.sweep_orphaned_exports is staging.sweep_orphaned_exports
    assert worker_main.sweep_orphaned_exports is staging.sweep_orphaned_exports
