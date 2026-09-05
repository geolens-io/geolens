"""Who sees a VRT generation's failure text and the id of whoever triggered it.

fix(#1860): ``GET /datasets/{dataset_id}/vrt/generations/`` gated on
``check_dataset_access``, which is a VISIBILITY check by its own contract: it
admits any signed-in caller on a published public or internal dataset. It then
returned every history row's ``error_message`` and ``triggered_by``.

That is the same door closed on ``GET /jobs/by-dataset/{dataset_id}`` in the
first commit of this change, and the one ``list_dataset_refresh_runs`` had
already closed on its own identical fields. The reader who gets missed is the
signed-in stranger rather than the anonymous one, so every case below uses a
NAMED third party on a dataset they can legitimately see.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

from app.processing.raster.models import VrtGeneration

from tests.factories import create_dataset, create_user, get_user_id

_ERROR_TEXT = "ogr2ogr: cannot open /srv/private-staging/tile-042.tif"


async def _seed_vrt_history(session, *, owner_id: uuid.UUID, triggered_by: uuid.UUID):
    """A published public VRT dataset with one failed generation in its history."""
    now = datetime.now(timezone.utc)
    vrt = await create_dataset(
        session,
        created_by=owner_id,
        name="Disclosure Mosaic",
        record_type="vrt_dataset",
        source_format="geotiff",
        source_filename="mosaic.vrt",
        visibility="public",
    )
    generation = VrtGeneration(
        vrt_dataset_id=vrt.id,
        status="failed",
        started_at=now - timedelta(minutes=5),
        completed_at=now,
        duration_seconds=300.0,
        error_message=_ERROR_TEXT,
        source_count=3,
        triggered_by=str(triggered_by),
    )
    session.add(generation)
    await session.commit()
    await session.refresh(generation)
    return vrt, generation


class TestVrtGenerationDisclosure:
    async def test_third_party_sees_the_timeline_without_the_detail(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """A stranger who can read the dataset still gets the redacted rows."""
        admin_id = await get_user_id(test_db_session, "admin")
        stranger_header, _ = await create_user(client, admin_auth_header, "editor")
        vrt, generation = await _seed_vrt_history(
            test_db_session, owner_id=admin_id, triggered_by=admin_id
        )

        resp = await client.get(
            f"/datasets/{vrt.id}/vrt/generations/", headers=stranger_header
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()["generations"]
        assert len(rows) == 1
        row = rows[0]

        # Kept: the timeline get_vrt_status already publishes to this reader.
        assert row["id"] == str(generation.id)
        assert row["status"] == "failed"
        assert row["source_count"] == 3
        assert row["started_at"] is not None
        assert row["completed_at"] is not None
        assert row["duration_seconds"] == 300.0

        # Redacted: the two fields DatasetRefreshRunResponse nulls for the
        # same reader.
        assert row["error_message"] is None
        assert row["triggered_by"] is None

        body = resp.text
        assert "private-staging" not in body
        assert str(admin_id) not in body

    async def test_dataset_owner_sees_the_detail(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """The owner arm, isolated: a non-admin who owns the VRT dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        owner_header, owner_id = await create_user(client, admin_auth_header, "editor")
        vrt, _ = await _seed_vrt_history(
            test_db_session,
            owner_id=uuid.UUID(owner_id),
            triggered_by=admin_id,
        )

        resp = await client.get(
            f"/datasets/{vrt.id}/vrt/generations/", headers=owner_header
        )
        assert resp.status_code == 200, resp.text
        row = resp.json()["generations"][0]
        assert row["error_message"] == _ERROR_TEXT
        assert row["triggered_by"] == str(admin_id)

    async def test_admin_sees_the_detail_on_another_users_dataset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Admins keep the operator view the regeneration surface needs."""
        _, owner_id = await create_user(client, admin_auth_header, "editor")
        vrt, _ = await _seed_vrt_history(
            test_db_session,
            owner_id=uuid.UUID(owner_id),
            triggered_by=uuid.UUID(owner_id),
        )

        resp = await client.get(
            f"/datasets/{vrt.id}/vrt/generations/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        row = resp.json()["generations"][0]
        assert row["error_message"] == _ERROR_TEXT
        assert row["triggered_by"] == str(owner_id)

    async def test_invisible_dataset_is_still_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """The visibility check is unchanged; only the projection is new."""
        admin_id = await get_user_id(test_db_session, "admin")
        stranger_header, _ = await create_user(client, admin_auth_header, "editor")
        vrt = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private Mosaic",
            record_type="vrt_dataset",
            source_format="geotiff",
            visibility="private",
        )

        resp = await client.get(
            f"/datasets/{vrt.id}/vrt/generations/", headers=stranger_header
        )
        assert resp.status_code == 404
