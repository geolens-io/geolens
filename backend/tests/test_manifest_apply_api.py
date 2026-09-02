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

    def test_rejects_standalone_vrt_at_schema_validation(self):
        payload = valid_manifest_payload()
        dataset = payload["datasets"][0]
        dataset["key"] = "flood-depth-mosaic"
        dataset["sources"][0]["type"] = "vrt"
        dataset["sources"][0]["uri"] = "./rasters/flood-depth-mosaic.vrt"
        dataset["publication"]["intent"] = "internal"

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "sources.0.type" in str(exc.value)
        assert "vrt" in str(exc.value)

    @pytest.mark.parametrize(
        "extension",
        [".fgb", ".kml", ".kmz", ".zip"],
    )
    def test_accepts_tier1_vector_extensions(self, extension: str):
        """fix(#1683): manifest sources now accept the same four tier-1
        vector formats the upload/reupload doors accepted as of #1682
        (FlatGeobuf, KML, KMZ, and a zipped File Geodatabase — the last one
        already matched the pre-existing `.zip` entry)."""
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0]["uri"] = f"./data/roads{extension}"
        del payload["datasets"][0]["sources"][0]["format"]

        request = ManifestApplyRequest.model_validate(payload)

        assert request.datasets[0].sources[0].uri == f"./data/roads{extension}"

    def test_accepts_a_well_formed_checksum(self):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0]["checksum"] = f"sha256:{'a' * 64}"

        request = ManifestApplyRequest.model_validate(payload)

        assert request.datasets[0].sources[0].checksum == f"sha256:{'a' * 64}"

    def test_omitted_checksum_defaults_to_none(self):
        request = ManifestApplyRequest.model_validate(valid_manifest_payload())

        assert request.datasets[0].sources[0].checksum is None

    @pytest.mark.parametrize(
        "checksum",
        [
            "sha256:" + "a" * 63,  # too short
            "sha256:" + "a" * 65,  # too long
            "sha256:" + "A" * 64,  # uppercase hex is rejected, not normalized
            "sha256:" + "g" * 64,  # not hex
            "md5:" + "a" * 32,  # wrong algorithm prefix
            "a" * 64,  # missing algorithm prefix entirely
            "sha256:",
            "",
        ],
    )
    def test_rejects_malformed_checksum_shapes(self, checksum: str):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0]["checksum"] = checksum

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "checksum" in str(exc.value)

    @pytest.mark.parametrize(
        ("source_type", "uri", "expected"),
        [
            ("vector", "./rasters/tile.tif", "requires one of"),
            ("raster_cog", "./data/roads.geojson", "requires one of"),
            ("raster_cog", "./rasters/mosaic.vrt", "Standalone VRT"),
            # fix(#1683): the new tier-1 vector formats are vector-only —
            # keep the mismatch check symmetric with the pre-existing ones.
            ("raster_cog", "./data/roads.fgb", "requires one of"),
            ("raster_cog", "./data/roads.kml", "requires one of"),
            ("raster_cog", "./data/roads.kmz", "requires one of"),
        ],
    )
    def test_rejects_source_type_extension_mismatch(
        self, source_type: str, uri: str, expected: str
    ):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0].update({"type": source_type, "uri": uri})

        with pytest.raises(ValidationError, match=expected):
            ManifestApplyRequest.model_validate(payload)

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

    def test_rejects_multiple_sources_until_manifest_supports_them(self):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"].append(
            {
                "type": "vector",
                "uri": "https://example.test/secondary.geojson",
                "format": "geojson",
            }
        )

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "sources" in str(exc.value)
        assert "at most 1 item" in str(exc.value)

    def test_rejects_unsupported_source_type(self):
        payload = valid_manifest_payload()
        payload["datasets"][0]["sources"][0]["type"] = "wms"

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "vector" in str(exc.value)
        assert "raster_cog" in str(exc.value)

    def test_rejects_unbounded_dataset_batch(self):
        payload = valid_manifest_payload()
        template = payload["datasets"][0]
        payload["datasets"] = [
            {
                **template,
                "key": f"roads-{index}",
            }
            for index in range(101)
        ]

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "datasets" in str(exc.value)
        assert "at most 100 items" in str(exc.value)

    def test_publication_intent_is_not_pinned_to_an_enum(self):
        """fix(#1201): the request schema cannot know the live status set.

        An intent is a catalog record_status, and those come from the workflow
        extension's status_order() (#1183) — an enum here rejected an
        overlay-defined status the API itself accepts. The live set is checked
        at apply time; the schema keeps only the shape bounds.
        """
        payload = valid_manifest_payload()
        payload["datasets"][0]["publication"]["intent"] = "approval_required"

        request = ManifestApplyRequest.model_validate(payload)

        assert request.datasets[0].publication.intent == "approval_required"

    @pytest.mark.parametrize("intent", ["", "x" * 21])
    def test_rejects_publication_intent_outside_the_record_status_bounds(
        self, intent: str
    ):
        payload = valid_manifest_payload()
        payload["datasets"][0]["publication"]["intent"] = intent

        with pytest.raises(ValidationError) as exc:
            ManifestApplyRequest.model_validate(payload)

        assert "publication.intent" in str(exc.value)


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
        _, request, user, http_request = mock_apply.await_args.args
        assert isinstance(request, ManifestApplyRequest)
        assert request.datasets[0].key == "roads"
        assert user.username.startswith("editor_")
        assert http_request.url.path == "/ingest/manifest/apply"
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
