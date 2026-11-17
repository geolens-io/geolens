"""Cold export conversions are capped per process and shed with a retry."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app.processing.export.ogr import FORMAT_MAP, ExportError

from tests.factories import create_dataset, get_user_id


async def _dataset(session, name: str):
    admin_id = await get_user_id(session, "admin")
    return await create_dataset(
        session, created_by=admin_id, name=name, visibility="public"
    )


def _fake_export(tmp_path, gate: asyncio.Event | None = None, fail: bool = False):
    async def _export(table_name, dataset_name, format_key, *, schema, **kwargs):
        if gate is not None:
            await gate.wait()
        if fail:
            raise ExportError("boom")
        out_dir = tmp_path / uuid.uuid4().hex
        out_dir.mkdir()
        path = out_dir / f"{dataset_name}.gpkg"
        path.write_bytes(b"mock export data")
        return str(path), path.name, FORMAT_MAP["gpkg"]["media"]

    return _export


@pytest.mark.anyio
async def test_conversion_overflow_gets_429_with_retry_after(
    client: AsyncClient, test_db_session, monkeypatch, tmp_path
):
    first = await _dataset(test_db_session, "ExportCapOne")
    second = await _dataset(test_db_session, "ExportCapTwo")
    gate = asyncio.Event()
    monkeypatch.setattr(
        "app.processing.export.router._conversion_slots", asyncio.Semaphore(1)
    )
    monkeypatch.setattr(
        "app.processing.export.selection.export_dataset", _fake_export(tmp_path, gate)
    )

    running = asyncio.create_task(
        client.get(f"/datasets/{first.id}/export", params={"format": "gpkg"})
    )
    await asyncio.sleep(0.5)
    shed = await client.get(f"/datasets/{second.id}/export", params={"format": "gpkg"})
    assert shed.status_code == 429
    assert int(shed.headers["retry-after"]) > 0

    gate.set()
    assert (await running).status_code == 200
    retry = await client.get(f"/datasets/{second.id}/export", params={"format": "gpkg"})
    assert retry.status_code == 200


@pytest.mark.anyio
async def test_failed_conversion_releases_its_slot(
    client: AsyncClient, test_db_session, monkeypatch, tmp_path
):
    ds = await _dataset(test_db_session, "ExportCapFail")
    slots = asyncio.Semaphore(1)
    monkeypatch.setattr("app.processing.export.router._conversion_slots", slots)
    monkeypatch.setattr(
        "app.processing.export.selection.export_dataset",
        _fake_export(tmp_path, fail=True),
    )

    resp = await client.get(f"/datasets/{ds.id}/export", params={"format": "gpkg"})
    assert resp.status_code == 500
    assert not slots.locked()
