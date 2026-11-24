"""Version 2 apply results carry links, visibility and group names.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text, update
from starlette.routing import Match

from app.api.main import app
from app.core.config import settings
from app.modules.auth.models import Group
from app.modules.catalog.maps.models import Map, MapGroupGrant
from app.platform.extensions import get_processing_port
from app.platform.jobs.models import IngestJob
from app.processing.ingest import manifest_links
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestMessage,
)
from tests.test_manifest_maps_apply import _apply, _dataset, _layer, _map
from tests.test_manifest_maps_dry_run import (
    _admin,
    _body,
    _http_request,
    _person,
)

pytestmark = pytest.mark.anyio

APP_ROOT = "https://geolens.test"
API_ROOT = "https://api.geolens.test"


def _frontend_routes() -> str:
    """The web app's route table, in the checkout and in the API container."""
    here = Path(__file__).resolve()
    candidates = [root / "frontend/src/App.tsx" for root in here.parents[:3]]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text()
    pytest.fail(f"frontend/src/App.tsx not found; looked in {candidates}")


@pytest.fixture(autouse=True)
def _public_urls(monkeypatch):
    monkeypatch.setattr(settings, "public_app_url", APP_ROOT)
    monkeypatch.setattr(settings, "public_api_url", API_ROOT)


def _served_by_the_api(url: str) -> bool:
    path = urlsplit(url).path
    scope = {"type": "http", "method": "GET", "path": path, "root_path": ""}
    return any(route.matches(scope)[0] == Match.FULL for route in app.router.routes)


def _request(visibility: str | None = None) -> ManifestApplyRequest:
    """A version 2 request with one dataset entry, as the results name it."""
    entry = {
        "key": "qgis-parks",
        "title": "Parks",
        "sources": [{"type": "vector", "uri": "https://example.com/parks.fgb"}],
        "publication": {"intent": "published"},
        **({} if visibility is None else {"visibility": visibility}),
    }
    return ManifestApplyRequest.model_validate(_body(datasets=[entry], dry_run=True))


def _entry(dataset_id, action="update") -> ManifestApplyEntryResult:
    return ManifestApplyEntryResult(
        dataset_key="qgis-parks", action=action, dataset_id=dataset_id, message="x"
    )


async def test_a_map_result_links_to_the_viewer_the_app_serves(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-links", _layer(dataset_id=str(dataset_id))),
        )
    ).maps

    assert created.links is not None
    assert created.links.viewer == f"{APP_ROOT}/maps/{created.map_id}"
    assert 'path="maps/:id"' in _frontend_routes()


async def test_a_map_in_error_has_no_links(test_db_session, clean_tables):
    admin = await _admin(test_db_session)

    [failed] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-links", _layer(dataset_id=str(uuid.uuid4()))),
        )
    ).maps

    assert (failed.action, failed.links) == ("error", None)


async def test_a_map_result_names_the_groups_it_is_shared_with(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _map("qgis-map-links", _layer(dataset_id=str(dataset_id)))
    [created] = (await _apply(test_db_session, admin, entry)).maps
    group = Group(name=f"links-{uuid.uuid4().hex[:8]}")
    test_db_session.add(group)
    await test_db_session.flush()
    test_db_session.add(MapGroupGrant(map_id=created.map_id, group_id=group.id))
    await test_db_session.execute(
        update(Map).where(Map.id == created.map_id).values(visibility="restricted")
    )
    await test_db_session.commit()

    [applied] = (await _apply(test_db_session, admin, entry)).maps

    assert (created.groups, applied.groups) == ([], [group.name])


async def test_a_removed_layer_carries_its_id_and_the_dataset_link(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    kept = await _dataset(test_db_session, admin.id)
    dropped = await _dataset(test_db_session, admin.id)
    [created] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-links",
                _layer("kept", dataset_id=str(kept)),
                _layer("dropped", dataset_id=str(dropped)),
            ),
        )
    ).maps
    from tests.test_manifest_maps_apply import _layers

    dropped_layer_id = {
        layer.manifest_key: layer.id
        for layer in await _layers(test_db_session, created.map_id)
    }["dropped"]

    [updated] = (
        await _apply(
            test_db_session,
            admin,
            _map("qgis-map-links", _layer("kept", dataset_id=str(kept))),
        )
    ).maps

    [removed] = updated.removed_layers
    assert removed.layer_id == dropped_layer_id
    assert removed.link == f"{APP_ROOT}/datasets/{dropped}"
    assert 'path="datasets/:id"' in _frontend_routes()


async def test_a_dataset_result_links_resolve_to_served_routes(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _entry(dataset_id, action="skip")

    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [entry], None
    )

    assert entry.links is not None
    assert entry.links.page == f"{APP_ROOT}/datasets/{dataset_id}"
    assert entry.links.items == f"{API_ROOT}/collections/{dataset_id}/items"
    assert entry.links.tiles is not None
    assert entry.links.tiles.startswith(f"{API_ROOT}/tiles/data.")
    assert _served_by_the_api(entry.links.items)
    filled = re.sub(r"\{([zxy])\}", "1", entry.links.tiles)
    assert _served_by_the_api(filled)
    assert entry.visibility == "public"


