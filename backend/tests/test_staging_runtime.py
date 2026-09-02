import os
import stat
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.processing.export.service import export_dataset
from app.core.runtime.staging import StagingRuntimeError, ensure_staging_ready


def test_ensure_staging_ready_creates_directory_and_probe_file(tmp_path: Path) -> None:
    staging_dir = tmp_path / "nested" / "staging"

    ready_path = ensure_staging_ready(staging_dir)

    assert ready_path == staging_dir
    assert staging_dir.exists()
    assert staging_dir.is_dir()
    # Probe verifies write + delete; this extra write confirms path is usable.
    marker_file = staging_dir / "marker.txt"
    marker_file.write_text("ok", encoding="utf-8")
    assert marker_file.read_text(encoding="utf-8") == "ok"


def test_ensure_staging_ready_raises_with_failing_path_on_probe_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    failing_dir = tmp_path / "staging"

    def _raise_permission_error(directory: str | Path) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(
        "app.core.runtime.staging._probe_writable_dir", _raise_permission_error
    )

    with pytest.raises(StagingRuntimeError) as exc_info:
        ensure_staging_ready(failing_dir)

    message = str(exc_info.value)
    assert f"'{failing_dir}'" in message
    assert "directory is not writable" in message
    assert "UPLOAD_STAGING_DIR" in message


def test_ensure_staging_ready_raises_with_failing_path_on_mkdir_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    failing_dir = tmp_path / "readonly" / "staging"
    original_mkdir = Path.mkdir

    def _raise_permission_error(
        self: Path, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if self == failing_dir:
            raise PermissionError("read-only filesystem")
        original_mkdir(self, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", _raise_permission_error)

    with pytest.raises(StagingRuntimeError) as exc_info:
        ensure_staging_ready(failing_dir)

    message = str(exc_info.value)
    assert f"'{failing_dir}'" in message
    assert "unable to create directory" in message


@pytest.mark.anyio
async def test_export_dataset_creates_temp_dir_after_staging_guard_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))

    async def _fake_run_ogr2ogr_export(
        table_name: str,
        output_path: str,
        driver: str,
        *,
        schema: str,
        target_srs: str | None = None,
        bbox: list[float] | None = None,
        where: str | None = None,
        format_key: str = "",
        pmtiles_maxzoom: int | None = None,
        deadline: float | None = None,
    ) -> None:
        # Simulate successful export by creating the output file.
        Path(output_path).write_text("export-data", encoding="utf-8")

    monkeypatch.setattr(
        "app.processing.export.service.run_ogr2ogr_export", _fake_run_ogr2ogr_export
    )

    output_path, filename, media_type = await export_dataset(
        table_name="roads_2024",
        dataset_name="Roads 2024",
        format_key="gpkg",
        schema="data",
        column_info=[{"name": "name", "type": "text"}],
    )

    output = Path(output_path)
    assert output.exists()
    assert output.read_text(encoding="utf-8") == "export-data"
    assert output.parent.parent == tmp_path / "exports"
    assert output.parent.name  # uuid-like directory created by export service
    assert filename == "Roads_2024.gpkg"
    assert media_type == "application/geopackage+sqlite3"


def test_sweep_stale_gdal_header_files_removes_only_old_matching_files(
    tmp_path: Path,
) -> None:
    """fix(#1746): only ``gdal_auth_*.hdr`` files older than ``max_age_seconds``
    are removed. A fresh header file (still owned by a running ogr2ogr
    subprocess) and a non-matching old file both survive.
    """
    from app.core.runtime.staging import sweep_stale_gdal_header_files

    fresh_header = tmp_path / "gdal_auth_abc123.hdr"
    fresh_header.write_text("Authorization: Bearer x\n", encoding="utf-8")

    stale_header = tmp_path / "gdal_auth_def456.hdr"
    stale_header.write_text("Authorization: Bearer y\n", encoding="utf-8")

    other_old_file = tmp_path / "some_other_file.tmp"
    other_old_file.write_text("unrelated", encoding="utf-8")

    now = time.time()
    # fresh_header stays at "now" (just written, well within the window).
    os.utime(stale_header, (now - 2 * 3600, now - 2 * 3600))  # 2 hours old
    os.utime(other_old_file, (now - 2 * 3600, now - 2 * 3600))  # 2 hours old

    removed = sweep_stale_gdal_header_files(tmp_path, max_age_seconds=3600)

    assert removed == 1
    assert fresh_header.exists(), "a fresh header file must survive"
    assert not stale_header.exists(), "a 2-hour-old header file must be swept"
    assert other_old_file.exists(), (
        "a non-matching old file must survive — the sweep only ever touches "
        "gdal_auth_*.hdr"
    )


