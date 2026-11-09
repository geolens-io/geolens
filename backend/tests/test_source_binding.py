"""The source binding's seams: the "same stored pointer" check (``bound_pointer``
and ``still_bound``), the typed read of each kind (``read_source``), and the
write (``SourceBinding`` and ``restamp``)."""

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
    KEEP,
    BoundPointer,
    PostgisSource,
    ServiceSource,
    SourceBinding,
    StacSource,
    Unavailable,
    bound_pointer,
    read_source,
    restamp,
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
        ("postgis", _POSTGIS, PostgisSource(table_name="data.parcels")),
    ],
    ids=[
        "service",
        "service-marked",
        "service-int-layer",
        "stac",
        "stac-item-only",
        "postgis",
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
    assert isinstance(service, ServiceSource) and not service.auth_required
    assert isinstance(stac, StacSource) and not stac.auth_required


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


_ITEM = "0123456789abcdef0123456789abcdef"
_ARCGIS = "https://services7.arcgis.com/abc/arcgis/rest/services/Water/FeatureServer"
_PORTAL = "https://myorg.maps.arcgis.com"
_COG = "https://data.example.org/tile-1.tif"
_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)
_BEFORE = datetime(2025, 6, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("binding", "triple"),
    [
        (
            SourceBinding.from_ref("gpkg", {"filename": "roads.gpkg"}),
            ("gpkg", None, {"kind": "upload", "filename": "roads.gpkg"}),
        ),
        (
            SourceBinding.from_ref(
                "wfs",
                {
                    "service_type": "wfs",
                    "url": _WFS,
                    "layer_id": "roads",
                    "auth_required": None,
                },
                uri=f"{_WFS}?typeName=roads",
            ),
            ("wfs", f"{_WFS}?typeName=roads", _REF),
        ),
        (
            SourceBinding.service(
                "wfs",
                url=_WFS,
                layer_id="roads",
                enriched_uri=f"{_WFS}?typeName=roads",
                auth_required=True,
            ),
            ("wfs", f"{_WFS}?typeName=roads", {**_REF, "auth_required": True}),
        ),
        (
            SourceBinding.upload("geotiff", filename="dem.tif", file_hash="ab12"),
            (
                "geotiff",
                None,
                {"kind": "upload", "filename": "dem.tif", "file_hash": "ab12"},
            ),
        ),
        (
            SourceBinding.upload("copc", filename="cloud.laz"),
            ("copc", None, {"kind": "upload", "filename": "cloud.laz"}),
        ),
        (
            SourceBinding.stac(
                asset_href=_COG,
                item_href=_STAC["item_href"],
                item_id="tile-1",
                collection_id="dem",
                asset_key="data",
                url="https://stac.example.org",
                auth_required=False,
            ),
            ("stac", _COG, _STAC),
        ),
        (
            SourceBinding.postgis("parcels", schema="data"),
            (None, "postgis://data.parcels", _POSTGIS),
        ),
        (
            SourceBinding.postgis("parcels", schema="tenant_a", managed=True),
            (
                None,
                "postgis://tenant_a.parcels",
                {"kind": "postgis", "table_name": "tenant_a.parcels", "managed": True},
            ),
        ),
        (SourceBinding.created(), ("created", None, None)),
    ],
    ids=[
        "file-import",
        "service-import",
        "service",
        "raster",
        "pointcloud",
        "stac",
        "postgis",
        "postgis-managed",
        "created",
    ],
)
def test_each_constructor_builds_the_stored_triple(binding, triple) -> None:
    assert (binding.source_format, binding.uri, binding.ref) == triple


def _probed(origin_ref=None) -> SimpleNamespace:
    return SimpleNamespace(
        source_format="gpkg",
        origin_uri="https://old.example/x",
        origin_ref=origin_ref,
        source_health="missing",
        source_health_detail="404",
        last_checked_at=_BEFORE,
        last_refreshed_at=_BEFORE,
    )


