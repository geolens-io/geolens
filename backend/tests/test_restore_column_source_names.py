import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import null, select, text

from app.modules.catalog.collections.models import DatasetVersion
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.refresh.verification import (
    geometry_contract,
    review_fingerprint,
    review_subject,
)
from app.processing.ingest.catalog_projection import Measurement
from app.processing.ingest.tasks_restore import _RestorePreviousVersion
from tests.test_previous_version_2590 import (
    _cleanup,
    _queue,
    _replace,
    _restore,
    _restore_version,
    _seed,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("source_present", "kept_columns", "expected"),
    [
        (
            True,
            [
                {"name": "dropped", "type": "integer", "source_name": "Dropped"},
                {"name": "name", "type": "text", "source_name": "Name"},
            ],
            {"name": "Name", "dropped": "Dropped", "elev": None},
        ),
        (True, None, {"name": None, "dropped": None, "elev": None}),
        (True, [], {"name": None, "dropped": None, "elev": None}),
        (
            True,
            [{"name": "name", "type": "text"}],
            {"name": None, "dropped": None, "elev": None},
        ),
        (False, None, {"name": None, "dropped": None, "elev": None}),
    ],
    ids=["recorded", "legacy-null", "empty", "legacy-column", "missing-row"],
)
async def test_restore_uses_the_kept_versions_source_names(
    source_present, kept_columns, expected
):
    source = SimpleNamespace(
        column_info=kept_columns,
        kept_refreshed_at=None,
        source_filename="old.geojson",
        source_format="geojson",
        file_hash=None,
        original_srid=4326,
    )
    dataset = SimpleNamespace(
        id=uuid.uuid4(),
        record=SimpleNamespace(record_type="vector_dataset"),
        current_version=2,
        last_refreshed_at=None,
        table_name="restored",
        geometry_type="POINT",
        feature_count=1,
        origin_ref={"kind": "upload"},
        column_info=[{"name": "name", "type": "text", "source_name": "NAME"}],
    )
    strategy = _RestorePreviousVersion(user_id=str(uuid.uuid4()))
    strategy.expected = 1
    strategy.measurement = Measurement(
        metadata={
            "column_info": [
                {"name": "name", "type": "text", "ordinal_position": 4},
                {"name": "dropped", "type": "integer", "ordinal_position": 5},
                {"name": "elev", "type": "double precision", "ordinal_position": 6},
            ],
            "feature_count": 1,
            "srid": 4326,
        },
        sample_values={},
        three_d={"is_3d": False, "n_dims": 2},
        geometry_type="POINT",
        quality_detail={},
    )
    session = AsyncMock()
    session.scalar.return_value = source if source_present else None
    session.add = Mock()
    with (
        patch("app.processing.ingest.tasks_restore.record_live_version", AsyncMock()),
        patch("app.processing.ingest.tasks_restore.stamp_kept_versions", AsyncMock()),
        patch("app.processing.ingest.metadata.refresh_attribute_metadata", AsyncMock()),
        patch("app.platform.audit.audit_emit", AsyncMock()),
    ):
        await strategy.write(session, dataset)

    assert {c["name"]: c.get("source_name") for c in dataset.column_info} == expected
    assert dataset.column_info[0]["ordinal_position"] == 4
    version = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], DatasetVersion)
    )
    assert version.column_info == dataset.column_info


_ORIGINAL_COLUMNS = [
    {"name": "name", "type": "text", "source_name": "Name"},
    {"name": "dropped", "type": "integer", "source_name": "Dropped"},
]


async def _version_columns(session, dataset_id, number):
    session.expire_all()
    return await session.scalar(
        select(DatasetVersion.column_info).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version_number == number,
        )
    )


async def _response_names(client, headers, dataset):
    response = await client.get(f"/api/datasets/{dataset.id}", headers=headers)
    assert response.status_code == 200, response.text
    return {c["name"]: c["source_name"] for c in response.json()["column_info"]}


