"""fix(#1778): a property the write path cannot address must be refused, not dropped.

Two guards disagreed about what a legal column is. `_reject_unknown_properties`
admitted any key present in column_info; the write loops then silently skipped
whatever `_COLUMN_NAME_RE` rejected, which is strictly narrower than every
producer of column_info. So a dataset with a `_notes` column returned that key
from GET and answered 201/200 on a write with the value never stored -- and on
PUT the column was not even NULLed, contradicting the documented "Columns not
present in properties are set to NULL". Silent write loss behind a success
response is exactly what an editing UI's read-modify-write round trip hits.

The hole was reachable with no external data: `POST /datasets/create/` validated
column names against SAFE_COLUMN_NAME_RE, which allows a leading underscore and
has no length bound, so it happily built a column the feature API could never
write.

Requires the Docker test database.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

POINT = {"type": "Point", "coordinates": [-74.0, 40.7]}


async def _create_dataset_with_unwritable_column(
    session, *, created_by: uuid.UUID
) -> Dataset:
    """A table carrying `_notes`, the shape create_empty_dataset used to allow."""
    table_name = f"test_uw_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "gid SERIAL PRIMARY KEY, "
            "geom geometry(Geometry, 4326), "
            "geom_4326 geometry(Geometry, 4326), "
            "name TEXT, "
            '"_notes" TEXT)'
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    record = Record(
        title=f"Unwritable column {table_name}",
        summary="Latent unwritable column",
        theme_category=["test"],
        visibility="private",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="GEOMETRY",
        feature_count=0,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "_notes", "type": "text"},
        ],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def unwritable_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset_with_unwritable_column(
        test_db_session, created_by=admin_id
    )
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


async def test_post_refuses_an_unwritable_property_instead_of_dropping_it(
    client: AsyncClient, unwritable_dataset: Dataset, admin_auth_header
):
    resp = await client.post(
        f"/datasets/{unwritable_dataset.id}/features/",
        json={"geometry": POINT, "properties": {"_notes": "keep me"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert "_notes" in resp.json()["detail"]


async def test_post_still_accepts_a_writable_property(
    client: AsyncClient, unwritable_dataset: Dataset, admin_auth_header
):
    """The refusal is per property on POST, not a blanket lock on the dataset."""
    resp = await client.post(
        f"/datasets/{unwritable_dataset.id}/features/",
        json={"geometry": POINT, "properties": {"name": "Alpha"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["properties"]["name"] == "Alpha"


async def test_patch_refuses_an_unwritable_property(
    client: AsyncClient, unwritable_dataset: Dataset, admin_auth_header
):
    created = await client.post(
        f"/datasets/{unwritable_dataset.id}/features/",
        json={"geometry": POINT, "properties": {"name": "Alpha"}},
        headers=admin_auth_header,
    )
    gid = created.json()["id"]

    resp = await client.patch(
        f"/datasets/{unwritable_dataset.id}/features/{gid}",
        json={"properties": {"_notes": "keep me"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert "_notes" in resp.json()["detail"]


async def test_put_refuses_the_dataset_because_replace_nulls_every_column(
    client: AsyncClient, unwritable_dataset: Dataset, admin_auth_header
):
    """PUT sets every known column, so one unwritable column breaks the contract."""
    created = await client.post(
        f"/datasets/{unwritable_dataset.id}/features/",
        json={"geometry": POINT, "properties": {"name": "Alpha"}},
        headers=admin_auth_header,
    )
    gid = created.json()["id"]

    resp = await client.put(
        f"/datasets/{unwritable_dataset.id}/features/{gid}",
        json={"geometry": POINT, "properties": {"name": "Beta"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text
    assert "_notes" in resp.json()["detail"]


async def test_an_unknown_property_is_still_a_400(
    client: AsyncClient, unwritable_dataset: Dataset, admin_auth_header
):
    """The pre-existing unknown-key contract (fix(#458 E-25)) is unchanged."""
    resp = await client.post(
        f"/datasets/{unwritable_dataset.id}/features/",
        json={"geometry": POINT, "properties": {"nosuchcolumn": "x"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 400
    assert "nosuchcolumn" in resp.json()["detail"]


@pytest.mark.parametrize(
    "column_name",
    ["_notes", "n" * 64],
    ids=["leading-underscore", "over-63-characters"],
)
async def test_creating_an_unwritable_column_is_refused(
    client: AsyncClient, admin_auth_header, column_name
):
    """The hole is closed where it opens: no such column gets built at all."""
    resp = await client.post(
        "/datasets/create/",
        json={
            "title": f"Unwritable column {uuid.uuid4().hex[:8]}",
            "columns": [{"name": column_name, "type": "text"}],
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 400, resp.text
    assert "column name" in resp.json()["detail"].lower()


async def test_a_writable_column_still_creates(client: AsyncClient, admin_auth_header):
    """The vacuity guard: the refusal must not have closed the ordinary path."""
    resp = await client.post(
        "/datasets/create/",
        json={
            "title": f"Writable column {uuid.uuid4().hex[:8]}",
            "columns": [{"name": "Notes", "type": "text"}],
        },
        headers=admin_auth_header,
    )

    assert resp.status_code in (200, 201), resp.text