class TestRestamp:
    def test_moves_all_three_columns_and_clears_the_probe_state(self) -> None:
        dataset = _probed({"kind": "upload", "filename": "old.gpkg"})
        binding = SourceBinding.from_ref("wfs", _without(_REF, "kind"), uri=_WFS)
        assert restamp(dataset, binding, contacted_at=None, refreshed_at=None) == []
        assert bound_pointer(dataset) == (_WFS, _REF, "wfs")
        assert (dataset.source_health, dataset.source_health_detail) == (None, None)
        assert (dataset.last_checked_at, dataset.last_refreshed_at) == (None, None)

    def test_writes_exactly_the_contact_and_freshness_it_is_given(self) -> None:
        dataset = _probed()
        later = datetime(2026, 3, 4, tzinfo=timezone.utc)
        restamp(
            dataset,
            SourceBinding.created(),
            contacted_at=_AT,
            refreshed_at=later,
        )
        assert (dataset.last_checked_at, dataset.last_refreshed_at) == (_AT, later)

    def test_keep_leaves_freshness_alone(self) -> None:
        dataset = _probed()
        restamp(dataset, SourceBinding.created(), contacted_at=_AT, refreshed_at=KEEP)
        assert dataset.last_refreshed_at == _BEFORE

    def test_health_is_written_after_the_clear(self) -> None:
        dataset = _probed()
        restamp(
            dataset,
            SourceBinding.from_ref("wfs", _without(_REF, "kind"), uri=_WFS),
            contacted_at=_AT,
            refreshed_at=KEEP,
            health=("healthy", None),
        )
        assert (dataset.source_health, dataset.source_health_detail) == (
            "healthy",
            None,
        )
        restamp(
            dataset,
            SourceBinding.stac(
                asset_href=_COG,
                item_href=None,
                item_id=None,
                collection_id=None,
                asset_key=None,
                url=None,
                auth_required=False,
            ),
            contacted_at=None,
            refreshed_at=KEEP,
            health=("missing", "HTTP 404"),
        )
        assert (dataset.source_health, dataset.source_health_detail) == (
            "missing",
            "HTTP 404",
        )


class TestAllowlist:
    @pytest.mark.parametrize("source_format", ["gpkg", "wfs", "stac", None])
    def test_an_undeclared_key_is_refused_for_every_kind(self, source_format) -> None:
        with pytest.raises(ValueError, match="token"):
            SourceBinding.from_ref(source_format, {"token": "s3cret"})

    def test_created_carries_no_payload(self) -> None:
        with pytest.raises(ValueError):
            SourceBinding.from_ref("created", {"filename": "a"})

    @pytest.mark.parametrize("key", ["host", "port", "dsn", "password", "url"])
    def test_postgis_accepts_only_its_table(self, key) -> None:
        with pytest.raises(ValueError):
            SourceBinding.from_ref(None, {"table_name": "data.t", key: "x"})

    @pytest.mark.parametrize(
        "ref",
        [
            {"kind": "upload", "filename": "a", "token": "s3cret"},
            {"kind": "upload", "filename": "a"},
            {"filename": "a"},
            {"kind": "service", "filename": "a"},
            {
                "kind": "service",
                "service_type": "wfs",
                "url": "u",
                "auth_required": None,
            },
        ],
        ids=["undeclared", "other-kind", "no-kind", "foreign-key", "none-value"],
    )
    def test_a_payload_the_allowlist_would_not_build_cannot_be_held(self, ref) -> None:
        with pytest.raises(ValueError):
            SourceBinding("wfs", _WFS, ref)

    @pytest.mark.parametrize(
        "make",
        [
            lambda: SourceBinding.upload("wfs", filename="a"),
            lambda: SourceBinding.upload("stac", filename="a"),
            lambda: SourceBinding.service(
                "geojson", url=_WFS, layer_id="0", enriched_uri=None
            ),
        ],
        ids=["upload-as-service", "upload-as-stac", "service-as-upload"],
    )
    def test_a_constructor_refuses_another_kinds_format(self, make) -> None:
        with pytest.raises(ValueError):
            make()


_LINKED_SERVICE = {
    "kind": "service",
    "service_type": "arcgis_featureserver",
    "url": _ARCGIS,
    "item_id": _ITEM,
    "portal_url": _PORTAL,
}


def _linked(origin_ref: dict) -> SimpleNamespace:
    return _probed(dict(origin_ref))


def _arcgis(url: str, **link) -> SourceBinding:
    return SourceBinding.service(
        "arcgis_featureserver", url=url, layer_id="0", enriched_uri=url, **link
    )


def _stamp_link(dataset, binding) -> list[str]:
    return restamp(dataset, binding, contacted_at=None, refreshed_at=KEEP)


