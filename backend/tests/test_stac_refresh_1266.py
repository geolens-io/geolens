"""STAC re-resolution strategy (#1266, ADR-002 Amendment A10).

A STAC dataset is a pointer and nothing else: the COG stays in the
publisher's bucket and Titiler reads it at tile time. #1222 taught GeoLens to
NOTICE when that pointer stops resolving; this is the half that acts on it.

Three things are being tested, and they fail in different ways.

**The resolution** is where the judgement lives — which asset in a re-fetched
item is "the same" one, when a 404 means the item moved versus was withdrawn,
and what an inconclusive answer is allowed to write. Those are unit tests
against a mock transport, because each one is a rule and not a round trip.

**The door** must admit a STAC origin through the SAME machinery the other
two strategies use — one Rule 1 gate, one ``create_pending_run``, one partial
unique index refereeing concurrent clicks. A strategy that grew its own
admission path would pass all of its own tests and still be the bug (handoff
invariant 11), so the assertions are about which shared function ran.

**The worker** must leave the dataset pointing somewhere better or exactly
where it was, never in between. The failure tests are the load-bearing ones:
invariant 10 says a failed refresh changes no data and no freshness, and for
this origin kind the pointer IS the data.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.sources import stac_resolve
from app.modules.catalog.sources.adapters.stac import pick_data_asset
from app.modules.catalog.sources.origin_probe import DETAIL_CODES
from app.platform.security import SSRFError, SSRFResolutionError
from app.modules.catalog.sources.stac_resolve import resolve_stac_binding
from app.platform.dataset_origin import SOURCE_HEALTH_VALUES, build_origin_ref
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest import tasks_stac_refresh
from app.processing.ingest.tasks_stac_refresh import refresh_stac
from app.processing.raster.models import DatasetAsset, RasterAsset
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_ROOT = "https://origin.test/stac"
_ITEM = f"{_ROOT}/collections/scenes/items/scene-1"
# A genuinely MOVED item: same id (the path segment is the item id, so a
# moved item that kept its identity keeps it here too), new address.
_MOVED_ITEM = f"{_ROOT}/v2/collections/scenes/items/scene-1"
_SEARCH = f"{_ROOT}/search"
_ASSET = "https://origin.test/tiles/scene.tif"
_MOVED_ASSET = "https://origin.test/v2/tiles/scene.tif"


# ---------------------------------------------------------------------------
# Transport doubles
# ---------------------------------------------------------------------------


def _item_doc(
    *,
    asset_href: str = _ASSET,
    asset_key: str = "data",
    self_href: str | None = _ITEM,
    item_id: str = "scene-1",
    assets: dict | None = None,
) -> dict:
    """A STAC item document, in the shape a catalog actually publishes one."""
    return {
        "type": "Feature",
        "id": item_id,
        "collection": "scenes",
        "properties": {"proj:code": "EPSG:32633"},
        "bbox": [10.0, 45.0, 11.0, 46.0],
        "links": (
            [{"rel": "self", "href": self_href}] if self_href is not None else []
        ),
        "assets": (
            assets
            if assets is not None
            else {
                asset_key: {"href": asset_href, "roles": ["data"], "type": "image/tiff"}
            }
        ),
    }


def _raising(exc_factory):
    """A handler that fails the request instead of answering it."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise exc_factory(request)

    return _handler


