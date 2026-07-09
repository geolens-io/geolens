from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import ManifestApplyRequest, ManifestDataset
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from app.processing.ingest.tasks_raster import create_raster_dataset
from app.processing.ingest.tasks_vrt import create_vrt_dataset
from tests.factories import create_dataset


def _dataset_payload(
    *,
    key: str,
    title: str,
    source_type: str = "vector",
    uri: str = "tests/fixtures/ingest/basic_attrs.geojson",
    intent: str = "published",
    crs: str = "EPSG:4326",
) -> dict:
    source_format = {
        "vector": "geojson",
        "raster_cog": "cog",
        "vrt": "vrt",
    }[source_type]
    return {
        "key": key,
        "title": title,
        "description": f"{title} manifest description",
        "sources": [
            {
                "type": source_type,
                "uri": uri,
                "format": source_format,
            }
        ],
        "metadata": {
            "tags": ["manifest", source_type],
            "organization": "Manifest QA",
            "crs": crs,
            "license": "CC-BY-4.0",
            "attribution": "Manifest QA",
        },
        "publication": {"intent": intent},
    }


def _manifest_payload(*datasets: dict, dry_run: bool = False) -> dict:
    return {
        "manifest_version": "1",
        "catalog": {
            "title": "Round-trip manifest catalog",
            "organization": "Manifest QA",
        },
        "datasets": list(datasets),
        "dry_run": dry_run,
    }


async def _admin_user(session) -> User:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one()


