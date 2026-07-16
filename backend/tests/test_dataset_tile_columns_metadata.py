from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.catalog.datasets.domain.schemas import DatasetMeta


def test_dataset_meta_accepts_tile_columns_allowlist() -> None:
    meta = DatasetMeta(tile_columns=["mag", "depth_km"])

    assert meta.tile_columns == ["mag", "depth_km"]


def test_dataset_meta_rejects_duplicate_tile_columns() -> None:
    with pytest.raises(ValidationError, match="tile_columns entries must be unique"):
        DatasetMeta(tile_columns=["mag", "mag"])


def test_dataset_meta_rejects_invalid_tile_column_names() -> None:
    with pytest.raises(ValidationError, match="Invalid tile column names"):
        DatasetMeta(tile_columns=["mag", "drop table"])


@pytest.mark.anyio
async def test_tile_columns_noop_patch_does_not_bump_tile_version(
    client, admin_auth_header, test_db_session
):
    """fix(#458 E-48): a PATCH echoing the current tile_columns must not roll
    the _v= tile version (which forces every client to refetch all tiles)."""
    import uuid as _uuid

    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"TileCols NoOp {_uuid.uuid4().hex[:6]}",
        column_info=[{"name": "name", "type": "text"}],
    )

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"tile_columns": ["name"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    await test_db_session.refresh(ds)
    version_after_change = ds.tile_cache_version

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"tile_columns": ["name"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    await test_db_session.refresh(ds)
    assert ds.tile_cache_version == version_after_change

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"tile_columns": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    await test_db_session.refresh(ds)
    assert ds.tile_cache_version > version_after_change
