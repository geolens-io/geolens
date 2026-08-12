"""Regression tests for the shared exports temp-dir sweep (ING-04 / P2-04, fix(#435)).

The sweeper lives in ``app.core.runtime.staging`` so the API lifespan and the
worker share one age-aware implementation; entries younger than 1 hour survive.
"""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

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
    data_file = old_dir / "data.bin"
    data_file.write_bytes(b"x")

    now = time.time()
    # fix(#1435 codex round 2): age the contained file too, not just the
    # directory — sweep_orphaned_exports now takes the most recent of the
    # two (see _latest_mtime), so a freshly-written file inside an
    # old-looking directory would otherwise read as still-active.
    os.utime(old_dir, (now - 2 * 3600, now - 2 * 3600))
    os.utime(data_file, (now - 2 * 3600, now - 2 * 3600))

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


def test_stale_jobs_sweeper_also_sweeps_orphaned_exports() -> None:
    """The periodic sweeper loop must sweep exports on every cycle, not just
    at process boot.

    Pre-fix, ``sweep_orphaned_exports`` only ran once at API startup and once
    at worker startup, so export residue from a hard process death (SIGKILL,
    OOM — not a clean restart) sat until the next boot. The sweep is
    idempotent and age-thresholded (see the module docstring above), so it is
    safe on every ``_stale_jobs_sweeper`` cycle too.

    Structural, because the alternative is waiting on the sweeper's real
    interval. Mirrors the `inspect.getsource(main.lifespan)` pattern used
    elsewhere to pin behavior inside this same nested closure (e.g.
    `test_enterprise_overlay_startup_check.py`,
    `test_service_refresh_1220.py`). Slices out just the
    `_stale_jobs_sweeper` function body rather than searching the whole
    `lifespan` source, because a call to the sweep already appears once in
    `lifespan` for the boot call — a whole-function search would pass even
    without this fix.

    The actual sweep + conditional log call is factored into the top-level
    `_sweep_orphaned_exports_and_log` helper (kept out of the nested closure
    so the extra branch does not push `lifespan`'s McCabe complexity over its
    gate), so this pins both halves: the loop calls the helper, and the
    helper calls `sweep_orphaned_exports`.
    """
    import inspect

    from app.api import main

    source = inspect.getsource(main.lifespan)
    sweeper_start = source.index("async def _stale_jobs_sweeper")
    sweeper_end = source.index("stale_jobs_task = asyncio.create_task", sweeper_start)
    sweeper_body = source[sweeper_start:sweeper_end]

    assert "_sweep_orphaned_exports_and_log(exports_dir" in sweeper_body, (
        "the periodic sweeper loop must call the export-sweep helper so export "
        "residue from a hard process death does not wait for the next restart"
    )

    helper_source = inspect.getsource(main._sweep_orphaned_exports_and_log)
    assert "sweep_orphaned_exports(" in helper_source, (
        "_sweep_orphaned_exports_and_log must actually call sweep_orphaned_exports"
    )
    assert "EXPORTS_PERIODIC_SWEEP_AGE_SECONDS" in helper_source, (
        "the periodic sweep must use the wider periodic threshold, not the "
        "boot-time default — see test_periodic_sweep_survives_a_slow_export "
        "below for why"
    )


def test_periodic_sweep_survives_a_slow_export(tmp_path: Path) -> None:
    """fix(#1435 codex round 1): the periodic sweeper runs continuously
    (every CREDENTIAL_RENEWAL_INTERVAL_SECONDS), unlike the boot-time
    callers, which only fire on a restart. A directory's mtime is set once
    at export creation and does not advance while ogr2ogr keeps writing the
    file inside it or a client keeps streaming it out, so reusing the
    1-hour boot threshold there would delete any export whose total
    lifetime (ogr2ogr + zip + download) exceeds 1 hour on the very next
    5-minute cycle — guaranteed, not just an unlucky restart coincidence.

    A 2-hour-old export (older than the 1-hour boot threshold, younger than
    the 4-hour periodic threshold) must survive the periodic helper, even
    though the boot-time default alone would have deleted it.
    """
    from app.api.main import _sweep_orphaned_exports_and_log
    from app.core.runtime.staging import sweep_orphaned_exports

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    slow_export = exports_dir / "still-downloading"
    slow_export.mkdir()
    export_file = slow_export / "export.gpkg"
    export_file.write_bytes(b"x")
    now = time.time()
    # Age both the directory AND the file inside it — sweep_orphaned_exports
    # takes the most recent of the two (fix #1435 codex round 2), so a
    # freshly-written file would otherwise mask the aged directory.
    os.utime(slow_export, (now - 2 * 3600, now - 2 * 3600))  # 2 hours old
    os.utime(export_file, (now - 2 * 3600, now - 2 * 3600))

    log = structlog.get_logger("test")
    _sweep_orphaned_exports_and_log(exports_dir, log)
    assert slow_export.exists(), (
        "a 2-hour-old export must survive the periodic sweep — it is well "
        "within the periodic threshold even though it is past the boot one"
    )

    # Confirms the boot-time default alone WOULD have deleted it — this is
    # the exact regression the periodic helper's wider threshold guards
    # against, not just a threshold that happens to be wide enough anyway.
    deleted, _ = sweep_orphaned_exports(exports_dir)
    assert deleted == 1
    assert not slow_export.exists()