def test_sweep_stale_gdal_header_files_missing_dir_is_a_noop(tmp_path: Path) -> None:
    """A header dir that does not exist yet (fresh boot) must not raise."""
    from app.core.runtime.staging import sweep_stale_gdal_header_files

    missing = tmp_path / "does-not-exist"
    assert sweep_stale_gdal_header_files(missing) == 0


def test_sweep_stale_gdal_header_files_defaults_without_provisioning(
    tmp_path: Path, monkeypatch
) -> None:
    """fix(#1746 codex r2): the no-argument form reads GDAL_HEADER_DIR and
    never creates it.

    Both boot hooks and the API's periodic pass call it with no argument. It
    must not leave an empty 0700 directory behind on every install that never
    fetches a protected WFS/OGC layer — reclamation is not provisioning.
    """
    from app.core.runtime import staging as staging_runtime

    missing = tmp_path / "never-created"
    monkeypatch.setattr(staging_runtime, "GDAL_HEADER_DIR", missing)

    assert staging_runtime.sweep_stale_gdal_header_files() == 0
    assert not missing.exists()

    # And it does read the constant rather than a snapshot: a stale header in
    # the redirected directory is swept by the same no-argument call.
    missing.mkdir()
    stale = missing / "gdal_auth_zzz.hdr"
    stale.write_text("Authorization: Bearer z\n", encoding="utf-8")
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))

    assert staging_runtime.sweep_stale_gdal_header_files() == 1
    assert not stale.exists()


def test_gdal_header_dir_is_on_the_container_tmpfs_not_the_backed_up_volume(
    tmp_path: Path, monkeypatch
) -> None:
    """fix(#1746 codex r2): the bearer-header directory is /tmp, mode 0700.

    Two properties, and they fail for different reasons. It must be under /tmp,
    because the api and the worker each mount that as their own 512m tmpfs —
    private to the container, emptied on restart, and never read by
    ``scripts/backup-entrypoint.sh``. And it must NOT be under
    ``upload_staging_dir``, which is a persistent volume that script tars every
    cycle, so a header orphaned by a SIGKILL before the unlink could be
    archived into a backup. The mode is asserted because the file inside is a
    credential and the container's /tmp is 1777.
    """
    from app.core.config import settings
    from app.core.runtime import staging as staging_runtime

    # The real constant, asserted as a path only — creating /tmp/gdal-auth from
    # a test would be the exact pollution the fixtures elsewhere avoid.
    real = staging_runtime.GDAL_HEADER_DIR
    assert real == Path("/tmp/gdal-auth")
    assert str(real).startswith("/tmp/")
    assert not str(real).startswith(str(Path(settings.upload_staging_dir)))

    # Behaviour is exercised against a redirected constant, the same way every
    # test that touches the header branch does.
    redirected = tmp_path / "gdal-auth"
    monkeypatch.setattr(staging_runtime, "GDAL_HEADER_DIR", redirected)
    created = staging_runtime.gdal_header_dir()
    assert created == redirected
    assert created.is_dir()
    assert stat.S_IMODE(created.stat().st_mode) == 0o700

    # Idempotent, and it tightens a directory that already existed too loose —
    # /tmp is world-writable, so "already there" is not "already ours".
    created.chmod(0o755)
    assert staging_runtime.gdal_header_dir() == redirected
    assert stat.S_IMODE(redirected.stat().st_mode) == 0o700
