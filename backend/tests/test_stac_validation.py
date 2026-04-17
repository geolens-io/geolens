"""STAC validation tests using PySTAC roundtrip deserialization.

Pure unit tests -- no database or fixtures required.
Uses the same _make_ogc_record helper pattern as test_stac_serializer.py.
"""

import pystac

from app.standards.stac.serializer import (
    ogc_collection_to_stac_collection,
    ogc_record_to_stac_item,
)

STAC_API_URL = "http://localhost:8080/api/stac"


def _make_ogc_record(
    *,
    record_id: str = "00000000-0000-0000-0000-000000000001",
    has_datetime: bool = True,
    has_range: bool = False,
    has_geometry: bool = True,
    has_stac_extensions: bool = False,
    has_assets: bool = True,
) -> dict:
    """Return a dict matching the output of dataset_to_ogc_record()."""
    props: dict = {
        "type": "dataset",
        "title": "Test Raster",
        "description": "A test raster dataset",
        "keywords": ["test"],
        "created": "2024-01-01T00:00:00",
        "updated": "2024-06-01T00:00:00",
        "crs": "EPSG:4326",
        "record_type": "raster_dataset",
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
        "assets": {},
    }

    if has_assets:
        record["assets"] = {
            "data": {
                "href": "https://storage.example.com/raster.tif",
                "type": "image/tiff; application=geotiff",
                "roles": ["data"],
                "title": "GeoTIFF",
            }
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
        record["bbox"] = None

    if has_stac_extensions:
        record["stac_extensions"] = [
            "https://stac-extensions.github.io/projection/v2/schema.json",
        ]

    return record


# ---------------------------------------------------------------------------
# PySTAC Roundtrip Tests
# ---------------------------------------------------------------------------


class TestPystacRoundtrip:
    def test_item_roundtrip_basic(self):
        """PySTAC can deserialize a basic STAC Item and preserve key fields."""
        ogc = _make_ogc_record(has_datetime=True, has_geometry=True)
        stac_item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        item = pystac.Item.from_dict(stac_item)
        assert item.id == stac_item["id"]
        assert item.geometry is not None
        assert item.datetime is not None

        # Re-serialize and verify structure preserved (transform_hrefs=False avoids link resolution)
        roundtripped = item.to_dict(include_self_link=False, transform_hrefs=False)
        # pystac may normalize stac_version to its own default (e.g. 1.1.0);
        # verify the field exists and roundtrip preserves structure
        assert "stac_version" in roundtripped
        assert "assets" in roundtripped

    def test_item_roundtrip_datetime_range(self):
        """PySTAC handles null datetime with start/end range."""
        ogc = _make_ogc_record(has_range=True)
        stac_item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        item = pystac.Item.from_dict(stac_item)
        assert item.common_metadata.start_datetime is not None
        assert item.common_metadata.end_datetime is not None
        # datetime can be None when range is provided
        assert item.datetime is None

    def test_item_roundtrip_with_extensions(self):
        """stac_extensions array survives PySTAC roundtrip."""
        ogc = _make_ogc_record(has_stac_extensions=True)
        stac_item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        item = pystac.Item.from_dict(stac_item)
        roundtripped = item.to_dict(include_self_link=False, transform_hrefs=False)
        assert "stac_extensions" in roundtripped
        assert len(roundtripped["stac_extensions"]) == 1
        assert "projection" in roundtripped["stac_extensions"][0]

    def test_item_roundtrip_with_assets(self):
        """Assets survive PySTAC roundtrip with correct href and roles."""
        ogc = _make_ogc_record(has_assets=True)
        stac_item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        item = pystac.Item.from_dict(stac_item)
        assert "data" in item.assets
        assert item.assets["data"].href == "https://storage.example.com/raster.tif"
        assert "data" in item.assets["data"].roles

    def test_item_roundtrip_null_geometry(self):
        """STAC allows null geometry -- PySTAC accepts it."""
        ogc = _make_ogc_record(has_geometry=False, has_datetime=True)
        stac_item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        item = pystac.Item.from_dict(stac_item)
        assert item.geometry is None
        assert item.bbox is None
        assert item.id == stac_item["id"]


# ---------------------------------------------------------------------------
# STAC Structure Validation
# ---------------------------------------------------------------------------


class TestStacStructureValidation:
    def test_item_required_fields(self):
        """STAC Item dict has all required top-level keys."""
        ogc = _make_ogc_record()
        item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        required_keys = {
            "type",
            "stac_version",
            "id",
            "geometry",
            "properties",
            "links",
            "assets",
        }
        assert required_keys.issubset(item.keys())
        assert "datetime" in item["properties"]

    def test_collection_required_fields(self):
        """STAC Collection dict has all required keys."""
        coll = ogc_collection_to_stac_collection(
            "coll-1", "Test", "Description", stac_api_url=STAC_API_URL
        )

        required_keys = {"type", "stac_version", "id", "extent", "links", "license"}
        assert required_keys.issubset(coll.keys())

    def test_item_links_required_rels(self):
        """STAC Item links contain self, root, parent rels."""
        ogc = _make_ogc_record()
        item = ogc_record_to_stac_item(ogc, stac_api_url=STAC_API_URL)

        rels = {link["rel"] for link in item["links"]}
        assert "self" in rels
        assert "root" in rels
        assert "parent" in rels