def test_sweep_skips_a_directory_whose_file_is_still_being_written(
    tmp_path: Path,
) -> None:
    """fix(#1435 codex round 2): a directory's OWN mtime is bumped only by an
    entry being added/removed/renamed inside it, not by writes to an
    already-created file's contents — so it freezes at file-creation time
    while ogr2ogr keeps writing. A directory whose own mtime looks stale
    must still survive if a file inside it was written recently.
    """
    from app.core.runtime.staging import sweep_orphaned_exports

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    still_writing = exports_dir / "in-progress"
    still_writing.mkdir()
    output_file = still_writing / "export.gpkg"
    output_file.write_bytes(b"partial data")

    now = time.time()
    # The directory itself looks 2 hours old (created once, never touched
    # again), but the file inside it was written 30 seconds ago.
    os.utime(still_writing, (now - 2 * 3600, now - 2 * 3600))
    os.utime(output_file, (now - 30, now - 30))

    deleted, skipped = sweep_orphaned_exports(exports_dir)

    assert still_writing.exists(), (
        "a directory containing an actively-written file must survive even "
        "though the directory's own (frozen) mtime looks stale"
    )
    assert deleted == 0
    assert skipped == 1


def test_latest_mtime_falls_back_when_directory_cannot_be_listed() -> None:
    """fix(#1435 codex round 3): a directory that cannot be listed (e.g.
    root-owned residue left behind by a container UID change across a
    deploy) must not crash the sweep. Both boot-time callers
    (api/main.py, worker.py) invoke sweep_orphaned_exports with no
    exception guard of their own, so one unreadable entry would otherwise
    take down API/worker startup entirely.

    Mocked rather than exercised via real chmod bits: a test process
    running as root (common under Docker-based CI) bypasses Unix
    permission checks entirely, which would make a chmod-based test pass
    or fail depending on the runner's privilege level rather than on the
    fix.
    """
    from app.core.runtime.staging import _latest_mtime

    unreadable_dir = MagicMock()
    unreadable_dir.stat.return_value.st_mtime = 12345.0
    unreadable_dir.is_dir.return_value = True
    unreadable_dir.iterdir.side_effect = PermissionError("Permission denied")

    # Must not raise — falls back to the entry's own mtime, which needs no
    # permission on the directory's *contents* to obtain (only on its
    # parent, to reach the entry at all).
    assert _latest_mtime(unreadable_dir) == 12345.0


def test_periodic_sweep_still_catches_long_abandoned_residue(tmp_path: Path) -> None:
    """The wider periodic threshold still has a ceiling: residue from a
    process that died hours ago must not survive forever."""
    from app.api.main import _sweep_orphaned_exports_and_log

    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()

    abandoned = exports_dir / "long-dead"
    abandoned.mkdir()
    abandoned_file = abandoned / "export.gpkg"
    abandoned_file.write_bytes(b"x")
    now = time.time()
    os.utime(abandoned, (now - 5 * 3600, now - 5 * 3600))  # 5 hours old
    os.utime(abandoned_file, (now - 5 * 3600, now - 5 * 3600))

    log = structlog.get_logger("test")
    _sweep_orphaned_exports_and_log(exports_dir, log)
    assert not abandoned.exists(), (
        "a 5-hour-old entry is well past any legitimate export lifetime and "
        "must still be swept"
    )
