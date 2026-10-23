"""ArcGIS coded-value domains become attribute value labels that a refresh keeps current."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import AttributeMetadata
from app.modules.catalog.sources.field_labels import arcgis_field_labels
from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_vector
from app.processing.ingest.tasks_reupload import reupload_service

from tests.factories import get_user_id
from tests.test_service_reupload_3d import _BASE, _WELLS, _refresh, _source

pytestmark = pytest.mark.anyio


def _layer(*coded: tuple[object, str]) -> dict:
    return {
        "fields": [
            {
                "name": "name",
                "type": "esriFieldTypeString",
                "domain": {
                    "type": "codedValue",
                    "name": "Status",
                    "codedValues": [{"name": n, "code": c} for c, n in coded],
                },
            }
        ]
    }


def test_a_coded_value_domain_gives_a_label_per_code_keyed_as_text() -> None:
    meta = _layer((1, "Active"), (2.0, "Retired"), ("X", "Unknown"))
    assert arcgis_field_labels(meta) == {
        "name": {"value_labels": {"1": "Active", "2": "Retired", "X": "Unknown"}}
    }


@pytest.mark.parametrize(
    ("code", "key"),
    [
        (2.5, "2.5"),
        (-0.25, "-0.25"),
        (3.0, "3"),
        (-0.0, "0"),
        (1e-6, "0.000001"),
        (1.5e-6, "0.0000015"),
        (1e16, "10000000000000000"),
        (1000000000000000128.0, "1000000000000000100"),
        (123456789012345680000.0, "123456789012345680000"),
        (1e-7, None),
        (1e21, None),
        (1.5e300, None),
        (float("nan"), None),
        (float("inf"), None),
        (7, "7"),
    ],
)
def test_numeric_codes_are_keyed_as_javascript_writes_them(code, key) -> None:
    labels = arcgis_field_labels(_layer((code, "x")))
    assert labels == ({} if key is None else {"name": {"value_labels": {key: "x"}}})


def test_import_labels_keep_a_prefix_of_columns_within_the_dataset_budget(
    monkeypatch,
) -> None:
    from app.modules.catalog.sources import field_labels

    def field(name: str, labels: int) -> dict:
        return {
            "name": name,
            "type": "esriFieldTypeInteger",
            "domain": {
                "type": "codedValue",
                "codedValues": [
                    {"code": i, "name": f"label {i}"} for i in range(labels)
                ],
            },
        }

    meta = {"fields": [field("a", 10), field("b", 10), field("c", 1)]}
    one = field_labels.value_labels_bytes({str(i): f"label {i}" for i in range(10)})
    monkeypatch.setattr(field_labels, "MAX_DATASET_VALUE_LABEL_BYTES", one + 10)

    labels = arcgis_field_labels(meta)

    # b does not fit, so c is dropped too although it would.
    assert list(labels) == ["a"]
    assert field_labels.value_labels_bytes(labels["a"]["value_labels"]) <= one + 10


def test_the_dataset_label_budget_is_1_mb() -> None:
    from app.modules.catalog.sources.field_labels import MAX_DATASET_VALUE_LABEL_BYTES

    assert MAX_DATASET_VALUE_LABEL_BYTES == 1024 * 1024


def test_string_codes_are_kept_exactly_and_unstorable_ones_are_skipped() -> None:
    meta = _layer(
        (" A", "Padded"),
        ("A", "Plain"),
        ("x" * 501, "Too long"),
        ("bad\x00", "Nul"),
        ("lone\ud800", "Surrogate"),
    )
    assert arcgis_field_labels(meta) == {
        "name": {"value_labels": {" A": "Padded", "A": "Plain"}}
    }


def test_other_domains_and_malformed_entries_give_no_labels() -> None:
    meta = {
        "fields": [
            {"name": "a", "domain": {"type": "range", "range": [0, 5]}},
            {"name": "b", "domain": {"type": "codedValue", "codedValues": []}},
            {
                "name": "c",
                "domain": {
                    "type": "codedValue",
                    "codedValues": [
                        "x",
                        {"code": True, "name": "yes"},
                        {"code": 1},
                        {"code": 2, "name": "  "},
                        {"code": 3, "name": "ok\x00"},
                        {"code": 3, "name": "duplicate"},
                    ],
                },
            },
        ]
    }
    assert arcgis_field_labels(meta) == {"c": {"value_labels": {"3": "ok"}}}


async def test_a_failed_metadata_read_gives_none_not_an_error() -> None:
    with patch(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_layer_meta",
        AsyncMock(side_effect=ValueError("boom")),
    ):
        assert await tasks_vector._fetch_arcgis_field_labels(_BASE, 0, None) is None
    assert await tasks_vector._fetch_arcgis_field_labels(_BASE, None, None) is None


async def _labels(session: AsyncSession, dataset_id) -> dict:
    session.expire_all()
    rows = await session.execute(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
    )
    return {row.field_name: row for row in rows.scalars().all()}


async def _import(session, monkeypatch, field_labels) -> uuid.UUID:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        source_filename="Wells",
        source_url=_BASE,
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": f"Wells {uuid.uuid4().hex[:8]}",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "geometry_type": "Point",
            "field_labels": field_labels,
        },
    )
    session.add(job)
    await session.commit()
    with _source(monkeypatch, _WELLS):
        await tasks_vector.ingest_service.func(
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            source_url=_BASE,
            source_layer="0",
            user_id=str(admin_id),
        )
    await session.refresh(job)
    assert job.status == "complete", job.error_message
    return job.dataset_id


async def test_an_import_stores_the_labels_and_leaves_other_fields_alone(
    test_db_session, monkeypatch
):
    labels = arcgis_field_labels(_layer((1, "Active"), (2, "Retired")))
    dataset_id = await _import(test_db_session, monkeypatch, labels)

    attrs = await _labels(test_db_session, dataset_id)
    assert attrs["name"].value_labels == {"1": "Active", "2": "Retired"}
    assert attrs["name"].user_modified_fields == []
    assert [a for k, a in attrs.items() if k != "name" and a.value_labels] == []


async def test_a_refresh_updates_unedited_labels_and_keeps_edited_ones(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    labels = arcgis_field_labels(_layer((1, "Active")))
    dataset_id = await _import(test_db_session, monkeypatch, labels)

    with patch(
        "app.processing.ingest.tasks_vector._fetch_arcgis_field_labels",
        AsyncMock(return_value=arcgis_field_labels(_layer((1, "In service")))),
    ):
        await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _WELLS)
    attrs = await _labels(test_db_session, dataset_id)
    assert attrs["name"].value_labels == {"1": "In service"}

    attr = attrs["name"]
    response = await client.patch(
        f"/datasets/{dataset_id}/attributes/{attr.id}/",
        json={"value_labels": {"1": "Mine"}},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    assert "value_labels" in response.json()["user_modified_fields"]

    with patch(
        "app.processing.ingest.tasks_vector._fetch_arcgis_field_labels",
        AsyncMock(return_value=arcgis_field_labels(_layer((1, "Gone")))),
    ):
        await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _WELLS)
    attrs = await _labels(test_db_session, dataset_id)
    assert attrs["name"].value_labels == {"1": "Mine"}


async def test_a_refresh_drops_labels_the_source_no_longer_publishes(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    labels = arcgis_field_labels(_layer((1, "Active")))
    dataset_id = await _import(test_db_session, monkeypatch, labels)

    with patch(
        "app.processing.ingest.tasks_vector._fetch_arcgis_field_labels",
        AsyncMock(return_value={}),
    ):
        await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _WELLS)

    assert (await _labels(test_db_session, dataset_id))["name"].value_labels is None


async def test_a_refresh_that_cannot_read_the_metadata_keeps_the_labels(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    labels = arcgis_field_labels(_layer((1, "Active")))
    dataset_id = await _import(test_db_session, monkeypatch, labels)

    with patch(
        "app.processing.ingest.tasks_vector._fetch_arcgis_field_labels",
        AsyncMock(return_value=None),
    ):
        await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _WELLS)

    assert (await _labels(test_db_session, dataset_id))["name"].value_labels == {
        "1": "Active"
    }


async def test_resetting_an_attribute_clears_its_labels_and_the_edit_mark(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _import(
        test_db_session, monkeypatch, arcgis_field_labels(_layer((1, "Active")))
    )
    attr = (await _labels(test_db_session, dataset_id))["name"]
    await client.patch(
        f"/datasets/{dataset_id}/attributes/{attr.id}/",
        json={"value_labels": {"1": "Mine"}},
        headers=admin_auth_header,
    )

    response = await client.post(
        f"/datasets/{dataset_id}/attributes/{attr.id}/reset/",
        headers=admin_auth_header,
    )

    assert response.status_code == 200, response.text
    assert response.json()["value_labels"] is None
    assert response.json()["user_modified_fields"] == []


@pytest.mark.parametrize(
    "labels",
    [
        {str(i): "x" for i in range(5001)},
        {"1": "x" * 501},
        {"1": "bad\x00"},
        {"a" * 501: "x"},
    ],
)
async def test_the_edit_endpoint_bounds_what_it_stores(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch, labels
):
    dataset_id = await _import(
        test_db_session, monkeypatch, arcgis_field_labels(_layer((1, "Active")))
    )
    attr = (await _labels(test_db_session, dataset_id))["name"]

    response = await client.patch(
        f"/datasets/{dataset_id}/attributes/{attr.id}/",
        json={"value_labels": labels},
        headers=admin_auth_header,
    )

    assert response.status_code == 422


async def test_a_reupload_from_a_service_without_coded_labels_clears_unedited_labels(
    test_db_session, monkeypatch
):
    dataset_id = await _import(
        test_db_session, monkeypatch, arcgis_field_labels(_layer((1, "Active")))
    )
    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Wells",
        source_url=_BASE,
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "WFS",
            "layer_id": "0",
            "source_type": "service_url",
        },
    )
    test_db_session.add(job)
    await test_db_session.commit()

    with _source(monkeypatch, _WELLS):
        await reupload_service.func(
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            dataset_id=str(dataset_id),
            source_url=_BASE,
            source_layer="0",
            user_id=str(admin_id),
        )

    await test_db_session.refresh(job)
    assert job.status == "complete", job.error_message
    assert (await _labels(test_db_session, dataset_id))["name"].value_labels is None


async def test_a_patch_that_passes_the_dataset_budget_is_refused(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    from app.modules.catalog.datasets.domain import value_label_budget

    dataset_id = await _import(
        test_db_session, monkeypatch, arcgis_field_labels(_layer((1, "Active")))
    )
    attrs = await _labels(test_db_session, dataset_id)
    other = (
        attrs["geom"]
        if "geom" in attrs
        else next(a for k, a in attrs.items() if k != "name")
    )
    big = {str(i): "x" * 20 for i in range(10)}
    monkeypatch.setattr(
        value_label_budget,
        "MAX_DATASET_VALUE_LABEL_BYTES",
        2 * value_label_budget.value_labels_bytes(big) - 1,
    )

    async def patch(attr, labels):
        return await client.patch(
            f"/datasets/{dataset_id}/attributes/{attr.id}/",
            json={"value_labels": labels},
            headers=admin_auth_header,
        )

    # Replacing the column's own labels does not count them twice.
    assert (await patch(attrs["name"], big)).status_code == 200
    assert (await patch(attrs["name"], big)).status_code == 200
    refused = await patch(other, big)

    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "Value labels for this dataset are over the 1 MB limit."
    )
    assert (await _labels(test_db_session, dataset_id))[
        other.field_name
    ].value_labels is None
