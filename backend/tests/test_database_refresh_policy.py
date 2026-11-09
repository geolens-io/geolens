"""``database_single_read_v1`` and the database source binding fingerprint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.platform.refresh.verification import (
    DATABASE_SINGLE_READ_POLICY,
    canonical_database_source_binding_fingerprint,
    canonical_source_binding_fingerprint,
    geometry_contract,
    verify_database_refresh,
)


def test_database_fingerprint_is_the_name_not_the_server() -> None:
    ref = {"kind": "database", "connection": "gis", "schema": "dbo", "table": "t"}
    fingerprint = canonical_database_source_binding_fingerprint(ref)
    assert canonical_source_binding_fingerprint(ref) == fingerprint
    assert canonical_database_source_binding_fingerprint(
        {**ref, "verification_policy": DATABASE_SINGLE_READ_POLICY}
    ) == (fingerprint)
    assert (
        canonical_database_source_binding_fingerprint({**ref, "table": "u"})
        != fingerprint
    )
    with pytest.raises(ValueError):
        canonical_database_source_binding_fingerprint({**ref, "table": None})


def _verify(**overrides):
    contract = geometry_contract(
        geometry_types=["POINT"], srid=2263, is_3d=False, n_dims=2
    )
    evidence = {
        "source_binding": {
            "connection": "gis",
            "schema": "dbo",
            "table": "t",
            "verification_policy": DATABASE_SINGLE_READ_POLICY,
        },
        "schema_diff": {"row_count_old": 3},
        "fetched_feature_count": 3,
        "content_digest": "d",
        "staged_geometry_type": "MULTIPOINT",
        "staged_srid": 2263,
        "staged_coordinate_dimension": 2,
        "live": contract,
        "staged": contract,
    }
    return verify_database_refresh(**{**evidence, **overrides})


def test_single_read_counts_its_own_rows() -> None:
    verification = _verify()
    assert verification["decision"] == "allowed"
    assert verification["count_status"] == "matched"
    assert verification["source_count"] == 3
    assert verification["review_reasons"] == []
    assert verification[
        "source_binding_fingerprint"
    ] == canonical_database_source_binding_fingerprint(
        {"connection": "gis", "schema": "dbo", "table": "t"}
    )


def test_a_partial_reload_publishes() -> None:
    assert _verify(fetched_feature_count=1)["decision"] == "allowed"


def test_an_empty_read_over_rows_waits_for_review() -> None:
    verification = _verify(fetched_feature_count=0)
    assert verification["decision"] == "blocked"
    assert verification["review_reasons"] == ["empty_result"]


def test_a_removed_column_waits_and_an_acceptance_publishes() -> None:
    diff = {"row_count_old": 3, "columns_removed": [{"name": "label"}]}
    blocked = _verify(schema_diff=diff)
    assert blocked["decision"] == "blocked"
    assert blocked["review_reasons"] == ["destructive_schema_change"]
    run_id = str(uuid.uuid4())
    accepted = _verify(
        schema_diff=diff,
        accepted_fingerprint=blocked["review_fingerprint"],
        accepted_run_id=run_id,
    )
    assert accepted["decision"] == "allowed"
    assert accepted["accepted_blocked_run_id"] == run_id


def test_an_added_column_publishes() -> None:
    diff = {"row_count_old": 3, "columns_added": [{"name": "note"}]}
    assert _verify(schema_diff=diff)["decision"] == "allowed"


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["mixed_srid_database", "missing_crs_database"])
async def test_a_refused_table_is_a_coded_refusal(monkeypatch, code) -> None:
    from app.processing.ingest import tasks_database

    reason = {
        "mixed_srid_database": tasks_database.MIXED_SRID_DATABASE,
        "missing_crs_database": tasks_database.MISSING_CRS_DATABASE,
    }[code]
    refusal = tasks_database.DatabaseRefusal(reason)
    failure = tasks_database._DatabaseRefresh(
        job_id=str(uuid.uuid4()), user_id=str(uuid.uuid4())
    ).classify(refusal)
    assert (failure.error_code, failure.reason, failure.refused) == (
        code,
        reason,
        True,
    )


@pytest.mark.anyio
async def test_a_refresh_of_a_mixed_column_is_refused_before_the_copy(
    monkeypatch,
) -> None:
    from app.platform.database_sources import TableGeometry
    from app.platform.dataset_origin import DatabaseSource
    from app.processing.ingest import tasks_database

    monkeypatch.setattr(
        tasks_database,
        "probe_table_geometry",
        AsyncMock(return_value=TableGeometry(column="g", srid=None, mixed=True)),
    )
    copy = AsyncMock()
    monkeypatch.setattr(tasks_database, "copy_database_table", copy)
    strategy = tasks_database._DatabaseRefresh(
        job_id=str(uuid.uuid4()), user_id=str(uuid.uuid4())
    )
    strategy.source = DatabaseSource("gis", "dbo", "t")
    strategy.stored_srid = 4326
    with pytest.raises(tasks_database.DatabaseRefusal) as raised:
        await strategy.fetch()
    assert raised.value.reason.code == "mixed_srid_database"
    copy.assert_not_awaited()
