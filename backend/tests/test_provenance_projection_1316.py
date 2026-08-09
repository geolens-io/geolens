"""Single provenance projection across dataset reads, /versions/, and
collection dataset listings (#1316, ADR-002 amendment).

Decided 2026-08-09: the refresh-runs redaction model (ADR-002 Decision 4e) is
the single provenance projection everywhere it applies. The dataset owner and
any admin see raw provenance in full; every other reader of an accessible
dataset — a named signed-in third party or an anonymous reader — gets
`origin_uri`/`origin_ref` nulled on dataset reads and `uploaded_by`/
`file_hash` nulled on `/versions/`. The capability summary
(`origin`, `source_health`, `last_refreshed_at`, `last_checked_at`) is never
gated — it survives redaction for everyone. See `can_view_dataset_provenance`
in `app/modules/catalog/authorization.py`, the single predicate every one of
these surfaces now shares.

Every redaction case below is checked against BOTH a named signed-in third
party (a real account with a real token and no grant on the dataset) and an
anonymous reader — a requester-scoped check that only exercises the
anonymous case is a different code path from `user is None` and reads as
complete when it is not (the same lesson the refresh-runs suite pins).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.modules.catalog.collections.models import DatasetVersion
from tests.factories import create_collection_via_api, create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_ORIGIN_URI = "https://origin.test/services/Parcels/FeatureServer/0"
_ORIGIN_REF = {"kind": "service", "service_type": "wfs", "url": "https://o.test"}
_LAST_REFRESHED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
_LAST_CHECKED_AT = datetime(2026, 1, 2, 3, 4, 6, tzinfo=timezone.utc)


async def _own_user_id(client: AsyncClient, headers: dict) -> uuid.UUID:
    """Resolve the caller's own user id.

    `viewer_auth_header`/`editor_auth_header` mint a fresh `<role>_<hex>`
    account per test, so the username is not knowable up front.
    """
    resp = await client.get("/auth/me/", headers=headers)
    assert resp.status_code == 200
    return uuid.UUID(resp.json()["id"])


async def _create_dataset_with_origin(session, *, created_by: uuid.UUID, name: str):
    """A public, probed service dataset — enough state to exercise both the
    raw pointer fields (`origin_uri`/`origin_ref`) and the capability summary
    that must survive redaction alongside them.
    """
    dataset = await create_dataset(
        session,
        created_by=created_by,
        name=name,
        visibility="public",
        source_format="arcgis_featureserver",
    )
    dataset.origin_uri = _ORIGIN_URI
    dataset.origin_ref = _ORIGIN_REF
    dataset.last_refreshed_at = _LAST_REFRESHED_AT
    dataset.last_checked_at = _LAST_CHECKED_AT
    dataset.source_health = "healthy"
    await session.commit()
    await session.refresh(dataset)
    return dataset


def _assert_summary_survives(body: dict) -> None:
    assert body["origin"] == "service"
    assert body["source_health"] == "healthy"
    assert body["last_refreshed_at"] is not None
    assert body["last_checked_at"] is not None


class TestDatasetReadProjection:
    """GET /datasets/{id}: origin_uri/origin_ref are owner-or-admin only."""

    async def test_owner_sees_full_provenance(
        self, client: AsyncClient, viewer_auth_header: dict, test_db_session
    ) -> None:
        viewer_id = await _own_user_id(client, viewer_auth_header)
        ds = await _create_dataset_with_origin(
            test_db_session, created_by=viewer_id, name="Owner Full DS"
        )

        resp = await client.get(f"/datasets/{ds.id}", headers=viewer_auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["origin_uri"] == _ORIGIN_URI
        assert body["origin_ref"] == _ORIGIN_REF

    async def test_admin_non_owner_sees_full_provenance(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ) -> None:
        """An admin is not the owner here — the predicate must still admit them."""
        viewer_id = await _own_user_id(client, viewer_auth_header)
        ds = await _create_dataset_with_origin(
            test_db_session, created_by=viewer_id, name="Admin Non-Owner DS"
        )

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["origin_uri"] == _ORIGIN_URI
        assert body["origin_ref"] == _ORIGIN_REF

    @pytest.mark.parametrize("reader", ["viewer", "editor"])
    async def test_a_named_third_party_gets_the_summary_without_the_pointers(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
        reader: str,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_origin(
            test_db_session, created_by=admin_id, name=f"Third Party DS {reader}"
        )
        headers = {"viewer": viewer_auth_header, "editor": editor_auth_header}[reader]

        resp = await client.get(f"/datasets/{ds.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["origin_uri"] is None, f"origin_uri leaked to a {reader}"
        assert body["origin_ref"] is None, f"origin_ref leaked to a {reader}"
        _assert_summary_survives(body)

    async def test_anonymous_reader_is_redacted_too(
        self, client: AsyncClient, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_origin(
            test_db_session, created_by=admin_id, name="Anon Read DS"
        )

        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["origin_uri"] is None
        assert body["origin_ref"] is None
        _assert_summary_survives(body)


class TestCollectionDatasetListProjection:
    """GET /catalog/collections/{id}/datasets/: redaction is PER ROW.

    A single collection page mixes the caller's own dataset with a peer's —
    a page-level admin/owner flag would either leak the peer's pointers or
    strip the caller's own, so this pins that the decision is made once per
    row rather than once per page.
    """

    async def test_own_row_full_peer_row_redacted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ) -> None:
        viewer_id = await _own_user_id(client, viewer_auth_header)
        admin_id = await get_user_id(test_db_session, "admin")
        admin_ds = await _create_dataset_with_origin(
            test_db_session, created_by=admin_id, name="Collection Admin DS"
        )
        viewer_ds = await _create_dataset_with_origin(
            test_db_session, created_by=viewer_id, name="Collection Viewer DS"
        )

        collection = await create_collection_via_api(client, admin_auth_header)
        resp = await client.post(
            f"/catalog/collections/{collection['id']}/datasets/",
            json={"dataset_ids": [str(admin_ds.id), str(viewer_ds.id)]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        resp = await client.get(
            f"/catalog/collections/{collection['id']}/datasets/",
            headers=viewer_auth_header,
        )
        assert resp.status_code == 200
        by_id = {d["id"]: d for d in resp.json()["datasets"]}

        # The viewer's own row: full projection.
        assert by_id[str(viewer_ds.id)]["origin_uri"] == _ORIGIN_URI
        assert by_id[str(viewer_ds.id)]["origin_ref"] == _ORIGIN_REF

        # The admin-owned peer row, same page: redacted, summary intact.
        peer_row = by_id[str(admin_ds.id)]
        assert peer_row["origin_uri"] is None
        assert peer_row["origin_ref"] is None
        _assert_summary_survives(peer_row)


class TestVersionsProjection:
    """GET /datasets/{id}/versions/: file_hash/uploaded_by are owner-or-admin only.

    Unredacted, a PUBLIC dataset's version history enumerates its editors —
    the exact leak ADR-002 Decision 4e closed for refresh-runs.
    """

    @staticmethod
    async def _seed_version(session, dataset_id: uuid.UUID, uploader_id: uuid.UUID):
        version = DatasetVersion(
            dataset_id=dataset_id,
            version_number=1,
            source_filename="original.geojson",
            source_format="geojson",
            feature_count=100,
            srid=4326,
            geometry_type="MultiPolygon",
            file_hash="sha256:deadbeef",
            uploaded_by=uploader_id,
        )
        session.add(version)
        await session.commit()
        return version

    async def test_owner_sees_file_hash_and_uploaded_by(
        self, client: AsyncClient, viewer_auth_header: dict, test_db_session
    ) -> None:
        viewer_id = await _own_user_id(client, viewer_auth_header)
        ds = await create_dataset(
            test_db_session,
            created_by=viewer_id,
            name="Owner Versions DS",
            visibility="public",
        )
        await self._seed_version(test_db_session, ds.id, viewer_id)

        resp = await client.get(
            f"/datasets/{ds.id}/versions/", headers=viewer_auth_header
        )
        assert resp.status_code == 200
        row = resp.json()["versions"][0]
        assert row["file_hash"] == "sha256:deadbeef"
        assert row["uploaded_by"] == str(viewer_id)

    async def test_admin_non_owner_sees_full_versions(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ) -> None:
        viewer_id = await _own_user_id(client, viewer_auth_header)
        ds = await create_dataset(
            test_db_session,
            created_by=viewer_id,
            name="Admin Non-Owner Versions DS",
            visibility="public",
        )
        await self._seed_version(test_db_session, ds.id, viewer_id)

        resp = await client.get(
            f"/datasets/{ds.id}/versions/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        row = resp.json()["versions"][0]
        assert row["file_hash"] == "sha256:deadbeef"
        assert row["uploaded_by"] == str(viewer_id)

    @pytest.mark.parametrize("reader", ["viewer", "editor"])
    async def test_a_named_third_party_gets_the_timeline_without_the_hash(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
        reader: str,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Third Party Versions DS {reader}",
            visibility="public",
        )
        await self._seed_version(test_db_session, ds.id, admin_id)
        headers = {"viewer": viewer_auth_header, "editor": editor_auth_header}[reader]

        resp = await client.get(f"/datasets/{ds.id}/versions/", headers=headers)
        assert resp.status_code == 200, resp.text
        row = resp.json()["versions"][0]
        assert row["file_hash"] is None, f"file_hash leaked to a {reader}"
        assert row["uploaded_by"] is None, f"uploaded_by leaked to a {reader}"
        # The timeline itself survives redaction.
        assert row["source_filename"] == "original.geojson"
        assert row["feature_count"] == 100
        assert row["version_number"] == 1

    async def test_anonymous_reader_is_redacted_too(
        self, client: AsyncClient, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Anon Versions DS",
            visibility="public",
        )
        await self._seed_version(test_db_session, ds.id, admin_id)

        resp = await client.get(f"/datasets/{ds.id}/versions/")
        assert resp.status_code == 200
        row = resp.json()["versions"][0]
        assert row["file_hash"] is None
        assert row["uploaded_by"] is None
        assert row["source_filename"] == "original.geojson"
