"""End-to-end coverage for the dataset attribution field (feat(#1472)).

``ManifestMetadata.attribution`` was validated at manifest apply and written to
``ingest_jobs.user_metadata['manifest_attribution']``, then dropped: no column,
no read model, nothing displayed. These tests pin the three seams that carry it
now — the PATCH round-trip, the dataset and map-layer read models, and the
ingest tail that seeds the column from the job ledger.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Record
from app.processing.ingest.manifest_schemas import ManifestDataset
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_job_metadata,
)
from app.processing.ingest.tasks_common import apply_manifest_record_metadata
from tests.factories import create_dataset, get_user_id

_SWISSTOPO_CREDIT = "© swisstopo — swissALTI3D"


async def _create_map_with_dataset(
    client: AsyncClient,
    headers: dict,
    dataset_id: uuid.UUID,
    *,
    public: bool = False,
) -> str:
    """Create a map, attach ``dataset_id`` as a layer, return the map id."""
    resp = await client.post(
        "/maps/",
        json={"name": f"Attribution Map {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    map_id = resp.json()["id"]

    resp = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(dataset_id)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    if public:
        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
    return map_id


class TestAttributionPatchRoundTrip:
    async def test_patch_sets_then_clears_attribution(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH writes the field, GET reads it back, explicit null clears it."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution RT {uuid.uuid4().hex[:6]}",
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"attribution": _SWISSTOPO_CREDIT},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["attribution"] == _SWISSTOPO_CREDIT

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        assert resp.json()["attribution"] == _SWISSTOPO_CREDIT

        # Explicit null clears — attribution is not in _NON_CLEARABLE_FIELDS,
        # so a source whose terms no longer require credit can drop the line.
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"attribution": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["attribution"] is None

        await test_db_session.refresh(await test_db_session.get(Record, ds.record_id))
        record = await test_db_session.get(Record, ds.record_id)
        assert record.attribution is None

    async def test_patch_omitting_attribution_leaves_it_alone(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """An absent key keeps PATCH semantics — it must not null the column."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution Keep {uuid.uuid4().hex[:6]}",
        )
        await client.patch(
            f"/datasets/{ds.id}",
            json={"attribution": _SWISSTOPO_CREDIT},
            headers=admin_auth_header,
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"summary": "unrelated edit"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["attribution"] == _SWISSTOPO_CREDIT

    async def test_attribution_over_max_length_is_rejected(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The 5000 bound matches ManifestMetadata.attribution's NonEmptyString5000."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution Bound {uuid.uuid4().hex[:6]}",
        )
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"attribution": "x" * 5001},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text


class TestAttributionReadModels:
    async def test_dataset_detail_and_list_carry_attribution(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution List {uuid.uuid4().hex[:6]}",
        )
        record = await test_db_session.get(Record, ds.record_id)
        record.attribution = _SWISSTOPO_CREDIT
        await test_db_session.commit()

        detail = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert detail.status_code == 200, detail.text
        assert detail.json()["attribution"] == _SWISSTOPO_CREDIT

        listing = await client.get("/datasets/", headers=admin_auth_header)
        assert listing.status_code == 200, listing.text
        rows = [d for d in listing.json()["datasets"] if d["id"] == str(ds.id)]
        assert rows, "dataset missing from list response"
        assert rows[0]["attribution"] == _SWISSTOPO_CREDIT

    async def test_map_layer_response_carries_dataset_attribution(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /maps/{id} — the builder/authenticated-viewer read model."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution Layer {uuid.uuid4().hex[:6]}",
        )
        record = await test_db_session.get(Record, ds.record_id)
        record.attribution = _SWISSTOPO_CREDIT
        await test_db_session.commit()

        map_id = await _create_map_with_dataset(client, admin_auth_header, ds.id)

        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        layers = [
            layer
            for layer in resp.json()["layers"]
            if layer["dataset_id"] == str(ds.id)
        ]
        assert layers, "layer missing from map response"
        assert layers[0]["dataset_attribution"] == _SWISSTOPO_CREDIT

    async def test_shared_map_layer_carries_dataset_attribution(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /maps/shared/{token} — the share-link and embed read model.

        This is the surface the display obligation most needs to reach: the
        audience of a share link is outside the instance.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution Shared {uuid.uuid4().hex[:6]}",
            visibility="public",
        )
        record = await test_db_session.get(Record, ds.record_id)
        record.attribution = _SWISSTOPO_CREDIT
        await test_db_session.commit()

        map_id = await _create_map_with_dataset(
            client, admin_auth_header, ds.id, public=True
        )
        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert share.status_code == 200, share.text
        token = share.json()["token"]

        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 200, resp.text
        layers = [
            layer
            for layer in resp.json()["layers"]
            if layer["dataset_id"] == str(ds.id)
        ]
        assert layers, "layer missing from shared map response"
        assert layers[0]["dataset_attribution"] == _SWISSTOPO_CREDIT

    async def test_layer_without_attribution_serializes_null(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The common case — no credit required — must not invent a string."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Attribution None {uuid.uuid4().hex[:6]}",
        )
        map_id = await _create_map_with_dataset(client, admin_auth_header, ds.id)

        resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        layer = next(
            layer
            for layer in resp.json()["layers"]
            if layer["dataset_id"] == str(ds.id)
        )
        assert layer["dataset_attribution"] is None


