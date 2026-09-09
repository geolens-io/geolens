"""One minted tile signature authorizes an unpublished public dataset on the
raster, vector and cluster routes alike, and a draft's tiles stay private."""

import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _admin_id(session) -> uuid.UUID:
    return await get_user_id(session, "admin")


async def _make_raster(session, *, created_by: uuid.UUID, record_status: str):
    return await create_raster_dataset(
        session,
        created_by=created_by,
        name=f"Signature Parity Raster {uuid.uuid4().hex[:6]}",
        visibility="public",
        record_status=record_status,
        table_name=f"sig_parity_raster_{uuid.uuid4().hex[:8]}",
        source_filename="test.tif",
        create_raster_asset=True,
    )


async def _make_vector(session, *, created_by: uuid.UUID, record_status: str):
    record = Record(
        title=f"Signature Parity Vector {uuid.uuid4().hex[:6]}",
        summary="Point dataset for the signed-draft parity tests",
        theme_category=["test"],
        visibility="public",
        record_status=record_status,
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"sig_parity_vector_{uuid.uuid4().hex[:8]}",
        source_format="geojson",
        source_filename="test.geojson",
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)

    table = dataset.table_name
    await session.execute(
        text(
            f"CREATE TABLE data.{table} ("
            "  gid SERIAL PRIMARY KEY,"
            "  geom GEOMETRY(Point, 3857),"
            "  geom_4326 GEOMETRY(Point, 4326))"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table} (geom, geom_4326) VALUES ("
            "  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            "  ST_SetSRID(ST_MakePoint(0, 0), 4326))"
        )
    )
    await session.commit()
    return dataset


async def _drop_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


async def _mint(client: AsyncClient, dataset_id, admin_auth_header: dict) -> dict:
    resp = await client.get(f"/tiles/token/{dataset_id}/", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    token = resp.json()
    return {"sig": token["sig"], "exp": token["exp"], "scope": token["scope"]}


class TestSignedDraftParity:
    async def test_raster_serves_a_signed_draft(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_raster(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            record_status="draft",
        )
        params = await _mint(client, dataset.id, admin_auth_header)

        bare = await client.get(
            "/tiles/raster-auth-check/", params={"dataset_id": str(dataset.id)}
        )
        signed = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id), **params},
        )

        assert bare.status_code == 404, bare.text
        assert signed.status_code == 200, signed.text

    async def test_vector_serves_a_signed_draft(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            record_status="draft",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"

            bare = await client.get(url)
            signed = await client.get(url, params=params)

            assert bare.status_code == 404, bare.text
            assert signed.status_code == 200, signed.text
            assert signed.headers["cache-control"].startswith("private")
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_cluster_serves_a_signed_draft(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            record_status="draft",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/clusters/data.{dataset.table_name}/0/0/0.pbf"

            bare = await client.get(url)
            signed = await client.get(url, params=params)

            assert bare.status_code == 404, bare.text
            assert signed.status_code == 200, signed.text
            assert signed.headers["cache-control"].startswith("private")
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_the_three_routes_answer_alike_for_the_same_input(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """One input, three routes, one answer."""
        admin = await _admin_id(test_db_session)
        raster = await _make_raster(
            test_db_session, created_by=admin, record_status="draft"
        )
        vector = await _make_vector(
            test_db_session, created_by=admin, record_status="draft"
        )
        try:
            raster_params = await _mint(client, raster.id, admin_auth_header)
            vector_params = await _mint(client, vector.id, admin_auth_header)
            answers = {
                "raster": (
                    await client.get(
                        "/tiles/raster-auth-check/",
                        params={"dataset_id": str(raster.id), **raster_params},
                    )
                ).status_code
            }
            for route, url in (
                ("vector", f"/tiles/data.{vector.table_name}/0/0/0.pbf"),
                ("cluster", f"/tiles/clusters/data.{vector.table_name}/0/0/0.pbf"),
            ):
                answers[route] = (
                    await client.get(url, params=vector_params)
                ).status_code

            assert len(set(answers.values())) == 1, answers
            assert answers["raster"] == 200, answers
        finally:
            await _drop_table(test_db_session, vector.table_name)

    async def test_a_signed_published_tile_stays_shared_cacheable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A signature does not narrow the cache scope a published dataset earns."""
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            record_status="published",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            resp = await client.get(
                f"/tiles/data.{dataset.table_name}/0/0/0.pbf", params=params
            )

            assert resp.status_code == 200, resp.text
            assert resp.headers["cache-control"].startswith("public")
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_a_valid_signature_outranks_an_unresolvable_credential(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The credential rule answers a request no capability authorized.

        A valid signature is such a capability, so it decides the request the
        way it does on the raster route; without one the same header is 401.
        """
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            record_status="published",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"
            headers = {"Authorization": "Bearer not-a-real-credential-1518"}

            signed = await client.get(url, params=params, headers=headers)
            bare = await client.get(url, headers=headers)

            assert signed.status_code == 200, signed.text
            assert bare.status_code == 401, bare.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_an_expired_signature_still_falls_through(
        self, client: AsyncClient, test_db_session
    ):
        """An unusable signature is not a refusal: the draft answers 404 to anon."""
        from app.core.tile_scope import tile_signature_scope
        from app.processing.tiles.signing import generate_tile_signature

        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            record_status="draft",
        )
        try:
            scope = tile_signature_scope(dataset.table_name, 0)
            expired = int(time.time()) - 60
            resp = await client.get(
                f"/tiles/data.{dataset.table_name}/0/0/0.pbf",
                params={
                    "sig": generate_tile_signature(scope, expired),
                    "exp": expired,
                    "scope": scope,
                },
            )

            assert resp.status_code == 404, resp.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)
