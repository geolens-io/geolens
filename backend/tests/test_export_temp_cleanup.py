"""fix(#435): a failed export must remove its own staging temp directory.

Pre-fix, `export_dataset()` created `<staging>/exports/<uuid>/` before running
ogr2ogr and attached cleanup only to a successful `FileResponse`. Every ogr2ogr
failure, ZIP failure, or client disconnect leaked a directory until some later
process startup swept it.
"""

from pathlib import Path

import pytest

from app.processing.export.ogr import ExportError


@pytest.fixture
def staging_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "app.processing.export.service.settings.upload_staging_dir", str(tmp_path)
    )
    return tmp_path


async def test_ogr_failure_removes_temp_dir(
    staging_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.processing.export import service

    async def _boom(*args, **kwargs):
        raise ExportError("ogr2ogr exited 1")

    monkeypatch.setattr(service, "run_ogr2ogr_export", _boom)

    with pytest.raises(ExportError):
        await service.export_dataset(
            "data_table", "My Dataset", "geojson", schema="data"
        )

    assert list((staging_root / "exports").iterdir()) == []


async def test_cancellation_removes_temp_dir(
    staging_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disconnecting client cancels the task; CancelledError is not an Exception."""
    from app.processing.export import service

    async def _cancelled(*args, **kwargs):
        raise __import__("asyncio").CancelledError()

    monkeypatch.setattr(service, "run_ogr2ogr_export", _cancelled)

    import asyncio

    with pytest.raises(asyncio.CancelledError):
        await service.export_dataset("data_table", "My Dataset", "gpkg", schema="data")

    assert list((staging_root / "exports").iterdir()) == []


async def test_zip_failure_removes_temp_dir(
    staging_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.processing.export import service

    async def _ok(*args, **kwargs):
        return None

    def _zip_boom(temp_dir: str, zip_path: str) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(service, "run_ogr2ogr_export", _ok)
    monkeypatch.setattr(service, "_zip_export_files", _zip_boom)

    with pytest.raises(OSError):
        await service.export_dataset("data_table", "My Dataset", "shp", schema="data")

    assert list((staging_root / "exports").iterdir()) == []


async def test_successful_export_keeps_its_file(
    staging_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The success path still hands a live path to the caller (no over-eager cleanup)."""
    from app.processing.export import service

    async def _write(table, output_path, driver, **kwargs):
        Path(output_path).write_text("{}")

    monkeypatch.setattr(service, "run_ogr2ogr_export", _write)

    path, filename, media_type = await service.export_dataset(
        "data_table", "My Dataset", "geojson", schema="data"
    )

    assert Path(path).exists()
    assert filename == "My_Dataset.geojson"
    assert media_type