async def _replace_dropping_column(session, dataset, admin_id):
    unknown = geometry_contract(geometry_types=None, srid=None, is_3d=None, n_dims=None)
    reviewed = review_fingerprint(
        review_subject(
            ["destructive_schema_change"],
            {"columns_removed": [{"name": "dropped"}], "type_changes": []},
            unknown,
            unknown,
        )
    )

    async def queue_reviewed(*args, metadata, **kwargs):
        return await _queue(
            *args, metadata={**metadata, "review_fingerprint": reviewed}, **kwargs
        )

    with patch("tests.test_previous_version_2590._queue", queue_reviewed):
        await _replace(session, dataset, admin_id, ["paris"])


@pytest.mark.parametrize("legacy_route", [False, True], ids=["numbered", "newest"])
@pytest.mark.parametrize("existing", ["missing", "legacy", "recorded"])
async def test_reupload_then_restore_keeps_each_versions_own_names(
    client, admin_auth_header, test_db_session, legacy_route, existing
):
    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await session.execute(
            text(f'ALTER TABLE data."{dataset.table_name}" ADD COLUMN dropped integer')
        )
        live = await session.get(Dataset, dataset.id)
        live.column_info = _ORIGINAL_COLUMNS
        if existing != "missing":
            session.add(
                DatasetVersion(
                    dataset_id=dataset.id,
                    version_number=1,
                    source_format="geojson",
                    column_info=_ORIGINAL_COLUMNS if existing == "recorded" else null(),
                )
            )
        if existing == "recorded":
            live.column_info = [
                {k: v for k, v in col.items() if k != "source_name"}
                for col in _ORIGINAL_COLUMNS
            ]
        await session.commit()

        await _replace_dropping_column(session, dataset, admin_id)

        assert await _version_columns(session, dataset.id, 1) == _ORIGINAL_COLUMNS
        replacement_columns = await _version_columns(session, dataset.id, 2)
        assert replacement_columns is not None
        assert {c["name"]: c.get("source_name") for c in replacement_columns} == {
            "name": "name"
        }
        await session.commit()

        if legacy_route:
            await _restore(client, admin_auth_header, session, dataset, 1)
        else:
            response = await _restore_version(client, admin_auth_header, dataset, 1)
            assert response.status_code == 202, response.text
        assert await _response_names(client, admin_auth_header, dataset) == {
            "name": "Name",
            "dropped": "Dropped",
        }
        restored_columns = await _version_columns(session, dataset.id, 3)
        assert restored_columns is not None
        assert {c["name"]: c.get("source_name") for c in restored_columns} == {
            "name": "Name",
            "dropped": "Dropped",
        }
        assert restored_columns[0]["ordinal_position"] == 4
        assert await _version_columns(session, dataset.id, 2) == replacement_columns
        await session.commit()

        response = await _restore_version(client, admin_auth_header, dataset, 2)
        assert response.status_code == 202, response.text
        assert await _response_names(client, admin_auth_header, dataset) == {
            "name": "name"
        }
    finally:
        await _cleanup(session, dataset)


@pytest.mark.parametrize("legacy_route", [False, True], ids=["numbered", "newest"])
async def test_a_legacy_kept_version_has_no_invented_names(
    client, admin_auth_header, test_db_session, legacy_route
):
    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await _replace(session, dataset, admin_id, ["paris"])
        await session.execute(
            text(
                "UPDATE catalog.dataset_versions SET column_info = NULL "
                "WHERE dataset_id = :id"
            ),
            {"id": dataset.id},
        )
        await session.commit()

        if legacy_route:
            await _restore(client, admin_auth_header, session, dataset, 1)
        else:
            response = await _restore_version(client, admin_auth_header, dataset, 1)
            assert response.status_code == 202, response.text
        assert await _response_names(client, admin_auth_header, dataset) == {
            "name": None
        }
        replaced_columns = await _version_columns(session, dataset.id, 2)
        assert replaced_columns is not None
        assert {c["name"]: c.get("source_name") for c in replaced_columns} == {
            "name": "name"
        }
    finally:
        await _cleanup(session, dataset)
