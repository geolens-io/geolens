"""Manifest version 2 maps: the request shape, map keys and the dry run.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, patch

import json

import pytest
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import event, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.identity import IdentitySnapshot
from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.schemas import _MAX_LAYERS_PER_MAP
from app.platform.extensions import get_processing_port
from app.platform.jobs.models import IngestJob
from app.platform.request_credential import ApiKeyCredential, record_api_key
from app.processing.ingest.manifest_schemas import (
    MAX_MANIFEST_MAP_LAYERS,
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestApplyResponse,
    ManifestMessage,
)
from app.processing.ingest.manifest_maps import check_manifest_maps
from app.processing.ingest.manifest_service import apply_manifest
from tests.factories import create_dataset, create_user

pytestmark = pytest.mark.anyio

_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
_UNKNOWN_DATASET_ID = "00000000-0000-4000-8000-000000000001"
_COLUMNS = [
    {"name": "park_type", "type": "text", "source_name": "PARK_TYPE"},
    {"name": "park_name", "type": "text", "source_name": "PARK_NAME"},
]


def _layer(key: str = "parks", **fields) -> dict:
    return {"key": key, **fields}


def _map(key: str = "qgis-map-parks", *layers: dict, **fields) -> dict:
    """A map entry; with no layers given it gets one on a dataset nobody has."""
    layers = layers or (_layer("only", dataset_id=_UNKNOWN_DATASET_ID),)
    return {"key": key, "name": "Springfield parks", "layers": list(layers), **fields}


def _body(*maps: dict, dry_run: bool = True, datasets=(), version="2") -> dict:
    body = {
        "manifest_version": version,
        "catalog": {"title": "Parks project"},
        "datasets": list(datasets),
        "dry_run": dry_run,
        "maps": list(maps),
    }
    if version == "2":
        body["client"] = {"id": "geolens-qgis", "version": "0.2.0"}
    return body


def _request(*maps: dict, dry_run: bool = True) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(_body(*maps, dry_run=dry_run))


def _dataset_entry() -> dict:
    return {
        "key": "roads",
        "title": "Roads",
        "sources": [{"type": "vector", "uri": "https://example.com/roads.fgb"}],
        "publication": {"intent": "draft"},
    }


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_version_2_takes_maps_without_datasets():
    request = _request(_map("qgis-map-a", _layer(dataset_id=_UNKNOWN_DATASET_ID)))
    assert request.datasets == []
    assert request.maps[0].layers[0].dataset_id == uuid.UUID(_UNKNOWN_DATASET_ID)


def test_version_2_needs_a_dataset_or_a_map():
    with pytest.raises(ValidationError, match="at least one dataset or map"):
        _request()


def test_version_1_refuses_maps():
    with pytest.raises(ValidationError, match="maps require manifest_version '2'"):
        ManifestApplyRequest.model_validate(
            _body(_map(), datasets=[_dataset_entry()], version="1")
        )


def test_the_published_schema_does_not_require_datasets():
    assert ManifestApplyRequest.model_json_schema()["required"] == [
        "manifest_version",
        "catalog",
    ]
    openapi = json.loads((Path(__file__).parents[1] / "openapi.json").read_text())
    schema = openapi["components"]["schemas"]["ManifestApplyRequest"]
    assert "datasets" not in schema["required"]


def test_version_2_may_leave_out_datasets():
    body = _body(_map("qgis-map-a", _layer(dataset_id=_UNKNOWN_DATASET_ID)))
    del body["datasets"]
    assert ManifestApplyRequest.model_validate(body).datasets == []


def test_version_1_answers_missing_datasets_as_before():
    body = _body(version="1")
    del body["maps"], body["datasets"]
    with pytest.raises(ValidationError) as caught:
        ManifestApplyRequest.model_validate(body)
    [error] = caught.value.errors(include_url=False)
    assert (error["type"], error["loc"], error["msg"]) == (
        "missing",
        ("datasets",),
        "Field required",
    )


_CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures/publish_contract_v2.json").read_text()
)
_MAPS_ONLY_EXAMPLES = {
    "maps_only_by_dataset_id",
    "minimal_map",
    "null_label_and_popup_config",
}


@pytest.mark.parametrize("example", _CONTRACT["valid"], ids=lambda e: e["name"])
def test_every_valid_contract_example_parses(example):
    manifest = example["manifest"]
    if manifest.get("maps") and not manifest.get("dry_run"):
        # Maps are checked only in a dry run for now, so the example as
        # written is refused and its dry run parses.
        with pytest.raises(ValidationError, match="dry_run true"):
            ManifestApplyRequest.model_validate(manifest)
        manifest = {**manifest, "dry_run": True}
    ManifestApplyRequest.model_validate(manifest)


@pytest.mark.parametrize(
    "example",
    [e for e in _CONTRACT["valid"] if e["name"] in _MAPS_ONLY_EXAMPLES],
    ids=lambda e: e["name"],
)
async def test_maps_only_contract_examples_run_as_a_dry_run(
    test_db_session, clean_tables, example
):
    assert "datasets" not in example["manifest"]
    admin = await _admin(test_db_session)
    request = ManifestApplyRequest.model_validate(
        {**example["manifest"], "dry_run": True}
    )

    response = await apply_manifest(test_db_session, request, admin, _http_request())

    assert response.results == []
    assert [r.map_key for r in response.maps] == [
        m["key"] for m in example["manifest"]["maps"]
    ]


def test_version_1_answers_an_empty_dataset_list_as_before():
    body = _body(version="1")
    del body["maps"]
    with pytest.raises(ValidationError) as caught:
        ManifestApplyRequest.model_validate(body)
    [error] = caught.value.errors(include_url=False)
    assert error["type"] == "too_short"
    assert error["loc"] == ("datasets",)
    assert error["msg"] == "List should have at least 1 item after validation, not 0"
    assert error["ctx"] == {"field_type": "List", "min_length": 1, "actual_length": 0}


@pytest.mark.parametrize(
    "layer",
    [
        _layer(),
        _layer(dataset_key="roads", dataset_id=_UNKNOWN_DATASET_ID),
    ],
)
def test_a_layer_names_exactly_one_dataset(layer):
    with pytest.raises(ValidationError, match="exactly one of dataset_key"):
        _request(_map("qgis-map-a", layer))


def test_layer_keys_are_unique_within_a_map_only():
    with pytest.raises(ValidationError, match="duplicate layer key"):
        _request(
            _map(
                "qgis-map-a",
                _layer("parks", dataset_key="parks"),
                _layer("parks", dataset_key="trails"),
            )
        )
    _request(
        _map("qgis-map-a", _layer("parks", dataset_key="parks")),
        _map("qgis-map-b", _layer("parks", dataset_key="parks")),
    )


def test_map_keys_are_unique_in_a_request():
    with pytest.raises(ValidationError, match="duplicate map key"):
        _request(_map("qgis-map-a"), _map("qgis-map-a"))


@pytest.mark.parametrize(
    ("map_key", "layer_key"),
    [("Upper", "parks"), ("qgis-map-a", "Upper"), ("-lead", "parks"), ("a" * 129, "p")],
)
def test_keys_use_the_dataset_key_pattern(map_key, layer_key):
    with pytest.raises(ValidationError):
        _request(_map(map_key, _layer(layer_key, dataset_key="parks")))


def test_layer_count_is_the_map_schemas_limit():
    assert MAX_MANIFEST_MAP_LAYERS == _MAX_LAYERS_PER_MAP == 200
    layers = [_layer(f"l{i}", dataset_key="parks") for i in range(200)]
    _request(_map("qgis-map-a", *layers))
    with pytest.raises(ValidationError):
        _request(_map("qgis-map-a", *layers, _layer("l200", dataset_key="parks")))


def test_a_request_takes_at_most_100_maps():
    _request(*(_map(f"m{i}") for i in range(100)))
    with pytest.raises(ValidationError):
        _request(*(_map(f"m{i}") for i in range(101)))


@pytest.mark.parametrize(
    "thumbnail",
    [
        "data:image/png;base64," + "A" * 99_979,
        "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "https://example.com/thumb.png",
        "data:image/png;base64,not base64!",
    ],
)
def test_the_thumbnail_is_a_bounded_png_or_jpeg_data_uri(thumbnail):
    with pytest.raises(ValidationError):
        _request(_map("qgis-map-a", thumbnail=thumbnail))


def test_a_padded_thumbnail_under_the_limit_is_accepted():
    _request(_map("qgis-map-a", thumbnail=_PNG))
    _request(_map("qgis-map-a", thumbnail="data:image/jpeg;base64," + "A" * 99_976))


@pytest.mark.parametrize(
    "field",
    [
        {"view": {"center": [181, 0], "zoom": 3}},
        {"view": {"center": [0, 0], "zoom": 25}},
        {"view": {"center": [0, 0], "zoom": 3, "pitch": 86}},
        {"styling": "overwrite"},
        {"visibility": "restricted"},
        {"name": ""},
        {"name": "nul\x00byte"},
        {"loss_report": {"items": [{"path": "layers[0]", "kind": ""}]}},
        {"loss_report": {"items": [{"path": "p", "kind": "two\nlines"}]}},
        {"loss_report": {"items": [{"path": "p", "kind": "k", "detail": "x\n---\ny"}]}},
        {"loss_report": {"items": [{"path": "p\r", "kind": "k"}]}},
        {"loss_report": {"items": [{"path": "p", "kind": "k", "detail": "a\u2028b"}]}},
    ],
)
def test_map_fields_are_bounded(field):
    with pytest.raises(ValidationError):
        _request(_map("qgis-map-a", **field))


def test_a_zoom_range_is_taken_as_sent():
    """The contract bounds each zoom, not their order."""
    _request(_map("qgis-map-a", _layer(dataset_key="parks", min_zoom=10, max_zoom=4)))


def test_a_version_1_response_has_no_maps_key_and_messages_leave_out_layer():
    response = ManifestApplyResponse(accepted=True, dry_run=False, results=[])
    assert "maps" not in response.model_dump(mode="json")
    message = ManifestMessage(code="A020", severity="warning", message="m")
    assert "layer" not in message.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


# Snapshots: a dry run rolls the session back, which expires ORM users.
async def _admin(session) -> IdentitySnapshot:
    return IdentitySnapshot.of(
        (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
    )


async def _person(client, session, admin_headers, role: str = "editor"):
    headers, user_id = await create_user(client, admin_headers, role)
    return IdentitySnapshot.of(await session.get(User, uuid.UUID(user_id))), headers


async def _dataset(session, owner_id, *, visibility="public") -> uuid.UUID:
    dataset = await create_dataset(
        session,
        created_by=owner_id,
        visibility=visibility,
        column_info=[dict(column) for column in _COLUMNS],
    )
    await session.commit()
    return dataset.id


async def _published_under(
    session, owner_id, key: str, dataset_id, *, status="complete"
):
    session.add(
        IngestJob(
            dataset_id=dataset_id,
            source_filename="parks.fgb",
            created_by=owner_id,
            status=status,
            completed_at=datetime.now(timezone.utc) if status == "complete" else None,
            user_metadata={"manifest_key": key},
        )
    )
    await session.commit()


async def _keyed_map(session, owner_id, key: str, dataset_id, *, layer_key="parks"):
    map_obj = Map(name="Original", created_by=owner_id, manifest_key=key)
    session.add(map_obj)
    await session.flush()
    session.add(
        MapLayer(map_id=map_obj.id, dataset_id=dataset_id, manifest_key=layer_key)
    )
    await session.commit()
    return map_obj.id


async def _dry_run(session, user, *maps: dict):
    return await apply_manifest(session, _request(*maps), user, _http_request())


def _codes(result) -> list[tuple[str, str, str | None]]:
    return [(m.code, m.severity, m.layer) for m in result.messages]


async def test_a_readable_dataset_by_id_or_key_checks_clean(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)

    response = await _dry_run(
        test_db_session,
        admin,
        _map(
            "qgis-map-parks",
            _layer("by-id", dataset_id=str(dataset_id)),
            _layer("by-key", dataset_key="qgis-parks"),
            basemap_style="openfreemap-positron",
            thumbnail=_PNG,
        ),
    )

    assert response.accepted is True
    assert response.dry_run is True
    [result] = response.maps
    assert (result.map_key, result.action, result.map_id) == (
        "qgis-map-parks",
        "create",
        None,
    )
    assert result.messages == []


async def test_a_map_key_the_caller_owns_is_an_update(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    map_id = await _keyed_map(test_db_session, admin.id, "qgis-map-own", dataset_id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-own", _layer(dataset_id=str(dataset_id))),
        )
    ).maps

    assert (result.action, result.map_id, result.messages) == ("update", map_id, [])


@pytest.mark.parametrize("visibility", ["private", "public"])
async def test_another_users_map_key_answers_a050_and_nothing_else(
    client, test_db_session, admin_auth_header, clean_tables, visibility
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, admin.id)
    secret = await _keyed_map(test_db_session, admin.id, "qgis-map-taken", dataset_id)
    await test_db_session.execute(
        update(Map)
        .where(Map.id == secret)
        .values(name="Board salaries", visibility=visibility)
    )
    await test_db_session.commit()

    response = await _dry_run(
        test_db_session,
        editor,
        _map("qgis-map-taken", _layer(dataset_id=str(dataset_id))),
    )

    [result] = response.maps
    assert response.accepted is False
    assert (result.action, result.map_id) == ("error", None)
    assert _codes(result) == [("A050", "error", None)]
    dumped = response.model_dump_json()
    assert str(secret) not in dumped
    assert "Board salaries" not in dumped


async def test_an_unknown_dataset_answers_a052(test_db_session, clean_tables):
    admin = await _admin(test_db_session)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer("by-id", dataset_id=_UNKNOWN_DATASET_ID),
                _layer("by-key", dataset_key="never-published"),
            ),
        )
    ).maps

    assert result.action == "error"
    assert _codes(result) == [
        ("A052", "error", "by-id"),
        ("A052", "error", "by-key"),
    ]


async def test_a_dataset_whose_job_is_not_complete_answers_a052(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(
        test_db_session, admin.id, "qgis-running", dataset_id, status="running"
    )

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_key="qgis-running")),
        )
    ).maps

    assert _codes(result) == [("A052", "error", "parks")]


class _Statements:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args) -> None:
        self.count += 1


async def _answer_and_statements(session, user, layer: dict):
    statements = _Statements()
    event.listen(Engine, "before_cursor_execute", statements)
    try:
        response = await _dry_run(session, user, _map("qgis-map-a", layer))
    finally:
        event.remove(Engine, "before_cursor_execute", statements)
    [result] = response.maps
    return [m.model_dump() for m in result.messages], statements.count


async def test_an_unreadable_dataset_answers_exactly_like_a_missing_one(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    private_id = await _dataset(test_db_session, admin.id, visibility="private")
    await _published_under(test_db_session, admin.id, "admin-private", private_id)

    # Settings the first check reads are cached afterwards.
    await _answer_and_statements(test_db_session, editor, _layer(dataset_key="warm"))
    for unreadable, missing in (
        (
            _layer(dataset_id=str(private_id)),
            _layer(dataset_id=_UNKNOWN_DATASET_ID),
        ),
        (_layer(dataset_key="admin-private"), _layer(dataset_key="never-published")),
    ):
        hidden = await _answer_and_statements(test_db_session, editor, unreadable)
        absent = await _answer_and_statements(test_db_session, editor, missing)
        assert hidden[0] == absent[0]
        assert [m["code"] for m in hidden[0]] == ["A052"]
        # No lookup runs only for a dataset that exists.
        assert hidden[1] == absent[1]

    # The owner reads it, so the same layer checks clean.
    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_key="admin-private")),
        )
    ).maps
    assert result.messages == []


async def test_unknown_style_and_label_keys_are_dropped_with_a062(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(
                    dataset_id=str(dataset_id),
                    style_config={
                        "mode": "categorical",
                        "column": "PARK_TYPE",
                        "glow": 1,
                    },
                    label_config={"column": "PARK_NAME", "sparkle": True, "zz": 0},
                ),
            ),
        )
    ).maps

    assert result.action == "create"
    assert _codes(result) == [("A062", "info", "parks"), ("A062", "info", "parks")]
    assert result.messages[0].message.endswith("dropped: glow.")
    assert result.messages[1].message.endswith("dropped: sparkle, zz.")


async def test_a_column_the_dataset_lacks_is_a063(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(
                    dataset_id=str(dataset_id),
                    style_config={"mode": "categorical", "column": "PARK_TYPE"},
                    paint={
                        "fill-color": [
                            "match",
                            ["get", "OWNER"],
                            "city",
                            "#4daf4a",
                            "#cccccc",
                        ]
                    },
                    filter=["==", ["get", "STATUS"], "open"],
                    label_config={"column": "PARK_NAME"},
                    popup_config={
                        "enabled": True,
                        "visible_fields": ["PARK_NAME", "ACRES"],
                    },
                ),
            ),
        )
    ).maps

    assert result.action == "create"
    assert _codes(result) == [("A063", "warning", "parks")]
    assert result.messages[0].message == (
        "The dataset has no single column named ACRES, OWNER, STATUS."
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"label_config": {"fontSize": 9999}},
        {"popup_config": {"enabled": True, "unknown": 1}},
        {"paint": {"_private": 1}},
        {"filter": [1, "a"]},
        {"style_config": {"column": "x" * 70_000}},
    ],
)
async def test_styling_the_map_schema_refuses_is_a099(
    test_db_session, clean_tables, fields
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), **fields)),
        )
    ).maps

    assert result.action == "error"
    assert _codes(result) == [("A099", "error", "parks")]
    assert result.messages[0].message.startswith("Layer parks can't be saved: ")


async def test_an_unknown_basemap_is_refused(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(dataset_id=str(dataset_id)),
                basemap_style="no-such-basemap",
            ),
        )
    ).maps

    assert result.action == "error"
    assert _codes(result) == [("A099", "error", None)]


async def test_a_dry_run_writes_nothing_the_check_touched(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    map_id = await _keyed_map(test_db_session, admin.id, "qgis-map-own", dataset_id)
    real = get_processing_port()

    class Touching:
        def __getattr__(self, name):
            return getattr(real, name)

        async def apply_manifest_maps(self, session, maps, user, **kwargs):
            await session.execute(
                update(Map).where(Map.id == map_id).values(name="Touched")
            )
            return await real.apply_manifest_maps(session, maps, user, **kwargs)

    with patch(
        "app.processing.ingest.manifest_maps.get_processing_port",
        return_value=Touching(),
    ):
        [result] = (
            await _dry_run(
                test_db_session,
                admin,
                _map("qgis-map-own", _layer(dataset_id=str(dataset_id))),
            )
        ).maps

    assert result.action == "update"
    name = await test_db_session.scalar(select(Map.name).where(Map.id == map_id))
    assert name == "Original"


@pytest.mark.parametrize("with_datasets", [False, True])
async def test_maps_outside_a_dry_run_are_refused_before_anything_is_applied(
    client, test_db_session, admin_auth_header, clean_tables, with_datasets
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    datasets = (
        [{**_local_dataset_entry("qgis-parks"), "collection": {"name": "Parks set"}}]
        if with_datasets
        else []
    )
    _stage_fixture()

    response = await client.post(
        "/ingest/manifest/apply",
        json=_body(
            _map("qgis-map-new", _layer(dataset_id=str(dataset_id))),
            dry_run=False,
            datasets=datasets,
        ),
        headers=admin_auth_header,
    )

    assert response.status_code == 422, response.text
    assert "dry_run" in response.text
    for model in (IngestJob, Collection, Map):
        assert (
            await test_db_session.scalar(select(func.count()).select_from(model)) == 0
        )


async def test_the_api_returns_map_results_with_layer_keys(
    client, editor_auth_header, clean_tables
):
    response = await client.post(
        "/ingest/manifest/apply",
        json=_body(_map("qgis-map-a", _layer(dataset_id=_UNKNOWN_DATASET_ID))),
        headers=editor_auth_header,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"] == []
    [result] = body["maps"]
    assert result["action"] == "error"
    assert [(m["code"], m["layer"]) for m in result["messages"]] == [("A052", "parks")]


# ---------------------------------------------------------------------------
# Keys on the map rows
# ---------------------------------------------------------------------------


async def test_a_second_users_map_cannot_take_an_existing_key(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _keyed_map(test_db_session, admin.id, "qgis-map-taken", dataset_id)

    test_db_session.add(
        Map(name="Mine", created_by=editor.id, manifest_key="qgis-map-taken")
    )
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


async def test_a_layer_key_is_unique_within_its_map_only(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    first = await _keyed_map(test_db_session, admin.id, "qgis-map-a", dataset_id)
    await _keyed_map(test_db_session, admin.id, "qgis-map-b", dataset_id)

    test_db_session.add(
        MapLayer(map_id=first, dataset_id=dataset_id, manifest_key="parks")
    )
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()

    # Builder layers carry no key, any number of them.
    for _ in range(2):
        test_db_session.add(MapLayer(map_id=first, dataset_id=dataset_id))
    await test_db_session.commit()


async def test_a_duplicate_starts_without_keys(
    client, test_db_session, admin_auth_header, clean_tables
):
    editor, headers = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    map_id = await _keyed_map(test_db_session, editor.id, "qgis-map-own", dataset_id)

    response = await client.post(f"/maps/{map_id}/duplicate/", headers=headers)

    assert response.status_code == 201, response.text
    copy_id = uuid.UUID(response.json()["id"])
    test_db_session.expire_all()
    assert (
        await test_db_session.scalar(select(Map.manifest_key).where(Map.id == copy_id))
        is None
    )
    layer_keys = (
        await test_db_session.scalars(
            select(MapLayer.manifest_key).where(MapLayer.map_id == copy_id)
        )
    ).all()
    assert layer_keys == [None]
    assert (
        await test_db_session.scalar(select(Map.manifest_key).where(Map.id == map_id))
        == "qgis-map-own"
    )


async def test_a_transfer_keeps_the_keys_and_the_previous_owner_gets_a050(
    client, test_db_session, admin_auth_header, clean_tables
):
    previous, _ = await _person(client, test_db_session, admin_auth_header)
    successor, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, previous.id)
    map_id = await _keyed_map(test_db_session, previous.id, "qgis-map-own", dataset_id)

    response = await client.patch(
        f"/maps/{map_id}",
        json={"owner_id": str(successor.id)},
        headers=admin_auth_header,
    )

    assert response.status_code == 200, response.text
    test_db_session.expire_all()
    assert (
        await test_db_session.scalar(select(Map.manifest_key).where(Map.id == map_id))
        == "qgis-map-own"
    )
    assert (
        await test_db_session.scalars(
            select(MapLayer.manifest_key).where(MapLayer.map_id == map_id)
        )
    ).all() == ["parks"]

    republish = _map("qgis-map-own", _layer(dataset_id=str(dataset_id)))
    [refused] = (await _dry_run(test_db_session, previous, republish)).maps
    assert (refused.action, refused.map_id) == ("error", None)
    assert _codes(refused) == [("A050", "error", None)]
    [allowed] = (await _dry_run(test_db_session, successor, republish)).maps
    assert (allowed.action, allowed.map_id) == ("update", map_id)


# ---------------------------------------------------------------------------
# Datasets the same request publishes
# ---------------------------------------------------------------------------

_FIXTURE = "tests/fixtures/ingest/basic_attrs.geojson"


def _local_dataset_entry(key: str) -> dict:
    return {
        "key": key,
        "title": "Parks",
        "sources": [{"type": "vector", "uri": _FIXTURE, "format": "geojson"}],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": "published"},
    }


def _stage_fixture() -> None:
    destination = Path(settings.upload_staging_dir) / _FIXTURE
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", destination)


def _accepted(request: ManifestApplyRequest) -> list[ManifestApplyEntryResult]:
    """Dataset results as a dry run reports entries it would create."""
    return [
        ManifestApplyEntryResult(dataset_key=entry.key, action="create", message="m")
        for entry in request.datasets
    ]


def _publish_request(dataset_keys: list[str], *maps: dict) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        _body(*maps, datasets=[_local_dataset_entry(key) for key in dataset_keys])
    )


_STYLED_LAYER = {
    "style_config": {"mode": "categorical", "column": "PARK_TYPE", "glow": 1},
    "paint": {"fill-color": ["match", ["get", "OWNER"], "city", "#4daf4a", "#ccc"]},
}


async def test_a_first_publish_dry_run_has_no_a052_or_a063_for_its_own_datasets(
    test_db_session, clean_tables
):
    _stage_fixture()
    admin = await _admin(test_db_session)
    request = _publish_request(
        ["qgis-parks"],
        _map("qgis-map-parks", _layer(dataset_key="qgis-parks", **_STYLED_LAYER)),
    )

    response = await apply_manifest(test_db_session, request, admin, _http_request())

    [dataset] = response.results
    assert (dataset.dataset_key, dataset.action) == ("qgis-parks", "create")
    [result] = response.maps
    assert result.action == "create"
    assert _codes(result) == [("A062", "info", "parks")]
    assert response.accepted is True
    assert await test_db_session.scalar(select(func.count()).select_from(Map)) == 0


async def test_a_key_the_request_does_not_publish_still_answers_a052(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    request = _publish_request(
        ["qgis-trails"],
        _map("qgis-map-parks", _layer(dataset_key="qgis-parks", **_STYLED_LAYER)),
    )

    [result] = await check_manifest_maps(
        test_db_session, request, admin, _accepted(request)
    )

    assert _codes(result) == [("A052", "error", "parks"), ("A062", "info", "parks")]


async def test_a_republished_dataset_the_caller_reads_gets_the_column_check(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    request = _publish_request(
        ["qgis-parks"],
        _map("qgis-map-parks", _layer(dataset_key="qgis-parks", **_STYLED_LAYER)),
    )

    [result] = await check_manifest_maps(
        test_db_session, request, admin, _accepted(request)
    )

    assert _codes(result) == [("A062", "info", "parks"), ("A063", "warning", "parks")]
    assert result.messages[1].message == "The dataset has no single column named OWNER."


async def _maps_answer_and_statements(session, user, request):
    statements = _Statements()
    event.listen(Engine, "before_cursor_execute", statements)
    try:
        [result] = await check_manifest_maps(session, request, user, _accepted(request))
    finally:
        event.remove(Engine, "before_cursor_execute", statements)
    return [m.model_dump() for m in result.messages], statements.count


async def test_a_listed_key_on_an_unreadable_dataset_reads_like_a_new_one(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    private_id = await _dataset(test_db_session, admin.id, visibility="private")
    await _published_under(test_db_session, admin.id, "admin-private", private_id)

    def request(key: str) -> ManifestApplyRequest:
        return _publish_request(
            [key], _map("qgis-map-a", _layer(dataset_key=key, **_STYLED_LAYER))
        )

    await _maps_answer_and_statements(test_db_session, editor, request("warm"))
    hidden = await _maps_answer_and_statements(
        test_db_session, editor, request("admin-private")
    )
    absent = await _maps_answer_and_statements(
        test_db_session, editor, request("never-published")
    )

    assert hidden == absent
    assert [m["code"] for m in hidden[0]] == ["A062"]


async def test_an_admins_publish_key_reads_and_writes_like_its_owner(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    editor, _ = await _person(client, test_db_session, admin_auth_header)
    private_id = await _dataset(test_db_session, editor.id, visibility="private")
    await _published_under(test_db_session, editor.id, "editor-private", private_id)
    await _keyed_map(test_db_session, editor.id, "qgis-map-editor", private_id)
    record_api_key(
        test_db_session,
        ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
    )
    request = _request(
        _map(
            "qgis-map-editor",
            _layer("by-id", dataset_id=str(private_id)),
            _layer("by-key", dataset_key="editor-private"),
        )
    )

    [result] = await check_manifest_maps(
        test_db_session, request, admin, _accepted(request)
    )

    assert (result.action, result.map_id) == ("error", None)
    assert _codes(result) == [
        ("A050", "error", None),
        ("A052", "error", "by-id"),
        ("A052", "error", "by-key"),
    ]


async def test_messages_list_a_bounded_number_of_caller_names(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    unknown = {f"{i:03d}" + "k" * 1000: 1 for i in range(50)}

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(
                    dataset_id=str(dataset_id),
                    style_config={"mode": "categorical", **unknown},
                    popup_config={"enabled": True, **unknown},
                ),
            ),
        )
    ).maps

    dropped, refused = result.messages
    assert dropped.code == "A062"
    assert dropped.message.endswith(" and 30 more.")
    assert "000" + "k" * 58 + "..." in dropped.message
    assert len(dropped.message) < 2000
    assert refused.code == "A099"
    assert len(refused.message) < 2500


async def test_a_layer_naming_a_refused_dataset_entry_answers_a052(
    test_db_session, clean_tables
):
    _stage_fixture()
    admin = await _admin(test_db_session)
    request = ManifestApplyRequest.model_validate(
        _body(
            _map("qgis-map-parks", _layer(dataset_key="qgis-parks")),
            datasets=[
                {
                    **_local_dataset_entry("qgis-parks"),
                    "publication": {"intent": "no-such-status"},
                }
            ],
        )
    )

    response = await apply_manifest(test_db_session, request, admin, _http_request())

    [dataset] = response.results
    assert dataset.action == "error"
    [result] = response.maps
    assert result.action == "error"
    assert _codes(result) == [("A052", "error", "parks")]
    assert response.accepted is False


_MATCH_ON_A_GET_LABEL = [
    "match",
    ["get", "PARK_TYPE"],
    ["get", "has"],
    "#4daf4a",
    "#cccccc",
]
_DICT_IN_A_LITERAL = ["get", "radius", ["at", 0, ["literal", [{"radius": 5}]]]]


@pytest.mark.parametrize(
    "paint",
    [
        {"fill-color": _MATCH_ON_A_GET_LABEL},
        {"fill-color": ["in", ["get", "PARK_TYPE"], ["literal", ["get", "x"]]]},
        {"circle-radius": _DICT_IN_A_LITERAL},
    ],
)
async def test_expression_data_is_not_read_as_columns(
    test_db_session, clean_tables, paint
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), paint=paint)),
        )
    ).maps

    assert (result.action, result.messages) == ("create", [])


async def test_a_dict_literal_in_one_map_leaves_every_map_clean(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    response = await _dry_run(
        test_db_session,
        admin,
        _map(
            "qgis-map-a",
            _layer(
                dataset_id=str(dataset_id), paint={"circle-radius": _DICT_IN_A_LITERAL}
            ),
        ),
        _map("qgis-map-b", _layer(dataset_id=str(dataset_id))),
    )

    assert [(r.map_key, r.action, r.messages) for r in response.maps] == [
        ("qgis-map-a", "create", []),
        ("qgis-map-b", "create", []),
    ]


async def test_a_missing_column_in_a_match_input_is_a063(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    paint = {"fill-color": ["match", ["get", "OWNER"], "city", "#4daf4a", "#ccc"]}

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), paint=paint)),
        )
    ).maps

    assert _codes(result) == [("A063", "warning", "parks")]
    assert result.messages[0].message.endswith("named OWNER.")


async def test_one_maps_unexpected_failure_fails_only_that_map(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    from app.modules.catalog.maps import manifest_apply

    real = manifest_apply._check_map

    async def failing_for_a(session, entry, *args):
        if entry.key == "qgis-map-a":
            raise RuntimeError("boom")
        return await real(session, entry, *args)

    with patch.object(manifest_apply, "_check_map", failing_for_a):
        response = await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id))),
            _map("qgis-map-b", _layer(dataset_id=str(dataset_id))),
        )

    failed, fine = response.maps
    assert (failed.action, _codes(failed)) == ("error", [("A099", "error", None)])
    assert (fine.action, fine.messages) == ("create", [])


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"popup_config": {"enabled": True, "expression": "{MISSING}"}}, "MISSING"),
        ({"popup_config": {"enabled": True, "expression": "{PARK_NAME}"}}, None),
        (
            {
                "style_config": {
                    "symbol": {
                        "categoryColumn": "MISSING",
                        "categories": [{"value": "a", "icon": "marker"}],
                    }
                }
            },
            "MISSING",
        ),
        (
            {
                "style_config": {
                    "builder": {
                        "symbol": {
                            "categoryColumn": "MISSING",
                            "categories": [{"value": "a", "icon": "marker"}],
                        }
                    }
                }
            },
            "MISSING",
        ),
        (
            {
                "style_config": {
                    "symbol": {
                        "categoryColumn": "PARK_TYPE",
                        "categories": [{"value": "a", "icon": "marker"}],
                    }
                }
            },
            None,
        ),
        # The export reads the column only when a category survives into the
        # icon match.
        (
            {
                "style_config": {
                    "symbol": {"categoryColumn": "MISSING", "categories": []}
                }
            },
            None,
        ),
        (
            {
                "style_config": {
                    "symbol": {
                        "categoryColumn": "MISSING",
                        "categories": [
                            {"value": None, "icon": "marker"},
                            {"value": "a", "icon": None},
                        ],
                    }
                }
            },
            None,
        ),
    ],
)
async def test_popup_placeholders_and_symbol_categories_are_checked(
    test_db_session, clean_tables, fields, missing
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), **fields)),
        )
    ).maps

    if missing is None:
        assert result.messages == []
    else:
        assert _codes(result) == [("A063", "warning", "parks")]
        assert result.messages[0].message.endswith(f"named {missing}.")


_STOPS = [[1, "#000"], [2, "#fff"]]


@pytest.mark.parametrize(
    "fields",
    [
        {"paint": {"fill-color": {"property": "{c}", "stops": _STOPS}}},
        {
            "paint": {
                "fill-color": {
                    "property": "{c}",
                    "type": "categorical",
                    "stops": _STOPS,
                    "default": "#ccc",
                }
            }
        },
        {"layout": {"icon-size": {"property": "{c}", "stops": _STOPS}}},
        {"filter": ["!has", "{c}"]},
        {"filter": ["!in", "{c}", "a", "b"]},
        {"filter": ["==", "{c}", "a"]},
        {"filter": ["<", "{c}", 3]},
        {"filter": ["none", ["==", "{c}", 1]]},
        {"filter": ["all", ["has", "{c}"], ["==", "$type", "Point"]]},
        {"label_config": {"column": "PARK_NAME", "fontSize": ["get", "{c}"]}},
    ],
)
@pytest.mark.parametrize("present", [False, True])
async def test_every_styling_form_names_its_columns(
    test_db_session, clean_tables, fields, present
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    name = "PARK_TYPE" if present else "MISSING"
    fields = json.loads(json.dumps(fields).replace("{c}", name))

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), **fields)),
        )
    ).maps

    if present:
        assert (result.action, result.messages) == ("create", [])
    else:
        assert _codes(result) == [("A063", "warning", "parks")]
        assert result.messages[0].message.endswith("named MISSING.")


@pytest.mark.parametrize(
    "filter_",
    [
        ["==", ["get", "PARK_TYPE"], "b"],
        ["==", "$type", "Point"],
        ["==", "$id", 1],
        ["!has", "$id"],
        ["has", "$id"],
        ["has", "$type"],
        ["!has", "$type"],
    ],
)
async def test_expression_filters_and_pseudo_fields_name_no_missing_column(
    test_db_session, clean_tables, filter_
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), filter=filter_)),
        )
    ).maps

    assert result.messages == []


@pytest.mark.parametrize(
    ("column_info", "codes"),
    [([], [("A063", "warning", "parks")]), (None, [])],
)
async def test_a_dataset_with_no_columns_has_none_to_name(
    test_db_session, clean_tables, column_info, codes
):
    admin = await _admin(test_db_session)
    dataset = await create_dataset(
        test_db_session, created_by=admin.id, column_info=column_info
    )
    if column_info is None:
        # The factory leaves column_info unset; make it the unrecorded NULL.
        dataset.column_info = None
    await test_db_session.commit()

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(
                    dataset_id=str(dataset.id),
                    label_config={"column": "NAME"},
                ),
            ),
        )
    ).maps

    assert _codes(result) == codes


@pytest.mark.parametrize(
    ("text_field", "missing"),
    [
        ("{MISSING}", "MISSING"),
        ("{PARK_NAME}", None),
        ("Park", None),
        ("{MISSING} and {OTHER}", "MISSING, OTHER"),
    ],
)
async def test_text_field_tokens_name_columns(
    test_db_session, clean_tables, text_field, missing
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(dataset_id=str(dataset_id), layout={"text-field": text_field}),
            ),
        )
    ).maps

    if missing is None:
        assert result.messages == []
    else:
        assert _codes(result) == [("A063", "warning", "parks")]
        assert result.messages[0].message.endswith(f"named {missing}.")


async def test_icon_image_tokens_name_columns(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(
                    dataset_id=str(dataset_id),
                    layout={"icon-image": "marker-{MISSING}"},
                ),
            ),
        )
    ).maps

    assert _codes(result) == [("A063", "warning", "parks")]


@pytest.mark.parametrize(
    ("symbol", "codes"),
    [
        ({"iconImage": "marker-{MISSING}"}, [("A063", "warning", "parks")]),
        (
            {
                "iconImage": "marker-{MISSING}",
                "categoryColumn": "PARK_TYPE",
                "categories": [{"value": "a", "icon": "pin-{MISSING}"}],
            },
            [],
        ),
    ],
    ids=["plain-fallback", "inside-a-match"],
)
async def test_symbol_icon_tokens_name_columns_only_outside_a_match(
    test_db_session, clean_tables, symbol, codes
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(dataset_id=str(dataset_id), style_config={"symbol": symbol}),
            ),
        )
    ).maps

    assert _codes(result) == codes


async def test_maps_naming_no_basemap_never_read_the_basemaps(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    from app.modules.catalog.maps import manifest_apply

    with patch.object(
        manifest_apply, "_known_basemap_ids", AsyncMock(side_effect=RuntimeError)
    ):
        [result] = (
            await _dry_run(
                test_db_session,
                admin,
                _map("qgis-map-a", _layer(dataset_id=str(dataset_id))),
            )
        ).maps

    assert (result.action, result.messages) == ("create", [])


async def test_a_database_error_in_one_map_leaves_the_next_map_checked(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    own = await _keyed_map(test_db_session, admin.id, "qgis-map-b", dataset_id)
    from app.modules.catalog.maps import manifest_apply

    real = manifest_apply._writable_map_id

    async def failing_on_the_server(session, key, user):
        if key == "qgis-map-a":
            # Raised by PostgreSQL, which aborts the transaction it runs in.
            await session.execute(text("SELECT 1 / 0"))
        return await real(session, key, user)

    with patch.object(manifest_apply, "_writable_map_id", failing_on_the_server):
        response = await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id))),
            _map("qgis-map-b", _layer(dataset_id=str(dataset_id))),
        )

    failed, checked = response.maps
    assert (failed.action, _codes(failed)) == ("error", [("A099", "error", None)])
    assert (checked.action, checked.map_id, checked.messages) == ("update", own, [])
    assert await test_db_session.scalar(select(func.count()).select_from(Map)) == 1


# Each names the column written {c}; filled with a missing and a present name.
_READS = {
    "get_with_properties": {"paint": {"circle-radius": ["get", "{c}", ["properties"]]}},
    "has_with_properties": {
        "paint": {
            "circle-color": ["case", ["has", "{c}", ["properties"]], "#000", "#fff"]
        }
    },
    "format_option": {
        "layout": {
            "text-field": [
                "format",
                ["get", "PARK_NAME"],
                {"font-scale": ["get", "{c}"]},
            ]
        }
    },
    "collator_option": {
        "paint": {
            "circle-color": [
                "case",
                [
                    "==",
                    ["get", "PARK_NAME"],
                    "x",
                    ["collator", {"locale": ["get", "{c}"]}],
                ],
                "#000",
                "#fff",
            ]
        }
    },
    "number_format_option": {
        "layout": {
            "text-field": [
                "number-format",
                ["get", "PARK_TYPE"],
                {"locale": ["get", "{c}"]},
            ]
        }
    },
    "semiliteral_item": {
        "layout": {"text-offset": ["semiliteral", [["get", "{c}"], 1]]}
    },
    "symbol_icon_expression": {
        "style_config": {
            "symbol": {"iconImage": ["match", ["get", "{c}"], "city", "bus", "marker"]}
        }
    },
    "builder_symbol_icon_size": {
        "style_config": {"builder": {"symbol": {"iconSize": ["get", "{c}"]}}}
    },
    "symbol_icon_token": {"style_config": {"symbol": {"iconImage": "park-{{c}}"}}},
    "paint_outline_color": {"paint": {"outline-color": ["get", "{c}"]}},
    "builder_outline_width": {
        "style_config": {"builder": {"outline_width": ["get", "{c}"]}}
    },
    "symbol_icon_size_function": {
        "style_config": {
            "symbol": {"iconSize": {"property": "{c}", "stops": [[1, 1], [5, 2]]}}
        }
    },
    "builder_symbol_icon_size_function": {
        "style_config": {
            "builder": {
                "symbol": {"iconSize": {"property": "{c}", "stops": [[1, 1], [5, 2]]}}
            }
        }
    },
    "symbol_category_icon_expression": {
        "style_config": {
            "symbol": {
                "categoryColumn": "PARK_TYPE",
                "categories": [{"value": "a", "icon": ["get", "{c}"]}],
            }
        }
    },
    "builder_symbol_category_icon_expression": {
        "style_config": {
            "builder": {
                "symbol": {
                    "categoryColumn": "PARK_TYPE",
                    "categories": [{"value": "a", "icon": ["get", "{c}"]}],
                }
            }
        }
    },
    "builder_arrow_color": {
        "style_config": {
            "render_mode": "arrow",
            "builder": {"arrowColor": {"property": "{c}", "stops": [[1, "#000"]]}},
        }
    },
}


@pytest.mark.parametrize("form", sorted(_READS))
@pytest.mark.parametrize("present", [False, True])
async def test_every_operator_form_names_its_columns(
    test_db_session, clean_tables, form, present
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    name = "PARK_TYPE" if present else "MISSING"
    fields = json.loads(json.dumps(_READS[form]).replace("{c}", name))

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), **fields)),
        )
    ).maps

    if present:
        assert (result.action, result.messages) == ("create", [])
    else:
        assert _codes(result) == [("A063", "warning", "parks")]
        assert result.messages[0].message.endswith("named MISSING.")


@pytest.mark.parametrize(
    "fields",
    [
        {"paint": {"circle-radius": ["get", "MISSING", ["literal", {"MISSING": 1}]]}},
        {"paint": {"circle-radius": ["get", "MISSING", ["global-state", "row"]]}},
        {"layout": {"text-field": ["to-string", {"x": ["get", "MISSING"]}]}},
        {"style_config": {"symbol": {"iconImage": "marker"}}},
        {
            "paint": {
                "circle-opacity": [
                    "case",
                    [
                        "within",
                        {"type": "Polygon", "coordinates": [[["get", "MISSING"]]]},
                    ],
                    1,
                    0,
                ]
            }
        },
    ],
)
async def test_data_beside_an_expression_names_no_column(
    test_db_session, clean_tables, fields
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map("qgis-map-a", _layer(dataset_id=str(dataset_id), **fields)),
        )
    ).maps

    assert (result.action, result.messages) == ("create", [])


@pytest.mark.parametrize("layers", [None, []])
def test_a_map_needs_a_layer(layers):
    entry = {"key": "qgis-map-a", "name": "Parks"}
    if layers is not None:
        entry["layers"] = layers
    with pytest.raises(ValidationError):
        ManifestApplyRequest.model_validate(_body(entry))


# Invalid in the contract, but not for the request schema: the styling ones
# are refused by the dry run with the code given, and a v1 source scheme stays
# open to every client by design.
_REFUSED_BY_THE_DRY_RUN = {
    "popup_config_without_enabled": "A099",
    "popup_config_unknown_field": "A099",
    "popup_visible_fields_duplicate": "A099",
}
_ACCEPTED_BY_DESIGN = {"uri_without_upload_scheme"}


def _as_dry_run(manifest: dict) -> dict:
    return {**manifest, "dry_run": True} if manifest.get("maps") else manifest


@pytest.mark.parametrize(
    "example",
    [
        e
        for e in _CONTRACT["invalid"]
        if e["name"] not in set(_REFUSED_BY_THE_DRY_RUN) | _ACCEPTED_BY_DESIGN
    ],
    ids=lambda e: e["name"],
)
def test_every_invalid_contract_example_is_refused(example):
    # As a dry run, so no example is refused only for carrying maps.
    with pytest.raises(ValidationError):
        ManifestApplyRequest.model_validate(_as_dry_run(example["manifest"]))


@pytest.mark.parametrize("name", sorted(_REFUSED_BY_THE_DRY_RUN))
async def test_invalid_contract_styling_is_refused_by_the_dry_run(
    test_db_session, clean_tables, name
):
    admin = await _admin(test_db_session)
    [example] = [e for e in _CONTRACT["invalid"] if e["name"] == name]
    request = ManifestApplyRequest.model_validate(_as_dry_run(example["manifest"]))

    with patch(
        "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
    ):
        response = await apply_manifest(
            test_db_session, request, admin, _http_request()
        )

    [result] = response.maps
    assert result.action == "error"
    assert [
        m.layer
        for m in result.messages
        if m.code == _REFUSED_BY_THE_DRY_RUN[name] and "popup_config" in m.message
    ] == ["parks"]


def test_the_listed_exceptions_are_contract_invalid_examples():
    names = {e["name"] for e in _CONTRACT["invalid"]}
    assert set(_REFUSED_BY_THE_DRY_RUN) | _ACCEPTED_BY_DESIGN <= names


async def test_get_with_a_dollar_name_reads_that_property_outside_a_filter(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [result] = (
        await _dry_run(
            test_db_session,
            admin,
            _map(
                "qgis-map-a",
                _layer(
                    dataset_id=str(dataset_id),
                    paint={"circle-radius": ["get", "$id"]},
                ),
            ),
        )
    ).maps

    assert _codes(result) == [("A063", "warning", "parks")]
    assert result.messages[0].message.endswith("named $id.")


@pytest.mark.parametrize(
    ("action", "codes"),
    [("error", [("A052", "error", "parks")]), ("update", []), ("skip", [])],
)
async def test_a_failed_replacement_entry_supplies_no_dataset(
    test_db_session, clean_tables, action, codes
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    await _published_under(test_db_session, admin.id, "qgis-parks", dataset_id)
    request = _publish_request(
        ["qgis-parks"], _map("qgis-map-a", _layer(dataset_key="qgis-parks"))
    )
    results = [
        ManifestApplyEntryResult(dataset_key="qgis-parks", action=action, message="m")
    ]

    [result] = await check_manifest_maps(test_db_session, request, admin, results)

    assert _codes(result) == codes


def test_every_builder_key_the_export_reads_is_scanned_or_never_a_column():
    """A builder key the style export reads must be decided on: scanned, or listed as unable to name a column."""
    import re

    from app.modules.catalog.maps import manifest_apply, style_json
    from app.modules.catalog.maps.schemas import BUILDER_SNAKE_TO_CAMEL_KEYS

    source = Path(style_json.__file__).read_text()
    read = set(re.findall(r'builder\.get\("([A-Za-z_]+)"\)', source))
    for keys in re.findall(r"for builder_key in \(([^)]*)\)", source):
        read |= set(re.findall(r'"([A-Za-z_]+)"', keys))
    assert {"outlineColor", "arrowColor", "heatmapWeightColumn"} <= read

    camel_to_snake = {
        camel: snake for snake, camel in BUILDER_SNAKE_TO_CAMEL_KEYS.items()
    }
    decided = (
        set(manifest_apply._BUILDER_STYLE_VALUE_KEYS)
        | set(manifest_apply._BUILDER_COLUMN_KEYS)
        | manifest_apply._BUILDER_NON_COLUMN_KEYS
    )
    undecided = sorted(k for k in read if camel_to_snake.get(k, k) not in decided)
    assert undecided == []


def test_the_style_export_writes_a_category_icon_expression_unchanged():
    """Why category icons are scanned: the export emits them as they are."""
    from app.modules.catalog.maps.style_json import _symbol_layout_from_style

    symbol = {
        "categoryColumn": "PARK_TYPE",
        "categories": [{"value": "a", "icon": ["get", "missing_icon"]}],
    }
    for style_config in ({"symbol": symbol}, {"builder": {"symbol": symbol}}):
        icon_image = _symbol_layout_from_style({}, style_config, None)["icon-image"]
        assert ["get", "missing_icon"] in icon_image