async def test_a_dataset_the_caller_cannot_read_gets_no_links(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    other, _ = await _person(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, admin.id, visibility="private")
    entry = _entry(dataset_id)

    await manifest_links.describe_results(
        test_db_session, _request(), other, _http_request(), [entry], None
    )

    assert (entry.visibility, entry.links) == (None, None)


async def test_an_entry_without_a_dataset_yet_sends_nulls_not_nothing(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    entry = _entry(None, action="create")

    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [entry], None
    )

    dumped = entry.model_dump()
    assert (dumped["visibility"], dumped["links"]) == ("private", None)
    assert {"visibility", "links"} <= set(dumped)


def test_a_version_1_entry_leaves_the_new_fields_out():
    dumped = _entry(uuid.uuid4()).model_dump()

    assert not {"visibility", "links"} & set(dumped)


async def test_an_updating_entry_reports_the_visibility_it_publishes(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id, visibility="private")
    changing, keeping = _entry(dataset_id), _entry(dataset_id)

    await manifest_links.describe_results(
        test_db_session, _request("internal"), admin, _http_request(), [changing], None
    )
    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [keeping], None
    )

    assert (changing.visibility, keeping.visibility) == ("internal", "private")


async def test_a_public_that_fell_back_reports_internal(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id, visibility="private")
    entry = _entry(dataset_id)
    entry.messages = [
        ManifestMessage(code="A020", severity="warning", message="fell back")
    ]

    await manifest_links.describe_results(
        test_db_session, _request("public"), admin, _http_request(), [entry], None
    )

    assert entry.visibility == "internal"


async def test_a_failed_lookup_leaves_the_session_usable(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _entry(dataset_id)

    async def broken(_self, db, _dataset_id):
        await db.execute(text("SELECT * FROM catalog.no_such_table"))

    monkeypatch.setattr(type(get_processing_port()), "get_dataset", broken)

    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [entry], None
    )

    assert entry.links is None
    assert await test_db_session.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("dry_run", [True, False])
async def test_a_failure_building_links_still_returns_the_apply_response(
    test_db_session, clean_tables, monkeypatch, dry_run
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)

    def broken(*_args, **_kwargs):
        raise RuntimeError("no url")

    monkeypatch.setattr(manifest_links, "join_public_url", broken)

    response = await _apply(
        test_db_session,
        admin,
        _map("qgis-map-links", _layer(dataset_id=str(dataset_id))),
        dry_run=dry_run,
    )

    [result] = response.maps
    assert (result.action, result.links) == ("create", None)
    assert await test_db_session.scalar(text("SELECT 1")) == 1


async def test_a_url_failure_leaves_every_result_its_visibility(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    stored = await _dataset(test_db_session, admin.id, visibility="private")
    updating, keeping = _entry(stored), _entry(stored)
    creating = _entry(None, action="create")

    async def broken(*_args, **_kwargs):
        raise RuntimeError("no fleet url")

    monkeypatch.setattr(manifest_links, "get_browser_reachable_app_url", broken)

    await manifest_links.describe_results(
        test_db_session,
        _request("internal"),
        admin,
        _http_request(),
        [creating, updating],
        None,
    )
    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [keeping], None
    )

    dumped = [r.model_dump() for r in (creating, updating, keeping)]
    assert [(d["visibility"], d["links"]) for d in dumped] == [
        ("internal", None),
        ("internal", None),
        ("private", None),
    ]


async def test_a_failed_lookup_keeps_the_levels_of_the_other_results(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id, visibility="internal")
    unreadable, readable = _entry(uuid.uuid4()), _entry(dataset_id)
    real = type(get_processing_port()).get_dataset

    async def broken_for_one(self, db, requested):
        if requested == unreadable.dataset_id:
            await db.execute(text("SELECT * FROM catalog.no_such_table"))
        return await real(self, db, requested)

    monkeypatch.setattr(type(get_processing_port()), "get_dataset", broken_for_one)

    await manifest_links.describe_results(
        test_db_session,
        _request(),
        admin,
        _http_request(),
        [unreadable, readable],
        None,
    )

    assert (unreadable.visibility, readable.visibility) == (None, "internal")
    assert readable.links is not None


@pytest.mark.parametrize(
    "action,pending,has_tiles",
    [
        ("skip", False, True),
        ("update", False, False),
        ("blocked", False, False),
        ("skip", True, False),
    ],
    ids=["completed-skip", "queued-update", "held", "in-flight-skip"],
)
async def test_tiles_are_left_out_while_a_job_is_still_writing_the_dataset(
    test_db_session, clean_tables, action, pending, has_tiles
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    entry = _entry(dataset_id, action=action)
    if pending:
        entry.mark_pending(None)

    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [entry], None
    )

    assert entry.links is not None
    assert (entry.links.tiles is not None) == has_tiles
    assert entry.links.items is not None


async def test_a_completed_skip_with_a_replacement_queued_since_has_no_tiles(
    test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    test_db_session.add(
        IngestJob(
            source_filename="parks.geojson",
            created_by=admin.id,
            dataset_id=dataset_id,
            status="pending",
            user_metadata={},
        )
    )
    await test_db_session.commit()
    entry = _entry(dataset_id, action="skip")

    await manifest_links.describe_results(
        test_db_session, _request(), admin, _http_request(), [entry], None
    )

    assert entry.links is not None
    assert (entry.links.items is not None, entry.links.tiles) == (True, None)
