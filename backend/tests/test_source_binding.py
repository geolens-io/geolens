"""The source binding's seams: the "same stored pointer" check (``bound_pointer``
and ``still_bound``) and the typed read of each kind (``read_source``)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import update

import app.core.db as db_module
from app.modules.catalog.datasets.api.router_refresh import _SERVICE_TYPE_LABELS
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.dataset_origin import (
    SERVICE_SOURCE_FORMATS,
    BoundPointer,
    PostgisSource,
    ServiceSource,
    StacSource,
    Unavailable,
    bound_pointer,
    read_source,
    set_dataset_origin,
    set_postgis_origin,
    still_bound,
)
from tests.factories import create_dataset, get_user_id

_WFS = "https://services.example.test/wfs"
_REF = {"kind": "service", "service_type": "wfs", "url": _WFS, "layer_id": "roads"}


def _row(origin_ref, *, origin_uri=_WFS, source_format="wfs"):
    return SimpleNamespace(
        origin_uri=origin_uri, origin_ref=origin_ref, source_format=source_format
    )


class TestBoundPointer:
    def test_reads_the_three_columns_as_a_plain_triple_too(self) -> None:
        pointer = bound_pointer(_row(_REF))
        assert pointer == BoundPointer(_WFS, _REF, "wfs") == (_WFS, _REF, "wfs")

    def test_key_order_is_not_a_rebind(self) -> None:
        reordered = dict(reversed(list(_REF.items())))
        assert bound_pointer(_row(reordered)) == bound_pointer(_row(_REF))

    @pytest.mark.parametrize(
        "changed",
        [
            _row({**_REF, "auth_required": True}),
            _row({**_REF, "item_id": "abc123", "portal_url": "https://example.test"}),
            _row(_REF, origin_uri=f"{_WFS}/roads"),
            _row(_REF, source_format="ogcapi_features"),
            _row(None),
        ],
        ids=["auth_required", "portal_link", "uri", "format", "ref_cleared"],
    )
    def test_any_difference_in_the_whole_triple_is_a_rebind(self, changed) -> None:
        assert bound_pointer(changed) != bound_pointer(_row(_REF))


async def _stamp(dataset_id, pointer) -> int:
    """Date contact under ``still_bound`` in a fresh session; the rows it matched."""
    async with db_module.async_session() as session:
        result = await session.execute(
            update(Dataset)
            .where(still_bound(Dataset, dataset_id, pointer))
            .values(last_checked_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return result.rowcount


async def _dataset(session, source_format: str | None) -> Dataset:
    return await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name="Still Bound",
        visibility="private",
        source_format=source_format,
    )


def _bind_service(dataset: Dataset, **extra) -> None:
    set_dataset_origin(
        dataset,
        "service",
        uri=_WFS,
        service_type="wfs",
        url=_WFS,
        layer_id="roads",
        **extra,
    )


@pytest.mark.anyio
class TestStillBound:
    async def _service_dataset(self, session) -> Dataset:
        dataset = await _dataset(session, "wfs")
        _bind_service(dataset)
        await session.commit()
        return dataset

    async def test_a_rebind_that_committed_first_matches_nothing(
        self, test_db_session
    ) -> None:
        dataset = await self._service_dataset(test_db_session)
        read = bound_pointer(dataset)
        set_dataset_origin(dataset, "upload", filename="roads.gpkg")
        dataset.source_format = "gpkg"
        await test_db_session.commit()

        assert await _stamp(dataset.id, read) == 0
        assert await _stamp(dataset.id, bound_pointer(dataset)) == 1

    async def test_an_auth_required_flip_matches_nothing(self, test_db_session) -> None:
        dataset = await self._service_dataset(test_db_session)
        read = bound_pointer(dataset)
        _bind_service(dataset, auth_required=True)
        await test_db_session.commit()

        assert await _stamp(dataset.id, read) == 0

    async def test_null_columns_match_their_own_null(self, test_db_session) -> None:
        """A registered table stores no format and a drawn layer no ref; both still match."""
        registered = await _dataset(test_db_session, None)
        set_postgis_origin(registered, registered.table_name, schema="data")
        drawn = await _dataset(test_db_session, "created")
        set_dataset_origin(drawn, "created")
        await test_db_session.commit()
        assert registered.source_format is None
        assert (drawn.origin_uri, drawn.origin_ref) == (None, None)

        assert await _stamp(registered.id, bound_pointer(registered)) == 1
        assert await _stamp(drawn.id, bound_pointer(drawn)) == 1


_SERVICE = {
    "kind": "service",
    "service_type": "wfs",
    "url": "https://maps.example.org/wfs",
    "layer_id": "topp:parcels",
}
_STAC = {
    "kind": "stac",
    "item_href": "https://stac.example.org/collections/dem/items/tile-1",
    "item_id": "tile-1",
    "collection_id": "dem",
    "asset_href": "https://data.example.org/tile-1.tif",
    "asset_key": "data",
    "url": "https://stac.example.org",
}
_POSTGIS = {"kind": "postgis", "table_name": "data.parcels"}


def _without(ref: dict, key: str) -> dict:
    return {k: v for k, v in ref.items() if k != key}


@pytest.mark.parametrize(
    ("kind", "ref", "expected"),
    [
        (
            "service",
            _SERVICE,
            ServiceSource(
                service_type="wfs",
                url="https://maps.example.org/wfs",
                layer_id="topp:parcels",
                auth_required=False,
            ),
        ),
        (
            "service",
            {**_SERVICE, "auth_required": True},
            ServiceSource(
                service_type="wfs",
                url="https://maps.example.org/wfs",
                layer_id="topp:parcels",
                auth_required=True,
            ),
        ),
        (
            "service",
            {**_SERVICE, "service_type": "arcgis_featureserver", "layer_id": 3},
            ServiceSource(
                service_type="arcgis_featureserver",
                url="https://maps.example.org/wfs",
                layer_id="3",
                auth_required=False,
            ),
        ),
        (
            "stac",
            _STAC,
            StacSource(
                item_href="https://stac.example.org/collections/dem/items/tile-1",
                item_id="tile-1",
                collection_id="dem",
                asset_href="https://data.example.org/tile-1.tif",
                asset_key="data",
                catalog_url="https://stac.example.org",
                auth_required=False,
            ),
        ),
        (
            "stac",
            {"kind": "stac", "item_href": "https://stac.example.org/i"},
            StacSource(
                item_href="https://stac.example.org/i",
                item_id=None,
                collection_id=None,
                asset_href=None,
                asset_key=None,
                catalog_url=None,
                auth_required=False,
            ),
        ),
        ("postgis", _POSTGIS, PostgisSource(table_name="data.parcels", managed=False)),
        (
            "postgis",
            {**_POSTGIS, "managed": True},
            PostgisSource(table_name="data.parcels", managed=True),
        ),
    ],
    ids=[
        "service",
        "service-marked",
        "service-int-layer",
        "stac",
        "stac-item-only",
        "postgis",
        "postgis-managed",
    ],
)
def test_a_complete_binding_reads_as_its_kind(kind, ref, expected) -> None:
    assert read_source(kind, ref) == expected


@pytest.mark.parametrize(
    ("kind", "ref", "missing"),
    [
        ("service", None, "service_type"),
        ("service", _without(_SERVICE, "service_type"), "service_type"),
        ("service", {**_SERVICE, "service_type": "wms"}, "service_type"),
        ("service", {**_SERVICE, "service_type": ["wfs"]}, "service_type"),
        ("service", _without(_SERVICE, "url"), "url"),
        ("service", {**_SERVICE, "url": ""}, "url"),
        ("service", {**_SERVICE, "url": 7}, "url"),
        ("service", _without(_SERVICE, "layer_id"), "layer_id"),
        ("service", {**_SERVICE, "layer_id": True}, "layer_id"),
        ("service", {**_SERVICE, "layer_id": ["a"]}, "layer_id"),
        # Refresh reports a missing base before a missing layer.
        ("service", {"service_type": "wfs"}, "url"),
        ("stac", "not-a-ref", "item_href"),
        ("stac", _without(_STAC, "item_href"), "item_href"),
        ("stac", {**_STAC, "item_href": ""}, "item_href"),
        ("stac", {**_STAC, "item_href": {"href": "x"}}, "item_href"),
        ("postgis", {}, "table_name"),
        ("postgis", {"table_name": ""}, "table_name"),
        ("postgis", {"table_name": 12}, "table_name"),
    ],
)
def test_an_incomplete_binding_names_the_first_missing_key(kind, ref, missing) -> None:
    assert read_source(kind, ref) == Unavailable(kind=kind, missing=missing)


@pytest.mark.parametrize("kind", [None, "upload", "created"])
def test_a_kind_with_no_source_to_reread_reads_as_none(kind) -> None:
    ref = {"kind": "upload", "filename": "parcels.gpkg", "url": "https://x.example"}
    assert read_source(kind, ref) is None


def test_an_unknown_kind_is_refused_rather_than_read() -> None:
    with pytest.raises(ValueError, match="unknown origin kind 'database'"):
        read_source("database", {"kind": "database", "table": "parcels"})


@pytest.mark.parametrize("stored", ["yes", 1, "true", None, False])
def test_only_a_stored_true_marks_a_credentialed_pull(stored) -> None:
    service = read_source("service", {**_SERVICE, "auth_required": stored})
    stac = read_source("stac", {**_STAC, "auth_required": stored})
    managed = read_source("postgis", {**_POSTGIS, "managed": stored})
    assert isinstance(service, ServiceSource) and not service.auth_required
    assert isinstance(stac, StacSource) and not stac.auth_required
    assert isinstance(managed, PostgisSource) and not managed.managed


def test_wrong_typed_optional_stac_keys_read_as_absent() -> None:
    source = read_source(
        "stac", {**_STAC, "item_id": 5, "collection_id": [], "url": {"a": 1}}
    )
    assert isinstance(source, StacSource)
    assert (source.item_id, source.collection_id, source.catalog_url) == (
        None,
        None,
        None,
    )


def test_every_service_format_has_a_refresh_label() -> None:
    """The refresh door looks a read service type up by key."""
    assert set(_SERVICE_TYPE_LABELS) == SERVICE_SOURCE_FORMATS
