from pathlib import Path

import pytest

from app.config import settings
from app.export.service import export_dataset
from app.runtime.staging import StagingRuntimeError, ensure_staging_ready


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
        "app.runtime.staging._probe_writable_dir", _raise_permission_error
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
        target_srs: str | None = None,
        bbox: list[float] | None = None,
        where: str | None = None,
        format_key: str = "",
    ) -> None:
        # Simulate successful export by creating the output file.
        Path(output_path).write_text("export-data", encoding="utf-8")

    monkeypatch.setattr(
        "app.export.service.run_ogr2ogr_export", _fake_run_ogr2ogr_export
    )

    output_path, filename, media_type = await export_dataset(
        table_name="roads_2024",
        dataset_name="Roads 2024",
        format_key="gpkg",
        column_info=[{"name": "name", "type": "text"}],
    )

    output = Path(output_path)
    assert output.exists()
    assert output.read_text(encoding="utf-8") == "export-data"
    assert output.parent.parent == tmp_path / "exports"
    assert output.parent.name  # uuid-like directory created by export service
    assert filename == "Roads_2024.gpkg"
    assert media_type == "application/geopackage+sqlite3"