def _routes(mapping: dict[str, tuple[int, object | None]]):
    """Answer each URL from a table; anything unlisted is a 404.

    Unlisted means 404 on purpose: a test that forgets to publish a URL should
    look like the origin does not have it, which is a state this code has an
    opinion about, rather than like a hung request.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        entry = mapping.get(str(request.url))
        if entry is None:
            return httpx.Response(404)
        status_code, payload = entry
        if 300 <= status_code < 400:
            # A redirect points at the one other URL in the table that shares
            # this one's final path segment — enough for the one case that
            # needs to express "the document came from somewhere else".
            target = next(
                (
                    url
                    for url in mapping
                    if url != str(request.url)
                    and url.rsplit("/", 1)[-1] == str(request.url).rsplit("/", 1)[-1]
                ),
                None,
            )
            if target is not None:
                return httpx.Response(status_code, headers={"Location": target})
        if payload is None:
            return httpx.Response(status_code)
        return httpx.Response(status_code, json=payload)

    return _handler


async def _resolve(**kwargs):
    """Resolve a binding shaped the way an import writes one today.

    Every field an import records is defaulted here, so a test that leaves one
    out is saying "this is the ordinary case" rather than silently exercising
    a legacy binding. Tests about legacy shapes pass the field explicitly.
    """
    kwargs.setdefault("item_id", "scene-1")
    kwargs.setdefault("collection_id", "scenes")
    kwargs.setdefault("asset_href", _ASSET)
    kwargs.setdefault("asset_key", "data")
    return await resolve_stac_binding(**kwargs)


@pytest.fixture(autouse=True)
def cog_info(monkeypatch):
    """Titiler's reading of a moved COG, which the resolver requires.

    Nothing is adopted without it — a pointer to an object GeoLens could not
    read is exactly what the strategy refuses — so it is stubbed by default
    and overridden where the failure itself is the subject.
    """
    described = {
        "band_count": 1,
        "dtype": "uint16",
        "width": 512,
        "height": 512,
        "nodata": 0,
        "band_info": [{"min": 0, "max": 4095, "mean": 1200}],
        # fix(#1334): the shape fetch_cog_info actually returns, so tests
        # against this fixture exercise the same fields the refresh path
        # now writes to the asset row. crs_wkt and epsg are a
        # matched pair, same as a real _georeferencing result: leaving epsg
        # out here would make reconcile_epsg read as "a CRS with no mappable
        # EPSG" rather than "the fixture just didn't set it".
        "crs_wkt": 'PROJCS["WGS 84 / UTM zone 33N",AUTHORITY["EPSG","32633"]]',
        "epsg": 32633,
        # fix(#1375): res_x/res_y/is_rotated join them for the same reason —
        # _geotransform reads all three off /cog/stac's proj:transform, so a
        # fixture without them would exercise only the degraded path.
        "res_x": 30.0,
        "res_y": 30.0,
        "is_rotated": False,
    }
    calls: list[str] = []

    async def _fake(url: str):
        calls.append(url)
        return described

    monkeypatch.setattr(
        "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info", _fake
    )
    return described, calls


@pytest.fixture
def stac_transport(monkeypatch):
    """Install a mock transport for every outbound byte this feature sends.

    One patch point covers the item fetch, the fallback search and the asset
    probe, because all three go through ``origin_probe``'s safe client — which
    is the structural claim the feature makes about Rule 2, checked here by
    the fact that no second patch is needed to silence the network.
    """
    recorded: list[httpx.Request] = []

    # The resolver validates a replacement item pointer and the adopted asset
    # href with the door's own SSRF function, which resolves DNS for real
    # against names nothing answers for. Policy refusal has its own test,
    # driven by raising from this stub.
    monkeypatch.setattr(
        "app.modules.catalog.sources.stac_resolve_asset_gate.validate_url_for_ssrf",
        AsyncMock(),
    )

    def install(routes) -> None:
        """Install a URL table, or a handler for the failure shapes."""
        handler = routes if callable(routes) else _routes(routes)

        def factory(timeout=10.0, **_kwargs) -> httpx.AsyncClient:
            async def _handle(request: httpx.Request) -> httpx.Response:
                recorded.append(request)
                return handler(request)

            # follow_redirects mirrors `make_safe_client`, so a route table
            # can express a redirect and `response.url` reports where the
            # document actually came from — which is what relative hrefs
            # resolve against.
            return httpx.AsyncClient(
                transport=httpx.MockTransport(_handle),
                timeout=timeout,
                follow_redirects=True,
            )

        monkeypatch.setattr(
            "app.modules.catalog.sources.origin_probe.make_safe_client", factory
        )

    return install, recorded


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _stac_dataset(
    session,
    *,
    created_by: uuid.UUID,
    item_href: str | None = _ITEM,
    item_id: str | None = "scene-1",
    asset_href: str | None = _ASSET,
    asset_key: str | None = "data",
    collection_id: str | None = "scenes",
    source_health: str | None = None,
) -> Dataset:
    """A STAC dataset with a remote raster asset, as the import path makes one."""
    dataset = await _create_dataset(
        session,
        created_by=created_by,
        name=f"STAC Scene {uuid.uuid4().hex[:6]}",
        source_format="stac",
        source_filename="scene-1",
        srid=4326,
    )
    dataset.record.record_type = "raster_dataset"
    dataset.origin_uri = asset_href
    dataset.origin_ref = build_origin_ref(
        "stac",
        asset_href=asset_href,
        item_href=item_href,
        item_id=item_id,
        collection_id=collection_id,
        asset_key=asset_key,
    )
    dataset.source_health = source_health
    dataset.last_refreshed_at = datetime.now(timezone.utc) - timedelta(days=30)
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=asset_href or "",
            storage_backend="remote",
            cog_status="verified",
            epsg=4326,
            ingested_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


@asynccontextmanager
async def _dispatch_harness():
    """Patch the deferred task and yield the mock the door should reach for.

    ``validate_url_for_ssrf`` is stubbed for the same reason the service
    door's harness stubs it: it resolves DNS for real, and ``origin.test`` is
    a name nothing answers for. The check itself has its own test below,
    driven from the other side.
    """
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.refresh_stac_task.return_value = task
    with (
        patch.object(router_refresh, "validate_url_for_ssrf", AsyncMock()),
        patch.object(router_refresh, "get_catalog_port", return_value=port),
    ):
        yield task


async def _dispatch(client: AsyncClient, headers: dict, dataset_id: uuid.UUID) -> dict:
    async with _dispatch_harness():
        resp = await client.post(f"/datasets/{dataset_id}/refresh", headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _execute(session, payload: dict) -> None:
    """Run the worker for a dispatched refresh, as the queue would.

    ``.func`` is the Procrastinate-registered callable — the same one a worker
    invokes — so the run ledger, the heartbeat and the failure handler all
    execute for real.
    """
    job = (
        await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(payload["job_id"]))
        )
    ).scalar_one()
    await refresh_stac.func(
        job_id=payload["job_id"],
        dataset_id=payload["dataset_id"],
        attempt_id=str(job.attempt_id),
    )


def _fresh_session():
    """A session of its own, independent of the test's.

    Every read-back here opens one rather than expiring the test's session.
    The worker commits from sessions the test does not own, so a fresh
    connection is what actually proves the write landed — and expiring the
    test's session instead would detach the dataset the assertions still
    need to name.
    """
    from app.core.db import async_session

    return async_session()


async def _reload(dataset_id: uuid.UUID) -> Dataset:
    async with _fresh_session() as session:
        return (
            await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_id)
            )
        ).scalar_one()


async def _asset_uri(dataset_id: uuid.UUID) -> str:
    async with _fresh_session() as session:
        return (
            await session.execute(
                select(RasterAsset.asset_uri).where(
                    RasterAsset.dataset_id == dataset_id
                )
            )
        ).scalar_one()


async def _raster_asset(dataset_id: uuid.UUID) -> RasterAsset:
    async with _fresh_session() as session:
        return (
            await session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
            )
        ).scalar_one()


async def _run_for(dataset_id: uuid.UUID) -> DatasetRefreshRun | None:
    async with _fresh_session() as session:
        return (
            await session.execute(
                select(DatasetRefreshRun).where(
                    DatasetRefreshRun.dataset_id == dataset_id
                )
            )
        ).scalar_one_or_none()


async def _origin_asset_rows(dataset_id: uuid.UUID) -> list[DatasetAsset]:
    """Every served ``dataset_assets`` row for the dataset (feat #1692)."""
    async with _fresh_session() as session:
        return list(
            (
                await session.execute(
                    select(DatasetAsset).where(DatasetAsset.dataset_id == dataset_id)
                )
            )
            .scalars()
            .all()
        )


# ---------------------------------------------------------------------------
# The vocabulary is the probe's, not a second one
# ---------------------------------------------------------------------------


def test_the_health_words_are_the_ones_the_api_already_describes() -> None:
    """Structural: processing/ retypes these, so a test has to pin them.

    ``origin_probe`` owns the closed vocabulary and the API description is
    generated from it, but processing/ may not import catalog. A value that
    drifted out of the probe's set would be persisted, served, and absent
    from the schema that claims to enumerate it.
    """
    assert tasks_stac_refresh._MISSING in SOURCE_HEALTH_VALUES
    assert tasks_stac_refresh._ITEM_WITHDRAWN in DETAIL_CODES
    assert tasks_stac_refresh._NOT_FOUND in DETAIL_CODES
    assert stac_resolve._WITHDRAWN.health in SOURCE_HEALTH_VALUES
    assert stac_resolve._WITHDRAWN.detail in DETAIL_CODES
    assert stac_resolve._ASSET_GONE.health in SOURCE_HEALTH_VALUES
    assert stac_resolve._ASSET_GONE.detail in DETAIL_CODES


def test_stored_failure_text_is_composed_here_and_carries_no_origin_words() -> None:
    """ADR-002 Decision 3: no provider text, body, or URL in a stored reason.

    These are constants rather than interpolations, which is what makes the
    property checkable by reading them — an embedded response or href would
    be visible as a placeholder.
    """
    for message in (
        tasks_stac_refresh._WITHDRAWN_MESSAGE,
        tasks_stac_refresh._ASSET_REMOVED_MESSAGE,
        tasks_stac_refresh._UNREACHABLE_MESSAGE,
    ):
        assert "{" not in message
        assert "http" not in message


# ---------------------------------------------------------------------------
# Which asset, and where the search goes
# ---------------------------------------------------------------------------


class TestAssetSelection:
    def test_import_and_refresh_pick_the_same_asset(self) -> None:
        """The two callers of one rule. If they disagreed, a refresh would
        quietly re-point a dataset at a different band than it was imported
        from."""
        assets = {
            "thumbnail": {"href": "https://origin.test/thumb.png"},
            "visual": {"href": _ASSET},
        }
        assert pick_data_asset(assets) == ("visual", assets["visual"])

    def test_role_tagged_asset_is_the_last_resort(self) -> None:
        assets = {"cog": {"href": _ASSET, "roles": ["data", "reflectance"]}}
        assert pick_data_asset(assets) == ("cog", assets["cog"])

    def test_an_item_with_no_data_asset_picks_nothing(self) -> None:
        assert pick_data_asset({"thumbnail": {"href": "https://x.test/t.png"}}) is None
        assert pick_data_asset({"data": "not-a-dict"}) is None
        assert pick_data_asset(None) is None

    def test_the_recorded_key_wins_over_the_import_default(self) -> None:
        """A dataset imported from ``B04`` must stay on ``B04`` even once the
        item gains a ``data`` asset — the key is the identity, and the
        import-order default is only a fallback for datasets that have none."""
        assets = {
            "data": {"href": "https://origin.test/other.tif", "roles": ["data"]},
            "B04": {"href": _MOVED_ASSET},
        }
        assert (
            stac_resolve._bound_asset_key(assets, asset_href=_ASSET, asset_key="B04")
            == "B04"
        )

    def test_an_unchanged_href_identifies_the_key_for_a_binding_that_lacks_one(
        self,
    ) -> None:
        """Datasets imported before ``asset_key`` was written have only the
        href to recognise their asset by — and recovering the key from it is
        what lets the NEXT refresh survive a move."""
        assets = {
            "data": {"href": "https://origin.test/other.tif", "roles": ["data"]},
            "B04": {"href": _ASSET},
        }
        assert (
            stac_resolve._bound_asset_key(assets, asset_href=_ASSET, asset_key=None)
            == "B04"
        )

    def test_an_empty_string_key_is_recognised_by_identity(self) -> None:
        """fix(#1331): ``""`` is a legal JSON property name, so an item may
        key its data asset under the empty string — and a binding that
        recorded it names a real asset. Testing the stored key with
        truthiness treats ``""`` exactly like no key was ever recorded,
        which is the bug: identity must be read with ``is not None``."""
        assets = {
            "data": {"href": "https://origin.test/other.tif", "roles": ["data"]},
            "": {"href": _MOVED_ASSET},
        }
        assert (
            stac_resolve._bound_asset_key(assets, asset_href=_ASSET, asset_key="") == ""
        )

    async def test_a_relative_asset_href_resolves_against_the_document_url(
        self, stac_transport
    ) -> None:
        install, _ = stac_transport
        resolved = "https://origin.test/stac/collections/scenes/tiles/scene.tif"
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(assets={"data": {"href": "../tiles/scene.tif"}}),
                ),
                resolved: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        assert (result.asset_key, result.asset_href) == ("data", resolved)

    @pytest.mark.parametrize(
        "href",
        [
            "https://user:pw@origin.test/tiles/scene.tif",
            "https://origin.test/tiles/scene.tif?token=abc",
            "s3://bucket/tiles/scene.tif",
            "http://[bad",
        ],
    )
    async def test_an_unstorable_asset_href_is_never_adopted(
        self, stac_transport, href: str
    ) -> None:
        """ADR-002 invariant 4: a publisher that starts signing hrefs must not
        be able to write a credential into ``origin_ref``. And the refusal
        must not demote the dataset onto a DIFFERENT asset either — which is
        why identity is settled before the href is looked at, and why the
        verdict is `unauthorized` rather than `missing`: nothing was deleted.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        assets={
                            "B04": {"href": href},
                            "data": {"href": _MOVED_ASSET, "roles": ["data"]},
                        }
                    ),
                )
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET, asset_key="B04"
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unauthorized")


class TestSearchDerivation:
    def test_the_root_and_id_come_out_of_the_item_url(self) -> None:
        assert stac_resolve._search_root_and_item_id(_ITEM, "scenes") == (
            _ROOT,
            "scene-1",
        )

    def test_a_percent_encoded_id_is_searched_for_decoded(self) -> None:
        href = f"{_ROOT}/collections/scenes/items/scene%20one"
        assert stac_resolve._search_root_and_item_id(href, "scenes") == (
            _ROOT,
            "scene one",
        )

    def test_a_query_string_is_not_part_of_the_identity(self) -> None:
        assert stac_resolve._search_root_and_item_id(f"{_ITEM}?f=json", "scenes") == (
            _ROOT,
            "scene-1",
        )

    @pytest.mark.parametrize(
        ("href", "collection"),
        [
            # The stored collection has to be the one in the path, or the
            # derivation is a guess rather than a reading.
            (_ITEM, "other-collection"),
            (_ITEM, None),
            # Layouts that are not the standard one get no second path at all.
            ("https://origin.test/items/scene-1", "scenes"),
            ("https://origin.test/stac/scenes/scene-1.json", "scenes"),
            # Not a single item segment: `/items/a/b` addresses something
            # inside the item, and searching for `a` would bind elsewhere.
            (f"{_ROOT}/collections/scenes/items/scene-1/assets/data", "scenes"),
            (f"{_ROOT}/collections/scenes/items/", "scenes"),
        ],
    )
    def test_layouts_that_do_not_state_the_identity_are_refused(
        self, href: str, collection: str | None
    ) -> None:
        assert stac_resolve._search_root_and_item_id(href, collection) is None


# ---------------------------------------------------------------------------
# The resolution
# ---------------------------------------------------------------------------


class TestResolution:
    async def test_a_moved_asset_is_reported_from_the_live_item(
        self, stac_transport
    ) -> None:
        install, recorded = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        assert result.asset_key == "data"
        assert result.item_href == _ITEM
        assert result.health == "healthy"
        # No search: the item's own URL answered, so there was nothing to
        # look up. The asset probe is the second request.
        assert [str(r.url) for r in recorded] == [_ITEM, _MOVED_ASSET]

    async def test_a_withdrawn_item_is_found_again_by_collection_and_id(
        self, stac_transport
    ) -> None:
        """The whole point of the second path: a 404 on the self link is not
        proof the item is gone, only that it is not THERE."""
        install, recorded = stac_transport
        install(
            {
                _ITEM: (404, None),
                _SEARCH: (
                    200,
                    {
                        "features": [
                            _item_doc(asset_href=_MOVED_ASSET, self_href=_MOVED_ITEM)
                        ]
                    },
                ),
                # The item's new address serves the item — a replacement
                # pointer is adopted only if it would work next time.
                _MOVED_ITEM: (
                    200,
                    _item_doc(asset_href=_MOVED_ASSET, self_href=_MOVED_ITEM),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        # The item pointer moves too, or the next refresh repeats the search.
        assert result.item_href == _MOVED_ITEM
        search = [r for r in recorded if str(r.url) == _SEARCH]
        assert len(search) == 1
        assert search[0].method == "POST"

    async def test_a_search_that_ignores_the_id_filter_binds_nothing(
        self, stac_transport
    ) -> None:
        """A 200 from /search is not by itself an answer about this item. An
        endpoint that ignores ``ids`` hands back the collection's first page,
        and taking features[0] would re-point the dataset at another scene."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (404, None),
                _SEARCH: (200, {"features": [_item_doc(item_id="some-other-scene")]}),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET, asset_key=None
        )
        assert not result.resolved
        # Non-empty and non-matching: the endpoint answered a different
        # question, so it establishes nothing — including absence.
        assert result.health == "inaccessible"

    async def test_a_search_that_ignores_the_collection_filter_binds_nothing(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 13): item ids are only collection-scoped.

        An endpoint that honours `ids` while ignoring `collections` can
        legitimately return a same-id item from somewhere else — and one that
        omits its `collection` field would sail through the contradiction
        test every other path here relies on. The request named a collection,
        so an answer that does not affirm it has not answered the question.
        """
        install, _ = stac_transport
        stranger = _item_doc(asset_href=_MOVED_ASSET)
        stranger["collection"] = "a-different-collection"
        nameless = _item_doc(asset_href=_MOVED_ASSET)
        del nameless["collection"]
        for feature in (stranger, nameless):
            install({_ITEM: (404, None), _SEARCH: (200, {"features": [feature]})})
            result = await _resolve(item_href=_ITEM)
            assert not result.resolved
            # Bound to nothing, and inconclusive rather than withdrawn: a page
            # that does not honour the filters has not reported an absence.
            assert result.health == "inaccessible"

    @pytest.mark.parametrize("code", [500, 503, 403])
    async def test_a_search_that_could_not_be_carried_out_is_not_a_withdrawal(
        self, stac_transport, code: int
    ) -> None:
        """fix(#1266 review round 13): round 1 collapsed "looked and found
        nothing" into "could not look", on the reasoning that the item's own
        404 was authoritative anyway.

        But the verdict that collapse writes is `missing`, and `missing` is
        precisely what this codebase refuses to conclude from an inconclusive
        attempt everywhere else — while the item may simply have moved, which
        is the entire reason the search exists.
        """
        install, _ = stac_transport
        install({_ITEM: (404, None), _SEARCH: (code, None)})
        result = await _resolve(item_href=_ITEM)
        assert not result.resolved
        assert result.health == "inaccessible"
        assert result.detail in DETAIL_CODES

    async def test_a_catalog_offering_no_search_endpoint_keeps_the_items_verdict(
        self, stac_transport
    ) -> None:
        """A 404 from /search is the catalog saying there is nowhere to look,
        which leaves the item's own 404 as the last authoritative word.

        fix(#1266 review round 14): including its DETAIL. The search
        endpoint's `not_found` describes the wrong resource — the Source
        panel would tell a user the source was not found where it should say
        the item was withdrawn.
        """
        install, _ = stac_transport
        install({_ITEM: (404, None), _SEARCH: (404, None)})
        result = await _resolve(item_href=_ITEM)
        assert not result.resolved
        assert (result.health, result.detail) == ("missing", "item_withdrawn")

    async def test_a_search_that_never_reached_the_wire_keeps_the_item_contact(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 14): the item answered, so the origin WAS
        contacted.

        A search that fails before it reaches the wire — a DNS timeout, a
        first-hop policy refusal — reports `contacted=False` about itself,
        and copying that would erase a contact that demonstrably happened.
        `last_checked_at` records that GeoLens reached the origin at all.
        """
        install, _ = stac_transport

        def _handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == _SEARCH:
                raise SSRFError("private address")
            return httpx.Response(404)

        install(_handler)
        result = await _resolve(item_href=_ITEM)
        assert not result.resolved
        assert result.health == "inaccessible"
        assert result.contacted is True

    async def test_a_search_page_that_ignores_the_filters_proves_nothing(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 15): non-empty and non-matching is not
        absence.

        The request asks for one id in one collection with `limit: 1`, so an
        endpoint that ignores the filters has only ever had room to return an
        unrelated first row — which says nothing about whether this item
        still exists somewhere in the catalog, least of all that it does not.
        An EMPTY page is the catalog answering the question; a mismatched one
        is it answering a different question.
        """
        install, _ = stac_transport
        stranger = _item_doc(item_id="some-other-scene", asset_href=_MOVED_ASSET)
        install({_ITEM: (404, None), _SEARCH: (200, {"features": [stranger]})})
        result = await _resolve(item_href=_ITEM)
        assert not result.resolved
        assert result.health == "inaccessible"

        # ...while an empty page still earns the withdrawal verdict.
        install({_ITEM: (404, None), _SEARCH: (200, {"features": []})})
        empty = await _resolve(item_href=_ITEM)
        assert (empty.health, empty.detail) == ("missing", "item_withdrawn")

    async def test_a_permalink_body_must_affirm_the_stored_collection(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 18): where no URL can speak for the
        collection, the document has to.

        A permalink states no collection, so a permalink re-pointed at
        another collection's same-id item — in a body that omits its optional
        `collection` field — had nothing anywhere to contradict, and the
        bound key would then select the other collection's asset.
        """
        install, _ = stac_transport
        permalink = "https://origin.test/permalink/abc123"
        nameless = _item_doc(asset_href=_MOVED_ASSET, self_href=None)
        del nameless["collection"]
        install({permalink: (200, nameless), _MOVED_ASSET: (206, None)})

        result = await _resolve(item_href=permalink)
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unexpected_status")

        # Affirming it is all that was ever asked.
        install(
            {
                permalink: (200, _item_doc(asset_href=_MOVED_ASSET, self_href=None)),
                _MOVED_ASSET: (206, None),
            }
        )
        affirmed = await _resolve(item_href=permalink)
        assert affirmed.resolved
        assert affirmed.asset_href == _MOVED_ASSET

    async def test_a_keyed_binding_whose_asset_vanished_reports_removal(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 18): a binding that recorded its key knows
        exactly which entry disappeared.

        Reporting that as "cannot identify the asset" sent the reader to the
        wrong diagnosis, even though the item still publishes something the
        import rule would have picked.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        assets={"data": {"href": _MOVED_ASSET, "roles": ["data"]}}
                    ),
                )
            }
        )
        result = await _resolve(item_href=_ITEM, asset_key="visual")
        assert not result.resolved
        assert (result.health, result.detail) == ("missing", "not_found")

    async def test_a_redirect_into_another_collection_binds_nothing(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 17): the post-redirect URL states an
        identity, and round 15 made it authoritative.

        A stored URL that redirects to another collection's same-id item, in
        a body that omits its optional `collection` field, passed every check
        — and that URL is then the base the bound asset resolves against.
        """
        install, _ = stac_transport
        other_collection_url = f"{_ROOT}/collections/other/items/scene-1"
        body = _item_doc(asset_href=_MOVED_ASSET, self_href=None)
        del body["collection"]
        install({other_collection_url: (200, body), _MOVED_ASSET: (206, None)})

        result = await resolve_stac_binding(
            item_href=other_collection_url,
            item_id="scene-1",
            collection_id="scenes",
            asset_href=_ASSET,
            asset_key="data",
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unexpected_status")

    async def test_a_self_link_whose_hostname_does_not_resolve_is_refused(
        self, stac_transport, monkeypatch
    ) -> None:
        """fix(#1266 review round 16): the gap the probe alone leaves.

        The probe reports NXDOMAIN as `network_error`, indistinguishable from
        a host that is merely down — but the DOOR raises on it, before any
        fetch and before the search fallback can run. Storing such a pointer
        over a working one is therefore unrecoverable, which is why the
        door's own function is asked as well.
        """
        install, _ = stac_transport
        dead_self = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(asset_href=_MOVED_ASSET, self_href=dead_self),
                ),
                _MOVED_ASSET: (206, None),
            }
        )

        async def _validate(url: str) -> None:
            if url == dead_self:
                raise SSRFResolutionError("Could not resolve hostname")

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.validate_url_for_ssrf",
            _validate,
        )
        result = await _resolve(item_href=_ITEM)
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        # The asset moved; the pointer stayed the one the door still accepts.
        assert result.item_href == _ITEM

    async def test_a_self_link_that_answers_with_a_login_page_is_not_stored(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 19): 200 is not the same claim as "this
        serves the item".

        A self link behind an auth wall answers 200 with HTML, which a ranged
        GET cannot tell from a STAC item — and the next refresh then fails on
        it as inconclusive and never reaches the search fallback. The
        replacement is put through the next refresh's own first step instead.
        """
        install, _ = stac_transport
        login_page = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(asset_href=_MOVED_ASSET, self_href=login_page),
                ),
                # 200, and not an item.
                login_page: (200, {"message": "please sign in"}),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        assert result.item_href == _ITEM

    async def test_an_untrusted_self_link_does_not_steer_a_relative_asset(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 20): the self link steers TWO things.

        Validating it only on the way to storage left the asset base reading
        from an untrusted URL — so an item advertising a login page could
        still have a COG resolved under that page's path and persisted as
        this dataset's asset, which is worse than a stale pointer.
        """
        install, recorded = stac_transport
        login_page = "https://origin.test/login/scene-1"
        under_login = "https://origin.test/login/tiles/scene.tif"
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        self_href=login_page,
                        assets={"data": {"href": "tiles/scene.tif"}},
                    ),
                ),
                login_page: (200, {"message": "please sign in"}),
                under_login: (206, None),
                "https://origin.test/stac/collections/scenes/items/tiles/scene.tif": (
                    206,
                    None,
                ),
            }
        )
        result = await _resolve(item_href=_ITEM)
        # Whatever it resolved, it must not be the path under the login page.
        assert result.asset_href != under_login
        assert result.item_href == _ITEM

    async def test_a_replacement_without_the_bound_asset_is_not_adopted(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 20): the item is what a pointer addresses,
        the asset is what the dataset needs.

        An address that serves the item WITHOUT the bound asset is one the
        next refresh cannot get anything from — and it would not reach the
        search fallback either, because the item answered.
        """
        install, _ = stac_transport
        thinner = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(asset_href=_MOVED_ASSET, self_href=thinner),
                ),
                thinner: (
                    200,
                    _item_doc(
                        self_href=thinner,
                        assets={"thumbnail": {"href": "https://x.test/t.png"}},
                    ),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        assert result.item_href == _ITEM

    async def test_a_searched_item_advertising_the_stale_url_revalidates_it(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 21): the search path is reached BECAUSE the
        stored pointer 404s.

        A searched feature advertising that same stale URL was fast-pathed as
        "nothing to prove", which made a known-dead address the base a
        relative asset href resolves against — and a COG sitting at the
        resulting sibling path would have been adopted.
        """
        install, _ = stac_transport
        stale_sibling = f"{_ROOT}/collections/scenes/items/tiles/scene.tif"
        install(
            {
                _ITEM: (404, None),
                _SEARCH: (
                    200,
                    {
                        "features": [
                            _item_doc(
                                self_href=_ITEM,
                                assets={"data": {"href": "tiles/scene.tif"}},
                            )
                        ]
                    },
                ),
                stale_sibling: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        # The stale URL is not trusted as a base, so nothing is resolved
        # under it — the relative href has no address left to resolve against.
        assert result.asset_href != stale_sibling

    async def test_a_replacement_whose_bound_asset_has_no_href_is_not_adopted(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 21): present is not the same as usable.

        A STAC Asset Object requires an href, and a keyed empty object gives
        the next refresh nothing to resolve — which it would report as an
        unusable asset, again without reaching the search fallback.
        """
        install, _ = stac_transport
        thinner = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET, self_href=thinner)),
                thinner: (
                    200,
                    _item_doc(self_href=thinner, assets={"data": {}}),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        assert result.resolved
        assert result.item_href == _ITEM

    async def test_a_redirected_document_bases_relative_assets_on_where_it_came_from(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 22): the self link plays two roles.

        A document served from a new directory while still declaring the old
        self link resolved its relative assets under the STALE directory —
        and a COG sitting at that sibling path would have been adopted. The
        pointer is the address the publisher declares; the base is the
        address that answered.
        """
        install, _ = stac_transport
        served_from = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        correct = f"{_ROOT}/v2/collections/scenes/items/tiles/scene.tif"
        stale = f"{_ROOT}/collections/scenes/items/tiles/scene.tif"

        install(
            {
                # The stored URL redirects into a new directory...
                _ITEM: (302, None),
                # ...and the document served there still declares the old
                # self link, which is the fast path's input.
                served_from: (
                    200,
                    _item_doc(
                        self_href=_ITEM,
                        assets={"data": {"href": "tiles/scene.tif"}},
                    ),
                ),
                correct: (206, None),
                stale: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        assert result.resolved
        assert result.asset_href != stale
        assert result.asset_href == correct

    async def test_the_pointer_and_the_asset_come_from_one_document(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 23): one binding, one document.

        When two addresses for the same item give the bound key different
        hrefs, storing one document's pointer beside the other's href made
        this run adopt the first asset while the next run — reading the
        pointer it was handed — switched to the second.
        """
        install, _ = stac_transport
        canonical = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        newer_asset = "https://origin.test/v2/tiles/new.tif"
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_ASSET, self_href=canonical)),
                canonical: (
                    200,
                    _item_doc(asset_href=newer_asset, self_href=canonical),
                ),
                _ASSET: (206, None),
                newer_asset: (206, None),
            }
        )
        result = await _resolve(item_href=_ITEM)
        assert result.item_href == canonical
        # The asset comes from the document that pointer names, so a refresh
        # from the stored pointer would reach the same answer.
        assert result.asset_href == newer_asset

    async def test_a_binding_with_no_collection_borrows_one_from_its_url(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 24): `StacImportItem.collection` is optional.

        A binding that carries none skipped every collection comparison, so a
        stored `/collections/A/items/x` redirecting to `/collections/B/items/x`
        would rebind the dataset to B's keyed asset. The URL states the
        collection even when the binding does not.
        """
        install, _ = stac_transport
        other = f"{_ROOT}/collections/other/items/scene-1"
        body = _item_doc(asset_href=_MOVED_ASSET, self_href=None)
        del body["collection"]
        install({other: (200, body), _MOVED_ASSET: (206, None)})

        result = await resolve_stac_binding(
            item_href=_ITEM,
            item_id="scene-1",
            collection_id=None,
            asset_href=_ASSET,
            asset_key="data",
        )
        # _ITEM is not served; what matters is that the derived collection is
        # used at all, which the redirect case below exercises directly.
        assert not result.resolved

        install({_ITEM: (302, None), other: (200, body), _MOVED_ASSET: (206, None)})
        redirected = await resolve_stac_binding(
            item_href=_ITEM,
            item_id="scene-1",
            collection_id=None,
            asset_href=_ASSET,
            asset_key="data",
        )
        assert not redirected.resolved

    async def test_a_missing_new_asset_keeps_its_conclusive_verdict(
        self, stac_transport, monkeypatch
    ) -> None:
        """fix(#1266 review round 24): Titiler being unable to describe a
        missing object adds nothing.

        The probe already settled that the publisher's new href is gone, and
        replacing that with an inconclusive verdict threw away the one fact
        the run established.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (404, None),
            }
        )

        async def _unreadable(url: str):
            return None

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            _unreadable,
        )
        result = await _resolve(item_href=_ITEM)
        assert not result.resolved
        assert (result.health, result.detail) == ("missing", "not_found")

    async def test_the_projection_comes_from_the_document_the_asset_did(
        self, stac_transport, monkeypatch
    ) -> None:
        """fix(#1266 review round 24): a canonical document that supersedes
        the representation supersedes its projection too.

        fix(#1334 review): stubs the probe to report no CRS at all — its OWN
        reading would otherwise outrank the document's declared one
        (``reconcile_epsg``), which is a different concern from the one this
        test isolates: WHICH document's declaration wins, not probe-vs-
        declared precedence.
        """
        install, _ = stac_transport
        canonical = f"{_ROOT}/v2/collections/scenes/items/scene-1"
        newer_asset = "https://origin.test/v2/tiles/new.tif"
        canonical_doc = _item_doc(asset_href=newer_asset, self_href=canonical)
        canonical_doc["properties"] = {"proj:code": "EPSG:3857"}
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_ASSET, self_href=canonical)),
                canonical: (200, canonical_doc),
                _ASSET: (206, None),
                newer_asset: (206, None),
            }
        )

        async def _no_crs(url: str):
            return {"band_count": 1, "dtype": "uint16", "band_info": None}

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            _no_crs,
        )
        result = await _resolve(item_href=_ITEM)
        assert result.asset_href == newer_asset
        assert result.epsg == 3857

    async def test_a_self_link_that_redirects_into_a_blocked_target_is_refused(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 15): the submission-time validator checks
        the hostname it is handed and nothing further.

        A public self link whose first hop redirects into a blocked target
        clears it, gets stored over a working pointer, and then aborts every
        later fetch at the redirect — the unrecoverable shape, because the
        door refuses the dataset from then on. The replacement is proven
        through the safe client, which does the per-hop revalidation.
        """
        install, _ = stac_transport
        moved_self = f"{_ROOT}/v2/collections/scenes/items/scene-1"

        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == moved_self:
                # Public first hop, blocked target — what the per-hop hook
                # raises on and the submission-time check cannot see.
                raise SSRFError("redirect target is private")
            if url == _ITEM:
                return httpx.Response(
                    200, json=_item_doc(asset_href=_ASSET, self_href=moved_self)
                )
            return httpx.Response(206)

        install(_handler)
        result = await _resolve(item_href=_ITEM)
        assert result.resolved
        # The asset still resolves; the pointer stays the one that works.
        assert result.item_href == _ITEM

    async def test_a_deleted_item_the_search_cannot_find_is_missing(
        self, stac_transport
    ) -> None:
        install, _ = stac_transport
        install({_ITEM: (410, None), _SEARCH: (200, {"features": []})})
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET, asset_key=None
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("missing", "item_withdrawn")

    async def test_a_catalog_with_no_second_path_keeps_the_items_own_verdict(
        self, stac_transport
    ) -> None:
        """No derivable search root, so nothing can say where else to look.
        The item's 404 stands, which is the same verdict the probe writes for
        the same observation."""
        install, recorded = stac_transport
        odd_href = "https://origin.test/items/scene-1"
        install({odd_href: (404, None)})
        result = await _resolve(
            item_href=odd_href,
            item_id="scene-1",
            collection_id="scenes",
            asset_href=_ASSET,
        )
        assert (result.health, result.detail) == ("missing", "item_withdrawn")
        assert [str(r.url) for r in recorded] == [odd_href]

    @pytest.mark.parametrize("code", [401, 403, 500, 503, 418])
    async def test_an_inconclusive_answer_never_says_missing(
        self, stac_transport, code: int
    ) -> None:
        """The distinction the whole vocabulary exists for. A catalog that
        added authentication or fell over has not deleted anything, and
        writing ``missing`` would tell an operator to replace data that is
        still published."""
        install, recorded = stac_transport
        install({_ITEM: (code, None)})
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.health == "inaccessible"
        assert result.detail in DETAIL_CODES
        # No search either: the item's absence was never established, so
        # there is nothing to go looking for a new home for.
        assert [str(r.url) for r in recorded] == [_ITEM]

    async def test_an_answer_that_is_not_a_stac_item_is_inconclusive(
        self, stac_transport
    ) -> None:
        install, _ = stac_transport
        install({_ITEM: (200, {"type": "FeatureCollection", "features": []})})
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unexpected_status")

    async def test_both_paths_agree_on_a_document_that_is_not_an_item(
        self, stac_transport
    ) -> None:
        """One reading of one shape. The direct fetch and the re-search must
        not reach different verdicts about the same malformed answer."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (404, None),
                # Affirms the collection, so it is accepted as OUR item and
                # then judged on its shape — which is the property under test.
                _SEARCH: (
                    200,
                    {
                        "features": [
                            {
                                "id": "scene-1",
                                "collection": "scenes",
                                "assets": "nope",
                            }
                        ]
                    },
                ),
            }
        )
        searched = await resolve_stac_binding(item_href=_ITEM, collection_id="scenes")
        install({_ITEM: (200, {"type": "FeatureCollection", "features": []})})
        direct = await resolve_stac_binding(item_href=_ITEM, collection_id="scenes")
        assert (searched.health, searched.detail) == (direct.health, direct.detail)
        assert (direct.health, direct.detail) == ("inaccessible", "unexpected_status")

    async def test_a_stored_url_that_serves_a_different_item_binds_nothing(
        self, stac_transport
    ) -> None:
        """fix(#1266 review): a valid item is not the same claim as THIS item.

        A stored URL that redirects — a scene collapsed into a mosaic, a
        bucket serving a default document — hands back a perfectly well-formed
        item, and the asset chooser's last resort would then publish that
        stranger's primary asset as this dataset's raster.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(item_id="a-different-scene", asset_href=_MOVED_ASSET),
                )
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unexpected_status")

    async def test_an_item_that_names_another_collection_binds_nothing(
        self, stac_transport
    ) -> None:
        install, _ = stac_transport
        doc = _item_doc(asset_href=_MOVED_ASSET)
        doc["collection"] = "some-other-collection"
        install({_ITEM: (200, doc)})
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.health == "inaccessible"

    async def test_a_recorded_id_is_checked_even_when_the_url_states_none(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 9): the hole the URL-derived check left.

        A catalog outside the `/collections/{c}/items/{id}` layout states no
        identity in its URLs, so the derived check was skipped entirely and a
        canonical URL that later served a different item of the same
        collection passed — after which the asset chooser would republish
        that item's raster as this dataset. The binding carries the id now.
        """
        install, _ = stac_transport
        odd_href = "https://origin.test/stac/permalink/abc123"
        install(
            {
                odd_href: (
                    200,
                    _item_doc(item_id="a-different-scene", asset_href=_MOVED_ASSET),
                )
            }
        )
        result = await _resolve(
            item_href=odd_href,
            item_id="scene-1",
            collection_id="scenes",
            asset_href=_ASSET,
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unexpected_status")

    async def test_the_resolved_id_comes_back_to_be_stored(
        self, stac_transport
    ) -> None:
        """A dataset imported before the id was recorded gains one the first
        time it refreshes — but only where the answer could be checked, which
        for a legacy binding means the URL states the identity itself."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, item_id=None, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.item_id == "scene-1"

    async def test_a_legacy_permalink_binding_is_refused_before_it_is_asked(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 10): the residue of recording the id.

        A binding written before item ids were recorded, whose catalog
        publishes permalink-style URLs that state no identity either, gives a
        refresh nothing to check the publisher's answer against — and an
        unverified first answer would be adopted AND recorded as durable
        truth, leaving a wrong binding self-consistent forever. Nothing is
        fetched at all.
        """
        install, recorded = stac_transport
        permalink = "https://origin.test/stac/permalink/abc123"
        install({permalink: (200, _item_doc(item_id="somebody-elses-scene"))})
        result = await _resolve(
            item_href=permalink, item_id=None, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.contacted is False
        assert recorded == []

    async def test_a_catalog_whose_layout_hides_the_id_refreshes_on_the_binding(
        self, stac_transport
    ) -> None:
        """The contradiction test must not become a confirmation requirement.

        A catalog that does not use the standard item layout states no id in
        its URL, so the URL contradicts nothing — the recorded id is what the
        answer is checked against, and having one is what lets these catalogs
        refresh at all.
        """
        install, _ = stac_transport
        odd_href = "https://origin.test/stac/scenes/scene-1.json"
        install(
            {
                odd_href: (200, _item_doc(asset_href=_MOVED_ASSET, self_href=odd_href)),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=odd_href,
            item_id="scene-1",
            collection_id="scenes",
            asset_href=_ASSET,
        )
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        assert result.item_id == "scene-1"

    async def test_a_searched_items_relative_asset_resolves_against_its_self_link(
        self, stac_transport
    ) -> None:
        """fix(#1266 review): the base is the ITEM's address, not /search's.

        Joining a relative asset href against the search endpoint composes a
        path under the search URL — a different object, and possibly a live
        one, which is the worst kind of wrong answer here.
        """
        install, _ = stac_transport
        # Relative to the item at its NEW address. Against the /search
        # endpoint the same href would compose
        # https://origin.test/tiles/scene.tif, a different object entirely.
        moved_relative = f"{_ROOT}/v2/collections/scenes/tiles/scene.tif"
        install(
            {
                _ITEM: (404, None),
                _SEARCH: (
                    200,
                    {
                        "features": [
                            _item_doc(
                                self_href=_MOVED_ITEM,
                                assets={"data": {"href": "../tiles/scene.tif"}},
                            )
                        ]
                    },
                ),
                # The item's new address answers — a replacement pointer is
                # only adopted if GeoLens can actually read it.
                _MOVED_ITEM: (
                    200,
                    _item_doc(
                        self_href=_MOVED_ITEM,
                        assets={"data": {"href": "../tiles/scene.tif"}},
                    ),
                ),
                moved_relative: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == moved_relative
        assert result.item_href == _MOVED_ITEM

    async def test_a_self_link_that_addresses_another_item_is_not_trusted(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 2): the self link is now load-bearing.

        It is the base for relative assets and the pointer that gets stored,
        so a body that is right about its own id while its self link
        addresses a different scene must not walk the dataset there — the
        next refresh would derive its expected identity from that stored URL
        and agree with itself.
        """
        install, _ = stac_transport
        liar = f"{_ROOT}/collections/scenes/items/somebody-elses-scene"
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET, self_href=liar)),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        # The asset still resolves — the document IS this item by its own id —
        # but the contradictory pointer is dropped, not stored.
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        assert result.item_href == _ITEM

    async def test_a_self_link_under_another_collection_is_not_trusted(
        self, stac_transport
    ) -> None:
        install, _ = stac_transport
        liar = f"{_ROOT}/collections/other-collection/items/scene-1"
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET, self_href=liar)),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.item_href == _ITEM

    async def test_a_self_link_that_states_no_identity_is_still_trusted(
        self, stac_transport
    ) -> None:
        """Contradiction, not confirmation — again. A permalink service or a
        static catalog states no identity in its path and cannot disagree
        with anything."""
        install, _ = stac_transport
        permalink = "https://origin.test/permalink/abc123"
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET, self_href=permalink)),
                # It serves the item, which is the bar a replacement pointer
                # has to clear: GeoLens adopts only a pointer that would work.
                permalink: (
                    200,
                    _item_doc(asset_href=_MOVED_ASSET, self_href=permalink),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.item_href == permalink

    async def test_an_asset_the_ssrf_guard_refuses_is_never_adopted(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 4): a security property, not a health one.

        Every other probe verdict is a fact about the origin that the binding
        can carry — an asset that 404s is still where the publisher says it
        is. A policy block is a fact about GeoLens, and the stored href is
        read by the raster tile path, which hands http(s) values to
        Titiler/GDAL. Rule 2 is explicit that GDAL cannot be made
        redirect-safe from the inside, so the safe client's refusal is the
        only check that will ever run against it: adopting the href would
        launder an address straight past the guard that rejected it.
        """
        install, _ = stac_transport
        blocked = "https://origin.test/internal/scene.tif"

        def _handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == blocked:
                raise SSRFError("private address")
            return httpx.Response(200, json=_item_doc(asset_href=blocked))

        install(_handler)
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.asset_href is None
        assert (result.health, result.detail) == ("inaccessible", "blocked_by_policy")

    async def test_a_searched_item_with_no_trustworthy_url_declines_relative_assets(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 4): the round-2 fix, one branch over.

        Dropping a contradictory self link left `asset_base` falling back to
        the `/search` endpoint, so a relative href still composed a path under
        the query URL — and the danger is precisely that something might be
        served there.
        """
        install, _ = stac_transport
        liar = f"{_ROOT}/collections/scenes/items/somebody-elses-scene"
        install(
            {
                _ITEM: (404, None),
                _SEARCH: (
                    200,
                    {
                        "features": [
                            _item_doc(
                                self_href=liar,
                                assets={"data": {"href": "../tiles/scene.tif"}},
                            )
                        ]
                    },
                ),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.health == "inaccessible"

    async def test_a_searched_item_with_no_self_link_still_takes_absolute_assets(
        self, stac_transport
    ) -> None:
        """An absolute href addresses itself and needs no base, so the
        refusal above must not become a blanket one."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (404, None),
                _SEARCH: (
                    200,
                    {"features": [_item_doc(asset_href=_MOVED_ASSET, self_href=None)]},
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        # No self link means no better address to store than the one already
        # held, dead as it is — the next refresh searches again.
        assert result.item_href == _ITEM

    async def test_a_moved_asset_that_cannot_be_read_is_not_adopted(
        self, stac_transport, monkeypatch
    ) -> None:
        """fix(#1266 review round 5): a publisher's document saying where the
        asset is, is not the same fact as that asset being openable. Same
        discipline as the raster replace path's read-back of its own COG."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )

        async def _unreadable(url: str):
            return None

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            _unreadable,
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.health == "inaccessible"

    async def test_an_unchanged_asset_is_not_re_read_from_titiler(
        self, stac_transport, cog_info
    ) -> None:
        """The read is for the ADOPTION, so it happens only when something is
        adopted. An object replaced in place at an unchanged URL is the raster
        twin of the registered-table case, and re-reading every refresh would
        buy a Titiler round trip per refresh for it."""
        _described, calls = cog_info
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_metadata is None
        assert calls == []

    async def test_an_asset_href_too_long_for_the_column_is_refused(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 5): `datasets.origin_uri` is String(2000).

        The storable-href gate mirrors the import model's 4096 cap, which is
        right for `origin_ref` (JSONB) and more than the column can hold — so
        without this a 2050-character href would clear every check and then
        abort the success transaction, failing a refresh that had resolved.
        """
        install, _ = stac_transport
        long_href = "https://origin.test/tiles/" + ("a" * 2000) + ".tif"
        install({_ITEM: (200, _item_doc(asset_href=long_href)), long_href: (206, None)})
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert result.health == "inaccessible"

    async def test_a_self_link_the_policy_blocks_is_not_stored(
        self, stac_transport, monkeypatch
    ) -> None:
        """fix(#1266 review round 5): a pointer has to be one the DOOR will
        accept next time.

        The refresh door SSRF-validates `origin_ref.item_href` before it
        queues anything, so storing a self link on a blocked host would buy
        one successful refresh and then permanent 400s — with the usable
        pointer already overwritten.
        """
        install, _ = stac_transport
        blocked_item = f"{_ROOT}/v2/collections/scenes/items/scene-1"

        # fix(#1266 review round 15): refused through the SAFE CLIENT now, so
        # the block is driven from the transport rather than by stubbing the
        # submission-time validator. This is the first-hop shape; the
        # redirect shape, which only the per-hop hook can catch, has its own
        # test above.
        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == blocked_item:
                raise SSRFError("private address")
            if url == _ITEM:
                return httpx.Response(
                    200,
                    json=_item_doc(asset_href=_MOVED_ASSET, self_href=blocked_item),
                )
            return httpx.Response(206)

        install(_handler)
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        # The asset moved; the item pointer stayed the one that still works.
        assert result.item_href == _ITEM

    async def test_a_keyless_binding_whose_href_moved_refuses_to_guess(
        self, stac_transport
    ) -> None:
        """fix(#1266 review round 11): the last place a guess was dressed as
        a rule.

        With no recorded key and an href that has already moved, re-running
        the import's priority list is not identification — an item imported
        from `visual` that has since gained a `data` asset would be switched
        to `data`, served as that, recorded as that, and reported as a
        successful refresh. Which asset a dataset serves is not something a
        refresh may decide.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        assets={
                            "data": {"href": _MOVED_ASSET, "roles": ["data"]},
                            "visual": {"href": "https://origin.test/v2/vis.tif"},
                        }
                    ),
                )
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET, asset_key=None
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("inaccessible", "unexpected_status")

    async def test_a_keyed_binding_follows_the_move_it_could_not_guess(
        self, stac_transport
    ) -> None:
        """The same item, the same move, with the key recorded: resolved.

        This is what the refusal above costs and what recording the key buys
        — and one refresh while the href still resolves is enough to record
        it, so a dataset only sits in the refused state until its first
        successful refresh.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        assets={
                            "data": {"href": "https://origin.test/v2/data.tif"},
                            "visual": {"href": _MOVED_ASSET},
                        }
                    ),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM,
            collection_id="scenes",
            asset_href=_ASSET,
            asset_key="visual",
        )
        assert result.resolved
        assert (result.asset_key, result.asset_href) == ("visual", _MOVED_ASSET)

    async def test_an_empty_string_keyed_binding_follows_the_move_it_could_not_guess(
        self, stac_transport
    ) -> None:
        """fix(#1331): the same scenario as the ``visual`` case above, for the
        one key value truthiness treats as absent. Before the fix, the stored
        ``""`` key was ignored, the href match failed because the asset moved,
        and — since the item also gained a decoy the priority list would
        pick — the refresh reported the asset unidentified instead of
        recovering it by the key that still names it.

        The write-back carries ``""`` forward, not ``None``: capture does not
        refuse the empty string (it has no length problem an over-long key
        has), so the durable identity this resolve just used to find the
        moved asset survives to protect the NEXT move too — stripping it
        back to keyless here would only defer today's bug by one refresh.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        assets={
                            "": {"href": _MOVED_ASSET, "roles": ["data"]},
                            "visual": {"href": "https://origin.test/v2/vis.tif"},
                        }
                    ),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM,
            collection_id="scenes",
            asset_href=_ASSET,
            asset_key="",
        )
        assert result.resolved
        assert (result.asset_key, result.asset_href) == ("", _MOVED_ASSET)

    async def test_a_live_item_that_dropped_the_asset_is_missing(
        self, stac_transport
    ) -> None:
        """Authoritative, and distinct from a withdrawal: the item is still
        published and no longer carries anything this dataset can serve."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(assets={"thumbnail": {"href": "https://x.test/t"}}),
                )
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert not result.resolved
        assert (result.health, result.detail) == ("missing", "not_found")

    async def test_a_resolved_pointer_carries_the_assets_own_health(
        self, stac_transport
    ) -> None:
        """The item is authoritative about WHERE the asset is; the probe is
        authoritative about whether it is being served. Both are recorded,
        because a refresh that adopts a pointer it never contacted is how a
        success is reported over a dataset whose tiles have stopped working.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (404, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == _MOVED_ASSET
        assert (result.health, result.detail) == ("missing", "not_found")


# ---------------------------------------------------------------------------
# The key has to be RECORDED, or the identity rule has nothing to read
# ---------------------------------------------------------------------------


class TestAssetKeyCapture:
    def test_search_surfaces_the_key_beside_the_href(self) -> None:
        """The two halves of the asset's identity travel together or not at
        all: the href is what moves, the key is what still names the same
        asset afterwards."""
        from app.modules.catalog.sources.stac_router import StacItemSummary

        assert "data_asset_key" in StacItemSummary.model_fields

    def test_search_never_surfaces_a_key_import_would_reject(self) -> None:
        """fix(#1266 review round 8): one bound, applied at both ends.

        STAC puts no limit on an asset identifier, and the frontend echoes
        search results straight into the import request — so a key the import
        model rejects, surfaced by search, is a 422 for the caller's whole
        batch over an item that imported fine before asset keys existed. The
        same trap `self_link_href` documents for item hrefs, closed the same
        way: an over-long key is dropped at capture, and the item imports
        without one exactly as it used to.
        """
        from app.modules.catalog.sources.adapters.stac import (
            MAX_ASSET_KEY_CHARS,
            storable_asset_key,
        )

        assert storable_asset_key("data") == "data"
        assert storable_asset_key("k" * MAX_ASSET_KEY_CHARS) is not None
        assert storable_asset_key("k" * (MAX_ASSET_KEY_CHARS + 1)) is None
        assert storable_asset_key(None) is None

    def test_an_empty_string_key_is_a_storable_key(self) -> None:
        """fix(#1331): ``""`` is a legal JSON property name and clears the
        length bound, so there is no reason to refuse it at capture — unlike
        an over-long key, it has nowhere it fails to fit. What made it
        misbehave was every downstream consultation reading it with
        truthiness, which is fixed at the read sites (``is not None``); the
        capture bound is unrelated to that and leaves ``""`` alone."""
        from app.modules.catalog.sources.adapters.stac import storable_asset_key

        assert storable_asset_key("") == ""

    async def test_an_over_long_key_still_resolves_an_unmoved_asset(
        self, stac_transport
    ) -> None:
        """Identity is settled by the href before the bound is applied, so the
        asset is still found — the binding just carries no key, which is the
        state every dataset was in before this feature."""
        from app.modules.catalog.sources.adapters.stac import MAX_ASSET_KEY_CHARS

        install, _ = stac_transport
        long_key = "k" * (MAX_ASSET_KEY_CHARS + 1)
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(assets={long_key: {"href": _ASSET, "roles": ["data"]}}),
                ),
                _ASSET: (206, None),
            }
        )
        result = await _resolve(
            item_href=_ITEM, collection_id="scenes", asset_href=_ASSET
        )
        assert result.resolved
        assert result.asset_href == _ASSET
        assert result.asset_key is None

    async def test_import_records_the_key_search_supplied(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """fix(#1266 review round 4): end to end, or the mechanism is inert.

        Without this the key stays unwritten on every new import, and the
        first refresh after a move falls back to re-running the import's
        priority list — which silently switches a dataset imported from
        `visual` onto a `data` asset the item has gained since.
        """
        item_id = f"key-{uuid.uuid4().hex[:8]}"
        with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://origin.test/v1",
                    "items": [
                        {
                            "id": item_id,
                            "collection": "scenes",
                            "title": "Asset key capture",
                            "data_asset_href": f"https://origin.test/{item_id}.tif",
                            "data_asset_key": "B04",
                            "item_href": f"https://origin.test/items/{item_id}",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 4326,
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        dataset_id = uuid.UUID(resp.json()["results"][0]["dataset_id"])
        dataset = await _reload(dataset_id)
        assert dataset.origin_ref["asset_key"] == "B04"
        # The item's own identity, recorded from a field the request already
        # carried — the system-managed binding, never the PATCHable filename.
        assert dataset.origin_ref["item_id"] == item_id

    async def test_an_older_client_that_sends_no_key_still_imports(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Optional, because the first refresh recovers the key by matching
        the stored href. What recording it at import buys is the one case
        that recovery cannot cover — the href moving first."""
        item_id = f"nokey-{uuid.uuid4().hex[:8]}"
        with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://origin.test/v1",
                    "items": [
                        {
                            "id": item_id,
                            "collection": "scenes",
                            "title": "No asset key",
                            "data_asset_href": f"https://origin.test/{item_id}.tif",
                            "bbox": [-1, -1, 1, 1],
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        dataset_id = uuid.UUID(resp.json()["results"][0]["dataset_id"])
        dataset = await _reload(dataset_id)
        assert "asset_key" not in dataset.origin_ref

    async def test_import_records_an_empty_string_key(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """fix(#1331): a searched item may key its data asset under ``""``,
        and the import request echoes back whatever search surfaced —
        including that. Recording it is what lets the FIRST refresh after a
        move recover the asset by identity instead of falling back to a
        keyless guess; the length bound is the only thing capture refuses,
        and ``""`` does not run into it."""
        item_id = f"emptykey-{uuid.uuid4().hex[:8]}"
        with patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://origin.test/v1",
                    "items": [
                        {
                            "id": item_id,
                            "collection": "scenes",
                            "title": "Empty asset key",
                            "data_asset_href": f"https://origin.test/{item_id}.tif",
                            "data_asset_key": "",
                            "item_href": f"https://origin.test/items/{item_id}",
                            "bbox": [-1, -1, 1, 1],
                            "epsg": 4326,
                            "keywords": [],
                        }
                    ],
                    "visibility": "private",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        dataset_id = uuid.UUID(resp.json()["results"][0]["dataset_id"])
        dataset = await _reload(dataset_id)
        assert dataset.origin_ref["asset_key"] == ""


# ---------------------------------------------------------------------------
# The door
# ---------------------------------------------------------------------------


class TestDispatch:
    async def test_a_stac_dataset_is_admitted_through_the_shared_machinery(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["origin_kind"] == "stac"
        assert body["trigger"] == "api"
        assert body["status"] == "pending"

        run = await _run_for(dataset.id)
        assert run is not None
        assert (run.origin_kind, run.status, run.trigger) == ("stac", "pending", "api")
        assert run.triggered_by == admin_id
        task.defer_async.assert_awaited_once()
        deferred = task.defer_async.await_args.kwargs
        assert deferred["dataset_id"] == str(dataset.id)
        assert deferred["job_id"] == body["job_id"]
        # The dispatch carries no pointer: the worker reads the binding, which
        # is the property that makes this door unable to re-point a dataset.
        assert "source_url" not in deferred
        assert "item_href" not in deferred

        job = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == uuid.UUID(body["job_id"]))
            )
        ).scalar_one()
        # NOT `reupload`: two pieces of shared SQL key off that marker to
        # reason about swaps this task never performs.
        assert job.user_metadata["refresh"] is True
        assert "reupload" not in job.user_metadata
        assert job.user_metadata["origin_kind"] == "stac"

    async def test_a_second_refresh_is_refused_while_one_is_active(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Admission control is the shared partial unique index, not a check
        in this handler — a double click cannot admit two runs."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        await _dispatch(client, admin_auth_header, dataset.id)

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "dataset_busy"

    async def test_a_binding_with_no_item_href_cannot_be_refreshed(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Recoverable by re-importing, and told apart from the kinds that
        have no origin at all — that difference is the difference between
        useful advice and a shrug."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, item_href=None
        )
        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "origin_unavailable"
        assert detail["origin_kind"] == "stac"
        assert await _run_for(dataset.id) is None

    async def test_a_binding_whose_identity_cannot_be_checked_is_refused(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Refused at the door, so the caller learns immediately and no run
        row is spent on a binding that could never be verified."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session,
            created_by=admin_id,
            item_href="https://origin.test/stac/permalink/abc123",
            item_id=None,
        )
        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "origin_unavailable"
        assert await _run_for(dataset.id) is None

    async def test_a_credential_is_refused_rather_than_dropped(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Answering 202 to a request that handed GeoLens a secret it silently
        discarded leaves the caller no way to learn their token went nowhere."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                headers=admin_auth_header,
                json={"token": "not-applicable-here"},
            )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "credential_not_applicable"
        assert await _run_for(dataset.id) is None

    async def test_a_stored_url_that_no_longer_passes_ssrf_is_refused(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Rule 2: the pointer was a catalog's when import stored it, and DNS
        moves. Before the reservation, so a refused request leaves no run row."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        with patch.object(
            router_refresh,
            "validate_url_for_ssrf",
            AsyncMock(side_effect=router_refresh.SSRFError("blocked")),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 400, resp.text
        assert await _run_for(dataset.id) is None

    async def test_an_upload_still_gets_the_kind_specific_refusal(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """Regression on the split: adding a third strategy must not change
        what the kinds with no origin are told."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(
            test_db_session, created_by=admin_id, source_format="geojson"
        )
        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "refresh_not_applicable"


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------


class TestWorker:
    async def test_a_moved_asset_is_picked_up_and_served_from_the_new_href(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The acceptance criterion, stated as the issue states it."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, source_health="missing"
        )
        before_version = dataset.tile_cache_version
        before_ingested = (await _raster_asset(dataset.id)).ingested_at

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.origin_ref["asset_href"] == _MOVED_ASSET
        assert refreshed.origin_uri == _MOVED_ASSET
        # The key is written back, so the NEXT move is recognised by identity
        # rather than by re-running the import's default choice.
        assert refreshed.origin_ref["asset_key"] == "data"
        assert refreshed.origin_ref["item_href"] == _ITEM
        assert refreshed.origin_ref["item_id"] == "scene-1"
        assert refreshed.origin_ref["collection_id"] == "scenes"
        # What actually serves — the address AND the description of what is
        # at it, because the tile proxy builds its parameters from the latter.
        assert await _asset_uri(dataset.id) == _MOVED_ASSET
        described = await _raster_asset(dataset.id)
        assert described.band_count == 1
        assert described.dtype == "uint16"
        assert described.nodata == "0"
        assert described.band_info == [{"min": 0, "max": 4095, "mean": 1200}]
        # One integer band is imagery, not elevation.
        assert described.is_dem is False
        # fix(#1334): the moved object's own CRS, from the same probe as
        # band_count/dtype/nodata — not left stale like the fields above
        # would be if the refresh only wrote the address.
        assert described.crs_wkt == (
            'PROJCS["WGS 84 / UTM zone 33N",AUTHORITY["EPSG","32633"]]'
        )
        # fix(#1375): and the pixel geometry, which a move is more likely to
        # change than anything else here — a re-tiled or reprojected
        # replacement is exactly where the old resolution stops describing
        # the new object.
        assert described.res_x == pytest.approx(30.0)
        assert described.res_y == pytest.approx(30.0)
        assert described.is_rotated is False

        # A moved member has to read as newer than any VRT built on it: a
        # mosaic that recorded no `built_from` is judged by this stamp alone,
        # and it still embeds the old URL.
        assert described.ingested_at is not None
        assert described.ingested_at > before_ingested
        # The georeferencing moves with the object, from the item that
        # publishes it — the same source the import path reads.
        assert described.epsg == 32633
        assert refreshed.srid == 32633
        # The tile URL has to change too, or browser and CDN caches keep
        # serving the old bytes.
        assert refreshed.tile_cache_version != before_version
        # The stale `missing` verdict is replaced by what this run observed,
        # through the probe's classifier rather than a second one.
        assert refreshed.source_health == "healthy"
        assert refreshed.last_checked_at is not None

        run = await _run_for(dataset.id)
        assert run.status == "succeeded"
        assert run.error_code is None

    async def test_a_refresh_without_a_transform_leaves_pixel_geometry_alone(
        self, client, admin_auth_header, test_db_session, stac_transport, monkeypatch
    ) -> None:
        """fix(#1375 review): the three affine-derived columns are one fact.

        ``fetch_cog_info``'s transform probe is optional — ``/cog/info`` can
        answer while ``/cog/stac`` fails — and an earlier version of this
        change turned that partial result into ``is_rotated=False``. That is
        not a missing value but a wrong measurement: the column is NOT NULL
        and cannot say "unknown", and ``_check_rotation`` (VAL-07) rejects a
        VRT source only when the flag is TRUE, so a fabricated ``False``
        would walk a rotated replacement straight through the gate built to
        stop it. A remote asset is an eligible VRT source, so that path is
        reachable rather than theoretical.

        The row here is seeded as rotated with a known resolution, then
        refreshed by a probe that establishes no transform. All three must
        survive: stale is the lesser wrong, and it is the conservative
        direction for every consumer of these columns.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, source_health="missing"
        )
        await test_db_session.execute(
            text(
                "UPDATE catalog.raster_assets SET is_rotated = true, "
                "res_x = 30.0, res_y = 30.0 WHERE dataset_id = :did"
            ).bindparams(did=dataset.id)
        )
        await test_db_session.commit()

        # A probe that read the COG but not its transform: /cog/info answered,
        # /cog/stac did not. The three affine keys are ABSENT, which is the
        # shape fetch_cog_info actually returns in that case.
        async def _no_transform(url: str):
            return {
                "band_count": 1,
                "dtype": "uint16",
                "width": 512,
                "height": 512,
                "nodata": 0,
                "band_info": [{"min": 0, "max": 4095, "mean": 1200}],
                "crs_wkt": 'PROJCS["WGS 84 / UTM zone 33N",AUTHORITY["EPSG","32633"]]',
                "epsg": 32633,
            }

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            _no_transform,
        )

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        # The move itself still happens — a missing transform degrades the
        # description, it does not block adoption.
        assert await _asset_uri(dataset.id) == _MOVED_ASSET
        described = await _raster_asset(dataset.id)
        assert described.band_count == 1

        assert described.is_rotated is True, (
            "an unmeasured probe must not assert axis-alignment — VAL-07 only "
            "rejects a rotated VRT source when this flag is true"
        )
        assert described.res_x == pytest.approx(30.0)
        assert described.res_y == pytest.approx(30.0)

    async def test_a_refresh_prefers_the_probed_epsg_over_the_items_declared_one(
        self, client, admin_auth_header, test_db_session, stac_transport, monkeypatch
    ) -> None:
        """fix(#1334 review): the moved item declares EPSG:32633
        (``_item_doc``'s default ``proj:code``), while the probe that
        actually opened the new bytes reports a different CRS — the raster
        row and the dataset's srid follow the probe, not the item, so
        ``RasterAsset.to_stac_properties()`` cannot publish a ``proj:code``
        and a ``proj:wkt2`` that name different projections.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )

        async def _disagreeing_probe(url: str):
            return {
                "band_count": 1,
                "dtype": "uint16",
                "nodata": 0,
                "band_info": None,
                "crs_wkt": 'PROJCS["WGS 84 / UTM zone 21N",AUTHORITY["EPSG","32621"]]',
                "epsg": 32621,
            }

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            _disagreeing_probe,
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        described = await _raster_asset(dataset.id)
        assert described.epsg == 32621
        refreshed = await _reload(dataset.id)
        assert refreshed.srid == 32621

    async def test_a_move_to_an_elevation_raster_reclassifies_it(
        self, client, admin_auth_header, test_db_session, stac_transport, monkeypatch
    ) -> None:
        """fix(#1266 review round 6): the tile proxy branches on `is_dem`
        BEFORE it looks at band metadata, so a stale flag renders a new
        elevation raster as ordinary imagery — and the reverse case requests
        RGB with algorithm=terrainrgb.

        Re-derived by the same rule every other raster path uses, over an
        owner's PATCH of the flag, with the precedent the raster replace path
        set: the classification describes the object, and the object is what
        just changed.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )

        async def _elevation(url: str):
            return {"band_count": 1, "dtype": "float32", "band_info": None}

        monkeypatch.setattr(
            "app.modules.catalog.sources.stac_resolve_asset_gate.fetch_cog_info",
            _elevation,
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        assert (await _raster_asset(dataset.id)).is_dem is True

    async def test_a_moved_asset_brings_its_footprint_with_it(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """fix(#1266 review round 25): a re-tiled scene comes with a new bbox.

        A dataset still advertising the old one lies to every spatial search
        and map-bounds read — the same staleness the registered-table
        strategy corrects when it rewrites an extent.
        """
        install, _ = stac_transport
        moved = _item_doc(asset_href=_MOVED_ASSET)
        moved["bbox"] = [20.0, 55.0, 21.0, 56.0]
        install({_ITEM: (200, moved), _MOVED_ASSET: (206, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        async with _fresh_session() as session:
            extent = await session.scalar(
                text(
                    "SELECT ST_AsText(ST_Envelope(spatial_extent)) "
                    "FROM catalog.records r "
                    "JOIN catalog.datasets d ON d.record_id = r.id "
                    "WHERE d.id = :dataset_id"
                ),
                {"dataset_id": dataset.id},
            )
        assert extent is not None
        # The new footprint, not the one imported.
        assert "20" in extent and "55" in extent

    def test_a_three_dimensional_bbox_keeps_its_horizontal_pair(self) -> None:
        """fix(#1266 review round 26): a bbox may be SIX values.

        `minx, miny, minz, maxx, maxy, maxz` sliced to its first four reads
        the elevation as east and the longitude as north, and writes a
        corrupted extent. `parse_bbox` already reduces 3D bboxes the same way.
        """
        assert stac_resolve._horizontal_bbox([10.0, 45.0, 11.0, 46.0]) == [
            10.0,
            45.0,
            11.0,
            46.0,
        ]
        assert stac_resolve._horizontal_bbox(
            [10.0, 45.0, 100.0, 11.0, 46.0, 900.0]
        ) == [10.0, 45.0, 11.0, 46.0]
        assert stac_resolve._horizontal_bbox([10.0, 45.0, 11.0]) is None
        # SEC-FU-06's rule, which `parse_bbox` already applies: JSON 1e400
        # parses as infinity and PostGIS handles it inconsistently.
        assert stac_resolve._horizontal_bbox([10.0, 45.0, float("inf"), 46.0]) is None
        assert stac_resolve._horizontal_bbox([10.0, float("nan"), 11.0, 46.0]) is None
        assert stac_resolve._horizontal_bbox([10.0, 45.0, "x", 46.0]) is None
        assert stac_resolve._horizontal_bbox(None) is None

    async def test_a_null_collection_binding_learns_its_collection(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The retention half of the null-collection fix.

        A binding imported with `collection=null` — which `StacImportItem`
        permits — has none of its own, so the stored item URL stands in for
        verification. Storing it back means the NEXT refresh checks against a
        stored value rather than re-deriving one, the same way `item_id` is
        learned.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, collection_id=None
        )
        assert "collection_id" not in dataset.origin_ref

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        # Read out of `/collections/scenes/items/scene-1`, and now stored.
        assert refreshed.origin_ref["collection_id"] == "scenes"

    async def test_a_stored_collection_is_never_replaced_by_the_items_own(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """Learning a value the URL already stated is one thing; taking one
        from the re-fetched item is a rebinding, and is not done."""
        install, _ = stac_transport
        moved = _item_doc(asset_href=_MOVED_ASSET)
        moved["collection"] = "scenes"
        install({_ITEM: (200, moved), _MOVED_ASSET: (206, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.origin_ref["collection_id"] == "scenes"

    async def test_an_unchanged_item_dates_the_refresh_without_rebinding(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The common case. Asking the publisher and being told nothing moved
        is a successful refresh — and it must not rewrite a binding it agreed
        with, because ``set_dataset_origin`` clears probe state on every
        write."""
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, asset_key="data"
        )
        before_version = dataset.tile_cache_version
        before_refreshed = dataset.last_refreshed_at

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.origin_ref["asset_href"] == _ASSET
        assert refreshed.origin_uri == _ASSET
        assert refreshed.tile_cache_version == before_version
        assert refreshed.last_refreshed_at > before_refreshed
        assert refreshed.source_health == "healthy"
        assert (await _run_for(dataset.id)).status == "succeeded"

    async def test_a_deleted_item_fails_the_run_and_keeps_the_old_pointer(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """Invariant 10, for an origin kind whose pointer IS its data."""
        install, _ = stac_transport
        install({_ITEM: (404, None), _SEARCH: (200, {"features": []})})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        before_refreshed = dataset.last_refreshed_at
        before_version = dataset.tile_cache_version

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.origin_ref["asset_href"] == _ASSET
        assert refreshed.origin_uri == _ASSET
        assert refreshed.origin_ref["item_href"] == _ITEM
        assert await _asset_uri(dataset.id) == _ASSET
        assert refreshed.last_refreshed_at == before_refreshed
        assert refreshed.tile_cache_version == before_version
        assert refreshed.source_health == "missing"
        assert refreshed.source_health_detail == "item_withdrawn"
        # The attempt reached the origin and got an answer, which is exactly
        # what the contact clock records.
        assert refreshed.last_checked_at is not None

        run = await _run_for(dataset.id)
        assert run.status == "failed"
        assert run.error_code == "source_missing"
        assert run.error_message == tasks_stac_refresh._WITHDRAWN_MESSAGE

    async def test_a_removed_asset_is_diagnosed_as_itself_not_a_withdrawal(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """fix(#1266 review round 17): two things are missing-shaped.

        The ITEM being gone and the ASSET being gone from a live item are not
        the same thing to the person reading the history, and the second one
        was being told the item disappeared and to re-import from a live one
        — advice pointing at the item they already have.
        """
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(assets={"thumbnail": {"href": "https://x.test/t.png"}}),
                )
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute(test_db_session, payload)

        run = await _run_for(dataset.id)
        assert run.status == "failed"
        assert run.error_code == "source_missing"
        assert run.error_message == tasks_stac_refresh._ASSET_REMOVED_MESSAGE
        refreshed = await _reload(dataset.id)
        assert refreshed.source_health == "missing"
        assert refreshed.source_health_detail == "not_found"
        # Invariant 10 holds either way.
        assert refreshed.origin_uri == _ASSET

    async def test_an_unreachable_catalog_leaves_the_stored_verdict_alone(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """A 5xx establishes nothing about the origin. Overwriting a
        conclusive verdict with an inconclusive attempt would make the column
        report the last REQUEST rather than the last thing GeoLens learned."""
        install, _ = stac_transport
        install({_ITEM: (503, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, source_health="healthy"
        )

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.source_health == "healthy"
        assert refreshed.origin_uri == _ASSET
        run = await _run_for(dataset.id)
        assert run.status == "failed"
        assert run.error_code == "source_inaccessible"

    async def test_an_inconclusive_failure_still_dates_the_contact(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """fix(#1266 review round 3): `last_checked_at` means the last time
        GeoLens contacted the origin AT ALL, success or failure.

        A 5xx establishes nothing about where the asset is, so no verdict is
        written — but the publisher answered, and the failure case is the one
        an operator most needs dated. Exactly one writer does it: the health
        stamp when it has a verdict, the run finalizer when it does not.
        """
        install, _ = stac_transport
        install({_ITEM: (503, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(
            test_db_session, created_by=admin_id, source_health="healthy"
        )
        before = datetime.now(timezone.utc)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.last_checked_at is not None
        assert refreshed.last_checked_at >= before - timedelta(seconds=5)
        # ...and still no verdict, because none was established.
        assert refreshed.source_health == "healthy"

    async def test_a_refusal_that_never_left_geolens_does_not_date_a_contact(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The other half of that contract. An SSRF policy refusal happens
        before any packet goes out, so stamping it would overwrite a real
        earlier contact time with a policy-check time."""
        install, _ = stac_transport
        install(_raising(lambda _req: SSRFError("private address")))
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        assert refreshed.last_checked_at is None
        assert refreshed.source_health is None

    async def test_a_rebind_during_the_fetch_discards_the_answer(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The window this strategy actually has: the publisher is asked
        while a raster replace or a re-upload commits a new binding. Applying
        an answer about the OLD origin over the top would undo a rebind that
        had already succeeded."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (200, _item_doc(asset_href=_MOVED_ASSET)),
                _MOVED_ASSET: (206, None),
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        payload = await _dispatch(client, admin_auth_header, dataset.id)

        rebound_href = "https://elsewhere.test/tiles/other.tif"
        dataset_id = dataset.id
        _real_resolve = stac_resolve.resolve_stac_binding

        async def _rebind_mid_flight(**kwargs):
            """Resolve for real, then let another writer win the race."""
            resolution = await _real_resolve(**kwargs)
            async with _fresh_session() as session:
                await session.execute(
                    Dataset.__table__.update()
                    .where(Dataset.id == dataset_id)
                    .values(origin_uri=rebound_href)
                )
                await session.commit()
            return resolution

        with patch.object(stac_resolve, "resolve_stac_binding", _rebind_mid_flight):
            with pytest.raises(Exception):
                await _execute(test_db_session, payload)

        refreshed = await _reload(dataset.id)
        # The concurrent write stands; the refresh's answer is thrown away.
        assert refreshed.origin_uri == rebound_href
        assert refreshed.origin_ref["asset_href"] == _ASSET
        run = await _run_for(dataset.id)
        assert run.status == "failed"
        assert run.error_code == "superseded"

    async def test_a_run_row_exists_for_every_outcome(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """Decision 4b: the row is created at DISPATCH, so a worker that dies
        mid-fetch still leaves a trace."""
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        pending = await _run_for(dataset.id)
        assert pending.status == "pending"
        assert pending.started_at is not None

        await _execute(test_db_session, payload)
        finished = await _run_for(dataset.id)
        assert finished.id == pending.id
        assert finished.status == "succeeded"
        assert finished.finished_at is not None
        assert finished.claimed_at is not None
        # No data moved, so there is no new version of it to point at.
        assert finished.dataset_version_id is None


class TestOriginAssetRepair:
    """feat(#1692): the refresh repairs the served origin asset.

    The import persists the origin item's primary data asset as a
    ``dataset_assets`` row, which is what puts a COG href a generic STAC
    client can read on the items GeoLens serves. The refresh upserts that
    same row on every success — for a dataset imported before the row
    existed, that upsert IS the backfill.
    """

    async def test_a_refresh_backfills_the_served_origin_asset(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """A pre-#1692 dataset gains the row from an UNCHANGED answer.

        ``_stac_dataset`` writes no ``dataset_assets`` row — the exact shape
        every by-reference dataset had before the import started persisting
        one — so a refresh that moved nothing must still create it, or the
        backfill story only covers datasets whose asset happens to move.
        """
        install, _ = stac_transport
        install({_ITEM: (200, _item_doc()), _ASSET: (206, None)})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        assert await _origin_asset_rows(dataset.id) == []

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        rows = await _origin_asset_rows(dataset.id)
        assert len(rows) == 1
        assert rows[0].key == "data"
        assert rows[0].href == _ASSET
        # From the item document's asset entry, not invented locally.
        assert rows[0].media_type == "image/tiff"
        assert rows[0].roles == ["data"]

        # Idempotent: a second refresh rewrites the row it already wrote.
        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)
        rows = await _origin_asset_rows(dataset.id)
        assert len(rows) == 1
        assert rows[0].href == _ASSET

    async def test_a_moved_asset_moves_the_served_row_with_it(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """The row the import wrote follows the publisher's move — href AND
        media type, both read from the live item document."""
        install, _ = stac_transport
        install(
            {
                _ITEM: (
                    200,
                    _item_doc(
                        assets={
                            "data": {
                                "href": _MOVED_ASSET,
                                "roles": ["data"],
                                "type": (
                                    "image/tiff; application=geotiff; "
                                    "profile=cloud-optimized"
                                ),
                            }
                        }
                    ),
                ),
                _MOVED_ASSET: (206, None),
            }
        )
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)
        # The row as the import writes it, pointing at the pre-move href.
        test_db_session.add(
            DatasetAsset(
                dataset_id=dataset.id,
                key="data",
                href=_ASSET,
                media_type="image/tiff",
                roles=["data"],
            )
        )
        await test_db_session.commit()

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        await _execute(test_db_session, payload)

        rows = await _origin_asset_rows(dataset.id)
        assert len(rows) == 1
        assert rows[0].href == _MOVED_ASSET
        assert rows[0].media_type == (
            "image/tiff; application=geotiff; profile=cloud-optimized"
        )
        assert rows[0].roles == ["data"]

    async def test_a_failed_refresh_repairs_no_asset_row(
        self, client, admin_auth_header, test_db_session, stac_transport
    ) -> None:
        """Invariant 10 extends to the served row: a refresh that resolved
        nothing backfills nothing."""
        install, _ = stac_transport
        # Everything 404s: the item is gone and the search finds nothing.
        install({})
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        payload = await _dispatch(client, admin_auth_header, dataset.id)
        with pytest.raises(Exception):
            await _execute(test_db_session, payload)

        assert (await _run_for(dataset.id)).status == "failed"
        assert await _origin_asset_rows(dataset.id) == []


# ---------------------------------------------------------------------------
# The probe is still a reporter
# ---------------------------------------------------------------------------


async def test_the_probe_path_still_never_mutates_a_pointer(
    client, admin_auth_header, test_db_session, stac_transport
) -> None:
    """Regression on #1222's contract, now that something else DOES rewrite
    bindings. The probe writes health and a contact time; the pointer, the
    asset row and the freshness are the refresh executor's alone.
    """
    install, _ = stac_transport
    install(
        {
            _ITEM: (404, None),
            _ASSET: (404, None),
            # Published, and irrelevant: the probe must not go looking.
            _SEARCH: (200, {"features": [_item_doc(asset_href=_MOVED_ASSET)]}),
        }
    )
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _stac_dataset(test_db_session, created_by=admin_id)
    before_refreshed = dataset.last_refreshed_at

    resp = await client.post(
        f"/datasets/{dataset.id}/source-health/", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_health"] == "missing"

    probed = await _reload(dataset.id)
    assert probed.origin_uri == _ASSET
    assert probed.origin_ref["asset_href"] == _ASSET
    assert probed.origin_ref["item_href"] == _ITEM
    assert await _asset_uri(dataset.id) == _ASSET
    assert probed.last_refreshed_at == before_refreshed
    assert await _run_for(dataset.id) is None
