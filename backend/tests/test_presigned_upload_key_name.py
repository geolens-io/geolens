"""Presigned upload doors key the staging object on the filename's basename."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.modules.catalog.datasets.api import router_reupload
from app.platform.jobs.models import IngestJob
from app.processing.ingest import router as ingest_router
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


class _SigningStorage:
    def __init__(self) -> None:
        self.signed: list[str] = []

    def generate_presigned_put_url(
        self, key: str, content_type: str, expiration: int = 3600
    ) -> str:
        self.signed.append(key)
        return f"https://s3.invalid/{key}?signed=1"


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> _SigningStorage:
    fake = _SigningStorage()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(ingest_router, "get_storage", lambda: fake)
    monkeypatch.setattr(router_reupload, "get_storage", lambda: fake)
    return fake


async def _reupload_url(session) -> str:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=admin_id, name="Presigned key name"
    )
    return f"/datasets/{dataset.id}/reupload/presigned"


@pytest.mark.parametrize("door", ["upload", "reupload"])
async def test_a_filename_with_directories_is_keyed_on_its_basename(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    storage: _SigningStorage,
    door: str,
) -> None:
    url = (
        "/ingest/upload/presigned"
        if door == "upload"
        else await _reupload_url(test_db_session)
    )

    resp = await client.post(
        url,
        json={"filename": "../../nested/dir/roads.geojson", "file_size": 10},
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["s3_key"] == f"staging/{body['job_id']}/roads.geojson"
    assert storage.signed[0].endswith(f"staging/{body['job_id']}/roads.geojson")


@pytest.mark.parametrize("filename", ["roads\x00.geojson", "bad\n/roads.geojson"])
@pytest.mark.parametrize("door", ["upload", "reupload"])
async def test_a_filename_with_a_control_character_is_refused_before_any_job(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    storage: _SigningStorage,
    door: str,
    filename: str,
) -> None:
    url = (
        "/ingest/upload/presigned"
        if door == "upload"
        else await _reupload_url(test_db_session)
    )
    before = (await test_db_session.execute(select(IngestJob.id))).scalars().all()

    resp = await client.post(
        url,
        json={"filename": filename, "file_size": 10},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "filename_control_characters"
    after = (await test_db_session.execute(select(IngestJob.id))).scalars().all()
    assert set(after) == set(before)
    assert storage.signed == []