class TestManifestAttributionCommit:
    """The ingest tail's read-back of ``manifest_attribution``.

    Driven from ``manifest_job_metadata``'s real output rather than a
    hand-written dict, so a rename on either side of the ledger fails here
    instead of silently reintroducing the drop this feature fixes.
    """

    @staticmethod
    async def _ledger(attribution: str | None) -> dict:
        metadata: dict = {"organization": "swisstopo", "license": "swisstopo terms"}
        if attribution is not None:
            metadata["attribution"] = attribution
        dataset = ManifestDataset.model_validate(
            {
                "key": "alti3d",
                "title": "swissALTI3D",
                "sources": [
                    {
                        "type": "vector",
                        "uri": "tests/fixtures/ingest/basic_attrs.geojson",
                        "format": "geojson",
                    }
                ],
                "metadata": metadata,
                "publication": {"intent": "published"},
            }
        )
        prepared = await classify_manifest_source(dataset.sources[0])
        return manifest_job_metadata(dataset, prepared, fingerprint="deadbeef")

    async def test_manifest_ledger_carries_attribution_to_the_record(self):
        ledger = await self._ledger(_SWISSTOPO_CREDIT)
        assert ledger["manifest_attribution"] == _SWISSTOPO_CREDIT

        record = Record(title="swissALTI3D")
        apply_manifest_record_metadata(record, ledger)
        assert record.attribution == _SWISSTOPO_CREDIT

    async def test_manifest_without_attribution_leaves_the_column_null(self):
        ledger = await self._ledger(None)
        assert "manifest_attribution" not in ledger

        record = Record(title="swissALTI3D")
        apply_manifest_record_metadata(record, ledger)
        assert record.attribution is None

    @pytest.mark.parametrize("user_metadata", [None, {}, {"title": "an upload"}])
    def test_non_manifest_ingests_are_untouched(self, user_metadata):
        """Upload/service/STAC jobs carry no manifest namespace — no-op."""
        record = Record(title="Uploaded")
        apply_manifest_record_metadata(record, user_metadata)
        assert record.attribution is None

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
    def test_blank_attribution_is_not_written(self, blank):
        """A whitespace-only credit is no credit; it must not become a string
        the viewer then renders as an empty attribution entry."""
        record = Record(title="Blank")
        apply_manifest_record_metadata(record, {"manifest_attribution": blank})
        assert record.attribution is None

    def test_a_reapply_replaces_a_previous_credit(self):
        """fix(#1472 review): the reupload case. A manifest re-apply whose
        fingerprint changed classifies as "update" and swaps new data onto the
        existing record, so the helper has to OVERWRITE the credit already
        there — leaving the old one would name a source the new bytes did not
        come from, which is worse than carrying no credit at all."""
        record = Record(title="swissALTI3D", attribution="© swisstopo — 2024 tiles")
        apply_manifest_record_metadata(
            record, {"manifest_attribution": _SWISSTOPO_CREDIT}
        )
        assert record.attribution == _SWISSTOPO_CREDIT

    def test_a_reapply_that_omits_attribution_keeps_the_existing_credit(self):
        """An absent key means "unchanged", matching the dataset PATCH's
        semantics for the same field. Clearing a credit is an explicit edit,
        not something a manifest that never mentioned the field should do."""
        record = Record(title="swissALTI3D", attribution=_SWISSTOPO_CREDIT)
        apply_manifest_record_metadata(record, {"manifest_key": "alti3d"})
        assert record.attribution == _SWISSTOPO_CREDIT

    def test_surrounding_whitespace_is_stripped(self):
        record = Record(title="Padded")
        apply_manifest_record_metadata(
            record, {"manifest_attribution": f"  {_SWISSTOPO_CREDIT}  "}
        )
        assert record.attribution == _SWISSTOPO_CREDIT
