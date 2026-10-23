"""In-place column edits follow the live version when it is later retained."""

from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.layers.service import (
    add_column,
    alter_column_type,
    drop_column,
    rename_column,
)
from app.platform.refresh.verification import (
    geometry_contract,
    review_fingerprint,
    review_subject,
)
from tests.test_previous_version_2590 import (
    _cleanup,
    _queue,
    _replace,
    _restore,
    _restore_version,
    _seed,
)
from tests.test_restore_column_source_names import _response_names, _version_columns

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("legacy_route", [False, True], ids=["numbered", "newest"])
@pytest.mark.parametrize("edit", ["rename", "drop_readd"])
async def test_restore_keeps_source_names_after_live_column_edits(
    client, admin_auth_header, test_db_session, legacy_route, edit
):
    """A rename retains its source; a new column replacing a dropped one has none."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await _replace(session, dataset, admin_id, ["paris"])
        live = await session.get(Dataset, dataset.id)
        if edit == "rename":
            await rename_column(session, live, "name", "city")
            expected = {"city": "name"}
        else:
            await drop_column(session, live, "name")
            await add_column(session, live, "name", "text")
            expected = {"name": None}
        await session.commit()

        unknown = geometry_contract(
            geometry_types=None, srid=None, is_3d=None, n_dims=None
        )
        reviewed = review_fingerprint(
            review_subject(
                ["destructive_schema_change"],
                {"columns_removed": [{"name": "city"}], "type_changes": []},
                unknown,
                unknown,
            )
        )

        async def queue_reviewed(*args, metadata, **kwargs):
            """Queued replacement metadata acknowledges the renamed column's removal."""
            return await _queue(
                *args, metadata={**metadata, "review_fingerprint": reviewed}, **kwargs
            )

        with patch("tests.test_previous_version_2590._queue", queue_reviewed):
            await _replace(session, dataset, admin_id, ["london"])

        if legacy_route:
            await _restore(client, admin_auth_header, session, dataset, 2)
        else:
            response = await _restore_version(client, admin_auth_header, dataset, 2)
            assert response.status_code == 202, response.text
        assert await _response_names(client, admin_auth_header, dataset) == expected
        columns = await _version_columns(session, dataset.id, 4)
        assert {c["name"]: c.get("source_name") for c in columns} == expected
    finally:
        await _cleanup(session, dataset)


@pytest.mark.parametrize("recorded", [False, True], ids=["lazy", "recorded"])
@pytest.mark.parametrize("edit", ["add", "rename", "retype", "drop"])
async def test_column_edits_refresh_only_the_live_version_snapshot(
    test_db_session, recorded, edit
):
    """All column edits update an existing live row and leave kept rows alone."""
    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        if recorded:
            await _replace(session, dataset, admin_id, ["paris"])
        historical = await _version_columns(session, dataset.id, 1)
        live = await session.get(Dataset, dataset.id)
        if edit == "add":
            columns = await add_column(session, live, "added", "integer")
        elif edit == "rename":
            columns = await rename_column(session, live, "name", "city")
        elif edit == "retype":
            await session.execute(
                text(f"UPDATE data.\"{dataset.table_name}\" SET name = '42'")
            )
            columns = await alter_column_type(session, live, "name", "integer")
        else:
            columns = await drop_column(session, live, "name")
        await session.commit()

        assert await _version_columns(session, dataset.id, 1) == historical
        if recorded:
            assert await _version_columns(session, dataset.id, 2) == columns
        else:
            assert historical is None
    finally:
        await _cleanup(session, dataset)
