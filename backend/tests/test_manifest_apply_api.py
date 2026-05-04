import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestApplyResponse,
)


def valid_manifest_payload() -> dict:
    return {
        "manifest_version": "1",
        "catalog": {
            "title": "City mobility catalog",
            "description": "Public transportation and street network datasets.",
            "organization": "City GIS Office",
        },
        "datasets": [
            {
                "key": "roads",
                "title": "Road centerlines",
                "description": "Local road centerline geometry.",
                "sources": [
                    {
                        "type": "vector",
                        "uri": "./data/roads.geojson",
                        "format": "geojson",
                    }
                ],
                "metadata": {
                    "tags": ["transportation", "roads"],
                    "organization": "City GIS Office",
                    "crs": "EPSG:4326",
                    "license": "CC-BY-4.0",
                    "attribution": "City GIS Office",
                    "bbox": [-74.1, 40.5, -73.7, 40.9],
                },
                "publication": {"intent": "draft"},
            }
        ],
    }


class TestManifestApplySchemas:
    def test_accepts_vector_fixture_shaped_payload(self):
        request = ManifestApplyRequest.model_validate(valid_manifest_payload())

        assert request.manifest_version == "1"
        assert request.dry_run is False
        assert request.catalog.title == "City mobility catalog"
        assert request.datasets[0].key == "roads"
        assert request.datasets[0].sources[0].type == "vector"

    def test_accepts_raster_cog_fixture_shaped_payload(self):
        payload = valid_manifest_payload()
        dataset = payload["datasets"][0]
        dataset["key"] = "naip-2025-tile-001"
        dataset["sources"][0]["type"] = "raster_cog"
        dataset["sources"][0]["uri"] = (
            "s3://example-geolens-public/rasters/naip-2025-tile-001.tif"
        )
        dataset["publication"]["intent"] = "published"

        request = ManifestApplyRequest.model_validate(payload)

        assert request.datasets[0].sources[0].type == "raster_cog"
        assert request.datasets[0].publication.intent == "published"

    def test_accepts_vrt_fixture_shaped_payload(self):
        payload = valid_manifest_payload()
        dataset = payload["datasets"][0]
        dataset["key"] = "flood-depth-mosaic"
        dataset["sources"][0]["type"] = "vrt"
        dataset["sources"][0]["uri"] = "./rasters/flood-depth-mosaic.vrt"
        dataset["publication"]["intent"] = "internal"

        request = ManifestApplyRequest.model_validate(payload)

        assert request.datasets[0].sources[0].type == "vrt"
        assert request.datasets[0].publication.intent == "internal"

    def test_rejects_bad_version(self):
        payload = valid_manifest_payload()
        payload["manifest_version"] = "2"

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "manifest_version" in str(exc.value)

    def test_rejects_duplicate_dataset_keys(self):
        payload = valid_manifest_payload()
        payload["datasets"].append(dict(payload["datasets"][0]))

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "duplicate dataset key" in str(exc.value)
        assert "roads" in str(exc.value)

    def test_rejects_unsupported_source_type(self):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0]["type"] = "wms"

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "vector" in str(exc.value)
        assert "raster_cog" in str(exc.value)
        assert "vrt" in str(exc.value)

    def test_rejects_unsupported_publication_intent(self):
        payload = valid_manifest_payload()
        payload["datasets"][0]["publication"]["intent"] = "external"

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "draft" in str(exc.value)
        assert "published" in str(exc.value)


class TestManifestApplyEndpoint:
    async def test_valid_request_delegates_to_manifest_service(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        dataset_id = uuid.uuid4()
        payload = valid_manifest_payload()
        expected_response = ManifestApplyResponse(
            accepted=True,
            dry_run=False,
            results=[
                ManifestApplyEntryResult(
                    dataset_key="roads",
                    action="create",
                    dataset_id=dataset_id,
                    message="created roads",
                )
            ],
        )

        with (
            patch(
                "app.processing.ingest.manifest_service.apply_manifest",
                new_callable=AsyncMock,
                return_value=expected_response,
            ) as mock_apply,
            patch(
                "app.processing.ingest.router.create_ingest_job",
                new_callable=AsyncMock,
            ) as mock_create_job,
            patch(
                "app.processing.ingest.router.save_upload_file",
                new_callable=AsyncMock,
            ) as mock_save_upload,
            patch(
                "app.processing.ingest.router.run_ogrinfo_preview",
                new_callable=AsyncMock,
            ) as mock_preview,
            patch(
                "app.processing.ingest.router.queue_ingest_job",
                new_callable=AsyncMock,
            ) as mock_queue_job,
        ):
            resp = await client.post(
                "/ingest/manifest/apply",
                json=payload,
                headers=editor_auth_header,
            )

        assert resp.status_code == 200
        assert resp.json() == {
            "accepted": True,
            "dry_run": False,
            "results": [
                {
                    "dataset_key": "roads",
                    "action": "create",
                    "job_id": None,
                    "dataset_id": str(dataset_id),
                    "message": "created roads",
                    "errors": [],
                }
            ],
        }
        mock_apply.assert_awaited_once()
        _, request, user = mock_apply.await_args.args
        assert isinstance(request, ManifestApplyRequest)
        assert request.datasets[0].key == "roads"
        assert user.username.startswith("editor_")
        mock_create_job.assert_not_awaited()
        mock_save_upload.assert_not_awaited()
        mock_preview.assert_not_awaited()
        mock_queue_job.assert_not_awaited()

    async def test_requires_authentication(self, client: AsyncClient):
        with patch(
            "app.processing.ingest.manifest_service.apply_manifest",
            new_callable=AsyncMock,
        ) as mock_apply:
            resp = await client.post(
                "/ingest/manifest/apply",
                json=valid_manifest_payload(),
            )

        assert resp.status_code == 401
        mock_apply.assert_not_awaited()

    async def test_requires_upload_permission(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        with patch(
            "app.processing.ingest.manifest_service.apply_manifest",
            new_callable=AsyncMock,
        ) as mock_apply:
            resp = await client.post(
                "/ingest/manifest/apply",
                json=valid_manifest_payload(),
                headers=viewer_auth_header,
            )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Missing permission: upload"
        mock_apply.assert_not_awaited()

    async def test_invalid_payload_returns_422_before_service(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0]["type"] = "wms"

        with patch(
            "app.processing.ingest.manifest_service.apply_manifest",
            new_callable=AsyncMock,
        ) as mock_apply:
            resp = await client.post(
                "/ingest/manifest/apply",
                json=payload,
                headers=editor_auth_header,
            )

        assert resp.status_code == 422
        assert "body.datasets.0.sources.0.type" in resp.text
        mock_apply.assert_not_awaited()