class TestPortalLinkCarry:
    def test_a_service_refresh_keeps_it(self) -> None:
        dataset = _linked(_LINKED_SERVICE)
        assert _stamp_link(dataset, _arcgis(_ARCGIS)) == []
        assert dataset.origin_ref["item_id"] == _ITEM
        assert dataset.origin_ref["portal_url"] == _PORTAL

    def test_a_file_replace_of_a_service_dataset_keeps_it(self) -> None:
        dataset = _linked(_LINKED_SERVICE)
        _stamp_link(dataset, SourceBinding.upload("gpkg", filename="a.gpkg"))
        assert dataset.origin_ref["kind"] == "upload"
        assert dataset.origin_ref["item_id"] == _ITEM

    def test_a_restore_of_a_file_dataset_keeps_it(self) -> None:
        dataset = _linked({"kind": "upload", "filename": "b.gpkg", "item_id": _ITEM})
        _stamp_link(dataset, SourceBinding.upload("gpkg", filename="a.gpkg"))
        assert dataset.origin_ref["item_id"] == _ITEM

    def test_a_new_link_replaces_the_old_one(self) -> None:
        dataset = _linked(_LINKED_SERVICE)
        other = "f" * 32
        _stamp_link(
            dataset, SourceBinding.from_ref("gpkg", {"filename": "a", "item_id": other})
        )
        assert dataset.origin_ref["item_id"] == other
        assert "portal_url" not in dataset.origin_ref

    def test_a_service_moved_to_another_domain_drops_the_link_and_says_so(
        self,
    ) -> None:
        dataset = _linked(_LINKED_SERVICE)
        losses = _stamp_link(
            dataset, _arcgis("https://gis.other.org/rest/FeatureServer")
        )
        assert losses == ["portal_url_domain_mismatch"]
        assert "item_id" not in dataset.origin_ref
        assert "portal_url" not in dataset.origin_ref

    def test_an_item_id_alone_is_dropped_when_the_service_moves_domain(self) -> None:
        dataset = _linked(_without(_LINKED_SERVICE, "portal_url"))
        losses = _stamp_link(
            dataset, _arcgis("https://gis.other.org/rest/FeatureServer")
        )
        assert losses == ["portal_url_domain_mismatch"]
        assert "item_id" not in dataset.origin_ref

    def test_an_item_id_alone_survives_a_move_within_the_domain(self) -> None:
        dataset = _linked(_without(_LINKED_SERVICE, "portal_url"))
        url = "https://services8.arcgis.com/z/FeatureServer"
        assert _stamp_link(dataset, _arcgis(url)) == []
        assert dataset.origin_ref["item_id"] == _ITEM

    def test_a_rebind_to_a_non_arcgis_service_drops_the_link(self) -> None:
        dataset = _linked(_LINKED_SERVICE)
        losses = _stamp_link(
            dataset,
            SourceBinding.service(
                "wfs",
                url="https://services7.arcgis.com/wfs",
                layer_id="roads",
                enriched_uri=None,
            ),
        )
        assert losses == ["origin_link_unsupported"]
        assert "item_id" not in dataset.origin_ref
        assert "portal_url" not in dataset.origin_ref

    def test_an_upload_turned_into_a_service_is_checked_against_the_new_host(
        self,
    ) -> None:
        dataset = _linked(
            {
                "kind": "upload",
                "filename": "a",
                "item_id": _ITEM,
                "portal_url": "https://evil.example",
            }
        )
        url = "https://gis.city.gov/server/rest/services/S/FeatureServer"
        assert _stamp_link(dataset, _arcgis(url)) == ["portal_url_domain_mismatch"]
        assert dataset.origin_ref.get("portal_url") is None
        assert dataset.origin_ref.get("item_id") is None

    def test_a_service_turned_into_an_upload_keeps_the_link(self) -> None:
        dataset = _linked(_LINKED_SERVICE)
        assert _stamp_link(dataset, SourceBinding.upload("gpkg", filename="a")) == []
        assert dataset.origin_ref["portal_url"] == _PORTAL

    def test_a_stac_item_id_is_not_a_portal_item(self) -> None:
        dataset = _linked(
            {"kind": "stac", "item_id": "S2A_2024", "url": "https://c.test"}
        )
        _stamp_link(dataset, SourceBinding.upload("geotiff", filename="a.tif"))
        assert "item_id" not in dataset.origin_ref

    @pytest.mark.parametrize(
        "binding",
        [SourceBinding.postgis("t", schema="data"), SourceBinding.created()],
        ids=["postgis", "created"],
    )
    def test_other_kinds_never_gain_it(self, binding) -> None:
        dataset = _linked(_LINKED_SERVICE)
        assert _stamp_link(dataset, binding) == []
        assert dataset.origin_ref == binding.ref

    def test_the_binding_value_itself_is_never_changed(self) -> None:
        binding = SourceBinding.upload("gpkg", filename="a")
        _stamp_link(_linked(_LINKED_SERVICE), binding)
        assert binding.ref == {"kind": "upload", "filename": "a"}
