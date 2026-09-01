import os
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
    """A staging dir that does not exist yet (fresh boot) must not raise."""
    from app.core.runtime.staging import sweep_stale_gdal_header_files

    missing = tmp_path / "does-not-exist"
    assert sweep_stale_gdal_header_files(missing) == 0
