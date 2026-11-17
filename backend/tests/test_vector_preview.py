"""preview_vector_file maps preview refusals to the same 422s for the import and re-upload previews."""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from fastapi import HTTPException

from app.core.upload_errors import IngestCeilingError, UnsafeUploadError
from app.platform.vector_preview import preview_vector_file

pytestmark = pytest.mark.anyio

_CEILING = IngestCeilingError(
    "This file has 9 layers; the limit is 5.",
    code="too_many_layers",
    values={"limit": 5},
)


async def _run(preview, downloaded=None):
    return await preview_vector_file(
        preview,
        "/staged/file.gpkg",
        "roads",
        job_id=uuid.uuid4(),
        downloaded=downloaded,
    )


async def test_returns_the_preview_and_passes_the_layer(tmp_path):
    """A preview that succeeds is returned as read, with the caller's layer name."""
    preview = mock.AsyncMock(return_value={"columns": []})
    assert await _run(preview) == {"columns": []}
    preview.assert_awaited_once_with("/staged/file.gpkg", layer_name="roads")


@pytest.mark.parametrize(
    ("raised", "detail"),
    [
        (
            _CEILING,
            {
                "code": "too_many_layers",
                "message": "This file has 9 layers; the limit is 5.",
                "limit": 5,
            },
        ),
        (
            UnsafeUploadError("VRT files are not accepted.", code="vrt_refused"),
            {"code": "vrt_refused", "message": "VRT files are not accepted."},
        ),
        (
            RuntimeError("ogrinfo crashed"),
            {
                "code": "preview_failed",
                "message": "Unable to preview file. The file may be malformed or unsupported.",
            },
        ),
    ],
)
async def test_refusals_answer_422_with_their_detail(tmp_path, raised, detail):
    """A ceiling or content refusal keeps its coded detail; anything else is preview_failed; the local copy is removed."""
    downloaded = tmp_path / "copy.gpkg"
    downloaded.write_bytes(b"x")
    with pytest.raises(HTTPException) as caught:
        await _run(mock.AsyncMock(side_effect=raised), downloaded)
    assert caught.value.status_code == 422
    assert caught.value.detail == detail
    assert not downloaded.exists()


async def test_removes_the_local_copy_after_success(tmp_path):
    """The downloaded copy is removed once the preview has read it."""
    downloaded = tmp_path / "copy.gpkg"
    downloaded.write_bytes(b"x")
    await _run(mock.AsyncMock(return_value={}), downloaded)
    assert not downloaded.exists()


async def test_import_preview_passes_any_ceiling_refusal_through(
    client, admin_auth_header, test_db_session, tmp_path, monkeypatch
):
    """The import preview answers a ceiling refusal with its own code, as the re-upload preview does."""
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest import router
    from tests.factories import get_user_id

    p = tmp_path / "layers.geojson"
    p.write_text('{"type":"FeatureCollection","features":[]}')
    job = IngestJob(
        source_filename="layers.geojson",
        file_path=str(p),
        created_by=await get_user_id(test_db_session, "admin"),
        status="pending",
        user_metadata={"file_type": "vector"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    monkeypatch.setattr(
        router, "run_ogrinfo_preview", mock.AsyncMock(side_effect=_CEILING)
    )

    response = await client.post(f"/ingest/preview/{job.id}", headers=admin_auth_header)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "too_many_layers"
