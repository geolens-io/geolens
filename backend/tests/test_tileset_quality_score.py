"""A 3D Tiles dataset is scored on its metadata alone, and its table is never queried."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text

from app.core.tiles3d import TILESET_ASSET_KEY, tileset_prefix
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.ingest.metadata_quality import compute_quality_score
from app.processing.raster.models import DatasetAsset


@pytest.fixture
async def tileset(test_db_session):
    """A published tileset whose synthetic table does not exist."""
    owner = User(username=f"tiles3d-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db_session.add(owner)
    await test_db_session.flush()
    record = Record(
        title="Campus tileset",
        summary="Photogrammetry of the campus",
        record_type="tiles3d_dataset",
        visibility="public",
        record_status="published",
        created_by=owner.id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"tiles3d_{uuid.uuid4().hex[:16]}",
        source_format="3dtiles",
    )
    test_db_session.add(dataset)
    await test_db_session.flush()
    test_db_session.add(
        DatasetAsset(
            dataset_id=dataset.id,
            key=TILESET_ASSET_KEY,
            href=f"{tileset_prefix(dataset.id)}{uuid.uuid4()}/tileset.json",
            size_bytes=1024,
        )
    )
    await test_db_session.commit()
    await test_db_session.refresh(dataset, ["record"])
    record_id, owner_id = record.id, owner.id
    yield dataset
    # A committed tiles3d row blocks every later downgrade past 0065 in this
    # worker's database (see tests/alembic_helpers.py).
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await test_db_session.execute(
        text("DELETE FROM catalog.users WHERE id = :id"), {"id": owner_id}
    )
    await test_db_session.commit()


async def test_the_validate_route_scores_only_the_metadata(
    client: AsyncClient, admin_auth_header: dict, tileset
) -> None:
    """Geometry, attribute and CRS have no score, and the detail still reads it."""
    validated = await client.get(
        f"/datasets/{tileset.id}/validate/",
        params={"refresh": True},
        headers=admin_auth_header,
    )
    detail = await client.get(f"/datasets/{tileset.id}", headers=admin_auth_header)

    assert validated.status_code == 200, validated.text
    score = validated.json()["quality_score"]
    assert (
        score["geometry_validity"],
        score["attribute_completeness"],
        score["crs_defined"],
    ) == (None, None, None)
    assert score["overall"] == round(score["metadata_completeness"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["quality_detail"]["attribute_completeness"] is None


async def test_no_query_touches_the_tilesets_table(test_db_session, tileset) -> None:
    """Even a row that claims geometry and columns never has its table read."""
    tileset.geometry_type = "POLYGON"
    statements: list[str] = []

    def _record(conn, cursor, statement, *args) -> None:
        statements.append(statement)

    engine = test_db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        score = await compute_quality_score(
            test_db_session,
            tileset.table_name,
            [{"name": "height", "type": "double precision"}],
            tileset,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert statements, "the metadata score reads the record's keywords"
    assert not any(tileset.table_name in statement for statement in statements)
    assert score["attribute_completeness"] is None
