"""Unit tests for STAC serializer: OGC Record -> STAC 1.1 Item transformation.

Pure unit tests -- no database or fixtures required.
"""

from app.standards.stac.serializer import (
    STAC_CONFORMANCE,
    ogc_collection_to_stac_collection,
    ogc_record_to_stac_item,
)

STAC_API_URL = "http://localhost:8080/api/stac"


def _make_ogc_record(
    *,
    record_id: str = "00000000-0000-0000-0000-000000000001",
    record_type: str = "raster_dataset",
    has_datetime: bool = True,
    has_range: bool = False,
    has_geometry: bool = True,
    has_stac_extensions: bool = True,
    has_bands: bool = False,
) -> dict:
    """Return a dict matching the output of dataset_to_ogc_record()."""
    props: dict = {
        "type": "dataset",
        "title": "Test Dataset",
        "description": "A test raster dataset",
        "keywords": ["test"],
        "created": "2024-01-01T00:00:00",
        "updated": "2024-06-01T00:00:00",
        "crs": "EPSG:4326",
        "record_type": record_type,
        "record_status": "published",
        "license": "CC-BY-4.0",
        "source_organization": "Test Org",
    }

    if has_datetime and not has_range:
        props["datetime"] = "2024-01-15T00:00:00Z"
    elif has_range:
        props["datetime"] = None
        props["start_datetime"] = "2024-01-01T00:00:00Z"
        props["end_datetime"] = "2024-12-31T00:00:00Z"
    else:
        props["datetime"] = None

    if has_stac_extensions:
        props["proj:epsg"] = 4326
        props["proj:shape"] = [1024, 2048]
        props["gsd"] = 30.0

    if has_bands:
        props["bands"] = [
            {"name": "B1", "data_type": "uint8"},
            {"name": "B2", "data_type": "uint8"},
        ]

    record: dict = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": record_id,
        "properties": props,
        "links": [
            {
                "rel": "self",
                "href": "/collections/datasets/items/1",
                "type": "application/geo+json",
            },
        ],
        "assets": {
            "data": {
                "href": "https://storage.example.com/raster.tif",
                "type": "image/tiff; application=geotiff",
                "roles": ["data"],
                "title": "GeoTIFF",
            }
        },
        "stac_assets": {
            "source": {
                "href": "https://storage.example.com/raster.tif",
                "type": "image/tiff",
            }
        },
    }

    if has_geometry:
        record["geometry"] = {
            "type": "Polygon",
            "coordinates": [
                [[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]
            ],
        }
        record["bbox"] = [-180, -90, 180, 90]
    else:
        record["geometry"] = None

    if has_stac_extensions:
        record["stac_extensions"] = [
            "https://stac-extensions.github.io/projection/v2/schema.json",
        ]

    return record


# ---------------------------------------------------------------------------
# ogc_record_to_stac_item
# ---------------------------------------------------------------------------


class TestOgcRecordToStacItem:
    def test_basic_structure(self):
        """Item has type=Feature, stac_version=1.1.0, and id."""
        record = _make_ogc_record()
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert item["type"] == "Feature"
        assert item["stac_version"] == "1.0.0"
        assert item["id"] == record["id"]

    def test_datetime_present_when_single(self):
        """properties.datetime equals the source value when no range."""
        record = _make_ogc_record(has_datetime=True, has_range=False)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert item["properties"]["datetime"] == "2024-01-15T00:00:00Z"

    def test_datetime_null_when_range(self):
        """properties.datetime is null when start/end range present."""
        record = _make_ogc_record(has_range=True)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert item["properties"]["datetime"] is None
        assert item["properties"]["start_datetime"] == "2024-01-01T00:00:00Z"
        assert item["properties"]["end_datetime"] == "2024-12-31T00:00:00Z"

    def test_datetime_always_in_properties(self):
        """datetime key always present in properties even when None."""
        record = _make_ogc_record(has_datetime=False, has_range=False)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert "datetime" in item["properties"]
        assert item["properties"]["datetime"] is None

    def test_bbox_included_with_geometry(self):
        """bbox is in output when geometry is non-null."""
        record = _make_ogc_record(has_geometry=True)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert item["bbox"] == [-180, -90, 180, 90]
        assert item["geometry"] is not None

    def test_bbox_absent_without_geometry(self):
        """bbox is None when geometry is null."""
        record = _make_ogc_record(has_geometry=False)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert item["bbox"] is None
        assert item["geometry"] is None

    def test_stac_extension_properties_copied(self):
        """proj:epsg, proj:shape, gsd are copied to item properties."""
        record = _make_ogc_record(has_stac_extensions=True)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert item["properties"]["proj:epsg"] == 4326
        assert item["properties"]["proj:shape"] == [1024, 2048]
        assert item["properties"]["gsd"] == 30.0

    def test_bands_copied(self):
        """bands array is in output properties when present."""
        record = _make_ogc_record(has_bands=True)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert len(item["properties"]["bands"]) == 2
        assert item["properties"]["bands"][0]["name"] == "B1"

    def test_stac_extensions_included(self):
        """stac_extensions array is present when source record has them."""
        record = _make_ogc_record(has_stac_extensions=True)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert "stac_extensions" in item
        assert len(item["stac_extensions"]) == 1
        assert "projection" in item["stac_extensions"][0]

    def test_stac_extensions_absent_when_none(self):
        """stac_extensions key absent when source has none."""
        record = _make_ogc_record(has_stac_extensions=False)
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert "stac_extensions" not in item

    def test_links_have_correct_rels(self):
        """STAC links include self, root, and parent rels."""
        record = _make_ogc_record()
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        rels = {link["rel"] for link in item["links"]}
        assert "self" in rels
        assert "root" in rels
        assert "parent" in rels

    def test_collection_link_when_provided(self):
        """collection field and collection link present when collection_id given."""
        record = _make_ogc_record()
        item = ogc_record_to_stac_item(
            record, collection_id="my-collection", stac_api_url=STAC_API_URL
        )

        assert item["collection"] == "my-collection"
        rels = {link["rel"] for link in item["links"]}
        assert "collection" in rels

        coll_link = next(lnk for lnk in item["links"] if lnk["rel"] == "collection")
        assert "my-collection" in coll_link["href"]

    def test_no_collection_when_omitted(self):
        """No collection field or collection link when collection_id not given."""
        record = _make_ogc_record()
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert "collection" not in item
        rels = {link["rel"] for link in item["links"]}
        assert "collection" not in rels

    def test_assets_from_unified_dict(self):
        """Assets in output come from record['assets'], not record['stac_assets']."""
        record = _make_ogc_record()
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        assert "data" in item["assets"]
        assert (
            item["assets"]["data"]["href"] == "https://storage.example.com/raster.tif"
        )
        # Should NOT include stac_assets keys
        assert "source" not in item["assets"]

    def test_links_use_stac_api_url(self):
        """All link hrefs are based on stac_api_url, not OGC record links."""
        record = _make_ogc_record()
        item = ogc_record_to_stac_item(record, stac_api_url=STAC_API_URL)

        for link in item["links"]:
            assert link["href"].startswith(STAC_API_URL)


# ---------------------------------------------------------------------------
# ogc_collection_to_stac_collection
# ---------------------------------------------------------------------------


class TestOgcCollectionToStacCollection:
    def test_basic_structure(self):
        """Collection has type=Collection, stac_version, id, title, extent."""
        coll = ogc_collection_to_stac_collection(
            "coll-1", "My Collection", "A description", stac_api_url=STAC_API_URL
        )

        assert coll["type"] == "Collection"
        assert coll["stac_version"] == "1.0.0"
        assert coll["id"] == "coll-1"
        assert coll["title"] == "My Collection"
        assert coll["description"] == "A description"
        assert coll["license"] == "proprietary"
        assert "extent" in coll

    def test_default_extent_when_none(self):
        """Spatial bbox defaults to global when not provided."""
        coll = ogc_collection_to_stac_collection(
            "coll-1", "Test", None, stac_api_url=STAC_API_URL
        )

        bbox = coll["extent"]["spatial"]["bbox"]
        assert bbox == [[-180, -90, 180, 90]]

        interval = coll["extent"]["temporal"]["interval"]
        assert interval == [[None, None]]

    def test_custom_extent(self):
        """Uses provided spatial and temporal extents."""
        coll = ogc_collection_to_stac_collection(
            "coll-1",
            "Test",
            "desc",
            spatial_extent=[-10, -20, 10, 20],
            temporal_extent=["2024-01-01T00:00:00Z", "2024-12-31T00:00:00Z"],
            stac_api_url=STAC_API_URL,
        )

        assert coll["extent"]["spatial"]["bbox"] == [[-10, -20, 10, 20]]
        assert coll["extent"]["temporal"]["interval"] == [
            ["2024-01-01T00:00:00Z", "2024-12-31T00:00:00Z"]
        ]

    def test_description_defaults_to_empty(self):
        """Description falls back to empty string when None."""
        coll = ogc_collection_to_stac_collection(
            "coll-1", "Test", None, stac_api_url=STAC_API_URL
        )
        assert coll["description"] == ""

    def test_links_present(self):
        """Collection has self, root, and items links."""
        coll = ogc_collection_to_stac_collection(
            "coll-1", "Test", None, stac_api_url=STAC_API_URL
        )
        rels = {link["rel"] for link in coll["links"]}
        assert "self" in rels
        assert "root" in rels
        assert "items" in rels


# ---------------------------------------------------------------------------
# STAC_CONFORMANCE
# ---------------------------------------------------------------------------


class TestStacConformance:
    def test_four_conformance_classes(self):
        assert len(STAC_CONFORMANCE) == 4

    def test_core_present(self):
        assert "https://api.stacspec.org/v1.0.0/core" in STAC_CONFORMANCE

    def test_collections_present(self):
        assert "https://api.stacspec.org/v1.0.0/collections" in STAC_CONFORMANCE

    def test_item_search_present(self):
        assert "https://api.stacspec.org/v1.0.0/item-search" in STAC_CONFORMANCE

    def test_ogcapi_features_present(self):
        assert "https://api.stacspec.org/v1.0.0/ogcapi-features" in STAC_CONFORMANCE