async def _create_completed_manifest_job(
    session,
    *,
    user: User,
    dataset: Dataset,
    manifest_dataset: ManifestDataset,
) -> IngestJob:
    prepared = await classify_manifest_source(manifest_dataset.sources[0])
    fingerprint = manifest_dataset_fingerprint(manifest_dataset)
    job = IngestJob(
        dataset_id=dataset.id,
        source_filename=prepared.source_filename,
        file_path=prepared.file_path,
        created_by=user.id,
        status="complete",
        completed_at=datetime.now(timezone.utc),
        user_metadata=manifest_job_metadata(
            manifest_dataset,
            prepared,
            fingerprint=fingerprint,
        ),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def _actions_by_key(response_json: dict) -> dict[str, dict]:
    return {entry["dataset_key"]: entry for entry in response_json["results"]}


async def _assert_search_discovers_dataset(
    client: AsyncClient,
    headers: dict,
    *,
    dataset: Dataset,
    query: str,
    record_type: str,
) -> None:
    response = await client.get(
        "/search/datasets/",
        params={"q": query, "limit": 10},
        headers=headers,
    )

    assert response.status_code == 200
    features = response.json()["features"]
    feature = next(item for item in features if item["id"] == str(dataset.id))
    assert feature["properties"]["title"] == query
    assert feature["properties"]["record_type"] == record_type
    assert feature["properties"]["record_status"] == "published"


class TestManifestApplyEndpointRoundTrip:
    async def test_endpoint_routes_vector_raster_and_vrt_entries_to_existing_queue(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
        clean_tables,
    ):
        payload = _manifest_payload(
            _dataset_payload(
                key="roundtrip-vector-create",
                title="Roundtrip Vector Create",
                source_type="vector",
                uri="tests/fixtures/ingest/basic_attrs.geojson",
                intent="ready",
            ),
            _dataset_payload(
                key="roundtrip-raster-create",
                title="Roundtrip Raster Create",
                source_type="raster_cog",
                uri="rasters/roundtrip-raster.tif",
                intent="published",
                crs="EPSG:3857",
            ),
            _dataset_payload(
                key="roundtrip-vrt-create",
                title="Roundtrip VRT Create",
                source_type="vrt",
                uri="rasters/roundtrip-mosaic.vrt",
                intent="internal",
            ),
        )

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await client.post(
                "/ingest/manifest/apply",
                json=payload,
                headers=editor_auth_header,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["dry_run"] is False
        actions = _actions_by_key(body)
        assert {key: value["action"] for key, value in actions.items()} == {
            "roundtrip-vector-create": "create",
            "roundtrip-raster-create": "create",
            "roundtrip-vrt-create": "create",
        }
        assert queue.await_count == 3

        jobs = (
            (
                await test_db_session.execute(
                    select(IngestJob).where(
                        IngestJob.id.in_(
                            [uuid.UUID(entry["job_id"]) for entry in actions.values()]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        jobs_by_key = {job.user_metadata["manifest_key"]: job for job in jobs}

        vector_job = jobs_by_key["roundtrip-vector-create"]
        raster_job = jobs_by_key["roundtrip-raster-create"]
        vrt_job = jobs_by_key["roundtrip-vrt-create"]

        assert vector_job.user_metadata["manifest_source_type"] == "vector"
        assert vector_job.user_metadata["visibility"] == "private"
        assert vector_job.user_metadata["record_status"] == "ready"
        assert "file_type" not in vector_job.user_metadata

        assert raster_job.user_metadata["manifest_source_type"] == "raster_cog"
        assert raster_job.user_metadata["file_type"] == "raster"
        assert raster_job.user_metadata["visibility"] == "public"
        assert raster_job.user_metadata["record_status"] == "published"
        assert raster_job.user_metadata["srid_override"] == 3857

        assert vrt_job.user_metadata["manifest_source_type"] == "vrt"
        assert vrt_job.user_metadata["file_type"] == "raster"
        assert vrt_job.file_path == "rasters/roundtrip-mosaic.vrt"
        assert vrt_job.user_metadata["visibility"] == "internal"
        assert vrt_job.user_metadata["record_status"] == "internal"

    async def test_endpoint_dry_run_does_not_write_or_defer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        clean_tables,
    ):
        # fix(#430 BA-02): the caller must OWN the manifest-managed datasets, else the
        # write-access gate now (correctly) denies the update. This test exercises
        # dry-run side-effect-freeness, not cross-user authz — so run it as the
        # owner (admin). The cross-user denial has its own test below.
        user = await _admin_user(test_db_session)
        skip_payload = _dataset_payload(
            key="roundtrip-dry-skip",
            title="Roundtrip Dry Skip",
        )
        update_original_payload = _dataset_payload(
            key="roundtrip-dry-update",
            title="Roundtrip Dry Original",
        )
        update_changed_payload = _dataset_payload(
            key="roundtrip-dry-update",
            title="Roundtrip Dry Changed",
        )
        skip_request = ManifestApplyRequest.model_validate(
            _manifest_payload(skip_payload)
        )
        update_original_request = ManifestApplyRequest.model_validate(
            _manifest_payload(update_original_payload)
        )
        skip_dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Roundtrip Dry Skip",
        )
        update_dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Roundtrip Dry Original",
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=skip_dataset,
            manifest_dataset=skip_request.datasets[0],
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=update_dataset,
            manifest_dataset=update_original_request.datasets[0],
        )
        before_jobs = await test_db_session.scalar(select(func.count(IngestJob.id)))
        before_record = await test_db_session.get(Record, update_dataset.record_id)
        assert before_record is not None
        before_title = before_record.title

        with (
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
            patch("app.processing.ingest.manifest_service.get_catalog_port") as port,
        ):
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest_payload(
                    _dataset_payload(
                        key="roundtrip-dry-create",
                        title="Roundtrip Dry Create",
                    ),
                    update_changed_payload,
                    skip_payload,
                    dry_run=True,
                ),
                headers=admin_auth_header,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["dry_run"] is True
        actions = _actions_by_key(body)
        assert {key: value["action"] for key, value in actions.items()} == {
            "roundtrip-dry-create": "create",
            "roundtrip-dry-update": "update",
            "roundtrip-dry-skip": "skip",
        }
        assert actions["roundtrip-dry-create"]["job_id"] is None
        assert actions["roundtrip-dry-update"]["job_id"] is None
        assert actions["roundtrip-dry-update"]["dataset_id"] == str(update_dataset.id)
        assert actions["roundtrip-dry-skip"]["dataset_id"] == str(skip_dataset.id)
        queue.assert_not_awaited()
        port.assert_not_called()

        after_jobs = await test_db_session.scalar(select(func.count(IngestJob.id)))
        after_record = await test_db_session.get(Record, update_dataset.record_id)
        assert after_jobs == before_jobs
        assert after_record is not None
        assert after_record.title == before_title

    async def test_manifest_update_over_other_users_dataset_is_denied(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
        clean_tables,
    ):
        """fix(#430 BA-02): an editor cannot overwrite another user's manifest-managed
        dataset, and dry_run must not leak that dataset's UUID (a pre-write oracle)."""
        owner = await _admin_user(test_db_session)
        original_payload = _dataset_payload(
            key="cross-user-update", title="Owner Original"
        )
        changed_payload = _dataset_payload(
            key="cross-user-update", title="Attacker Changed"
        )
        original_request = ManifestApplyRequest.model_validate(
            _manifest_payload(original_payload)
        )
        victim_dataset = await create_dataset(
            test_db_session, created_by=owner.id, name="Owner Original"
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=owner,
            dataset=victim_dataset,
            manifest_dataset=original_request.datasets[0],
        )
        before_title = (
            await test_db_session.get(Record, victim_dataset.record_id)
        ).title

        for dry_run in (True, False):
            with patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue:
                response = await client.post(
                    "/ingest/manifest/apply",
                    json=_manifest_payload(changed_payload, dry_run=dry_run),
                    headers=editor_auth_header,
                )
            assert response.status_code == 200
            actions = _actions_by_key(response.json())
            entry = actions["cross-user-update"]
            assert entry["action"] == "error"
            # UUID oracle closed: the victim's dataset id must not be disclosed.
            assert entry.get("dataset_id") is None
            queue.assert_not_awaited()

        # The victim's data was never touched.
        after_record = await test_db_session.get(Record, victim_dataset.record_id)
        assert after_record.title == before_title

    async def test_manifest_update_by_nonadmin_owner_classifies_as_update(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
        clean_tables,
    ):
        """fix(#430 codex r10, refuted): the BA-02 write gate dereferences
        dataset.record synchronously, which is only safe because the
        Dataset.record relationship is lazy='joined' (models.py) — the
        completed-manifest-job query has no explicit eager-load of its own.
        Nothing pinned the legitimate NON-admin owner update path: the admin
        dry-run test short-circuits before touching record, and the
        cross-user test asserts an error entry. If the model-level eager
        load is ever weakened, this test catches the MissingGreenlet."""
        me = await client.get("/auth/me/", headers=editor_auth_header)
        assert me.status_code == 200
        owner = await test_db_session.get(User, uuid.UUID(me.json()["id"]))
        original = _dataset_payload(key="owner-update", title="Owner Original")
        changed = _dataset_payload(key="owner-update", title="Owner Changed")
        original_request = ManifestApplyRequest.model_validate(
            _manifest_payload(original)
        )
        dataset = await create_dataset(
            test_db_session, created_by=owner.id, name="Owner Original"
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=owner,
            dataset=dataset,
            manifest_dataset=original_request.datasets[0],
        )

        response = await client.post(
            "/ingest/manifest/apply",
            json=_manifest_payload(changed, dry_run=True),
            headers=editor_auth_header,
        )
        assert response.status_code == 200
        entry = _actions_by_key(response.json())["owner-update"]
        assert entry["action"] == "update", entry
        assert entry["dataset_id"] == str(dataset.id)

        # fix(#430 codex r15): the OWNER's same-fingerprint submit still
        # returns the skip entry WITH ids (the new skip gates only bite
        # non-owners).
        skip_response = await client.post(
            "/ingest/manifest/apply",
            json=_manifest_payload(original, dry_run=True),
            headers=editor_auth_header,
        )
        assert skip_response.status_code == 200
        skip_entry = _actions_by_key(skip_response.json())["owner-update"]
        assert skip_entry["action"] == "skip", skip_entry
        assert skip_entry["dataset_id"] == str(dataset.id)

    async def test_manifest_skip_paths_hide_other_users_ids(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
        clean_tables,
    ):
        """fix(#430 codex r15): submitting a manifest whose key+fingerprint
        matches ANOTHER user's completed or in-flight job previously returned
        that user's job/dataset UUIDs in a 'skip' entry — the same
        enumeration oracle BA-02 closed on the update path. Both skip paths
        now yield an error entry with no ids for non-owners."""
        owner = await _admin_user(test_db_session)

        # -- skip_complete: victim has a COMPLETED job for this key --
        complete_payload = _dataset_payload(
            key="cross-user-skip-complete", title="Victim Complete"
        )
        complete_request = ManifestApplyRequest.model_validate(
            _manifest_payload(complete_payload)
        )
        victim_dataset = await create_dataset(
            test_db_session, created_by=owner.id, name="Victim Complete"
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=owner,
            dataset=victim_dataset,
            manifest_dataset=complete_request.datasets[0],
        )

        # -- skip_in_flight: victim has a PENDING job for this key --
        inflight_payload = _dataset_payload(
            key="cross-user-skip-inflight", title="Victim Inflight"
        )
        inflight_request = ManifestApplyRequest.model_validate(
            _manifest_payload(inflight_payload)
        )
        inflight_ds = inflight_request.datasets[0]
        prepared = await classify_manifest_source(inflight_ds.sources[0])
        test_db_session.add(
            IngestJob(
                dataset_id=None,
                source_filename=prepared.source_filename,
                file_path=prepared.file_path,
                created_by=owner.id,
                status="pending",
                user_metadata=manifest_job_metadata(
                    inflight_ds,
                    prepared,
                    fingerprint=manifest_dataset_fingerprint(inflight_ds),
                ),
            )
        )
        await test_db_session.commit()

        for dry_run in (True, False):
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest_payload(
                    complete_payload, inflight_payload, dry_run=dry_run
                ),
                headers=editor_auth_header,
            )
            assert response.status_code == 200
            actions = _actions_by_key(response.json())
            for key in ("cross-user-skip-complete", "cross-user-skip-inflight"):
                entry = actions[key]
                assert entry["action"] == "error", entry
                assert entry.get("dataset_id") is None
                assert entry.get("job_id") is None


class TestManifestCompletedDatasetRoundTrip:
    async def test_completed_manifest_datasets_are_searchable_and_previewable(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        clean_tables,
    ):
        user = await _admin_user(test_db_session)
        vector_payload = _dataset_payload(
            key="roundtrip-search-vector",
            title="Roundtrip Search Vector",
        )
        raster_payload = _dataset_payload(
            key="roundtrip-search-raster",
            title="Roundtrip Search Raster",
            source_type="raster_cog",
            uri="rasters/roundtrip-search-raster.tif",
        )
        vrt_payload = _dataset_payload(
            key="roundtrip-search-vrt",
            title="Roundtrip Search VRT",
            source_type="vrt",
            uri="rasters/roundtrip-search-vrt.vrt",
        )
        vector_request = ManifestApplyRequest.model_validate(
            _manifest_payload(vector_payload)
        )
        raster_request = ManifestApplyRequest.model_validate(
            _manifest_payload(raster_payload)
        )
        vrt_request = ManifestApplyRequest.model_validate(
            _manifest_payload(vrt_payload)
        )

        vector_dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Roundtrip Search Vector",
            visibility="public",
            record_status="published",
        )
        _raster_record, raster_dataset, _raster_asset = await create_raster_dataset(
            test_db_session,
            meta={
                "driver": "GTiff",
                "epsg": 4326,
                "band_count": 1,
                "dtype": "uint8",
                "width": 64,
                "height": 64,
            },
            source_sha256="1" * 64,
            asset_sha256="2" * 64,
            cog_status="verified",
            cog_size=2048,
            source_filename="roundtrip-search-raster.tif",
            created_by=user.id,
            title="Roundtrip Search Raster",
            summary="Roundtrip raster summary",
            visibility="public",
            record_status="published",
        )
        _vrt_record, vrt_dataset, _vrt_asset = await create_vrt_dataset(
            test_db_session,
            meta={
                "driver": "VRT",
                "epsg": 4326,
                "band_count": 2,
                "dtype": "uint16",
                "width": 128,
                "height": 128,
            },
            asset_sha256="3" * 64,
            vrt_size=4096,
            source_filename="roundtrip-search-vrt.vrt",
            created_by=user.id,
            title="Roundtrip Search VRT",
            summary="Roundtrip VRT summary",
            visibility="public",
            record_status="published",
            vrt_type="mosaic",
            resolution_strategy="finest",
            source_dataset_ids=[],
        )
        await test_db_session.commit()
        await test_db_session.refresh(raster_dataset)
        await test_db_session.refresh(vrt_dataset)

        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=vector_dataset,
            manifest_dataset=vector_request.datasets[0],
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=raster_dataset,
            manifest_dataset=raster_request.datasets[0],
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=vrt_dataset,
            manifest_dataset=vrt_request.datasets[0],
        )

        await _assert_search_discovers_dataset(
            client,
            admin_auth_header,
            dataset=vector_dataset,
            query="Roundtrip Search Vector",
            record_type="vector_dataset",
        )
        await _assert_search_discovers_dataset(
            client,
            admin_auth_header,
            dataset=raster_dataset,
            query="Roundtrip Search Raster",
            record_type="raster_dataset",
        )
        await _assert_search_discovers_dataset(
            client,
            admin_auth_header,
            dataset=vrt_dataset,
            query="Roundtrip Search VRT",
            record_type="vrt_dataset",
        )

        for dataset, expected_kind in (
            (vector_dataset, "vector"),
            (raster_dataset, "raster"),
            (vrt_dataset, "raster"),
        ):
            token_response = await client.get(
                f"/tiles/token/{dataset.id}/",
                headers=admin_auth_header,
            )
            assert token_response.status_code == 200
            token = token_response.json()
            assert token["kind"] == expected_kind
            if expected_kind == "raster":
                assert str(dataset.id) in token["tile_url"]
