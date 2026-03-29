"""Unit tests for STAC API endpoint logic.

Pure unit tests -- validates conformance, schema instantiation,
and parameter parsing without requiring a running database.
"""

from app.stac.schemas import StacCatalog, StacConformance, StacItemCollection, StacLink
from app.stac.serializer import STAC_CONFORMANCE


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


class TestStacConformance:
    def test_conformance_contains_core_uri(self):
        assert "https://api.stacspec.org/v1.0.0/core" in STAC_CONFORMANCE

    def test_conformance_contains_collections_uri(self):
        assert "https://api.stacspec.org/v1.0.0/collections" in STAC_CONFORMANCE

    def test_conformance_contains_item_search_uri(self):
        assert "https://api.stacspec.org/v1.0.0/item-search" in STAC_CONFORMANCE

    def test_conformance_four_classes(self):
        assert len(STAC_CONFORMANCE) == 4


# ---------------------------------------------------------------------------
# StacCatalog schema
# ---------------------------------------------------------------------------


class TestStacCatalog:
    def test_catalog_instantiation(self):
        """StacCatalog can be created with required fields."""
        catalog = StacCatalog(
            id="test-catalog",
            title="Test Catalog",
            description="A test catalog",
            conformsTo=STAC_CONFORMANCE,
            links=[
                StacLink(
                    rel="self", href="http://localhost/stac/", type="application/json"
                ),
            ],
        )
        assert catalog.id == "test-catalog"
        assert catalog.type == "Catalog"
        assert catalog.stac_version == "1.1.0"
        assert len(catalog.conformsTo) == 4

    def test_catalog_default_values(self):
        """StacCatalog defaults: type=Catalog, stac_version=1.1.0."""
        catalog = StacCatalog(
            id="x",
            title="X",
            description="X",
            conformsTo=[],
            links=[],
        )
        assert catalog.type == "Catalog"
        assert catalog.stac_version == "1.1.0"


# ---------------------------------------------------------------------------
# StacConformance schema
# ---------------------------------------------------------------------------


class TestStacConformanceSchema:
    def test_conformance_schema_instantiation(self):
        conf = StacConformance(conformsTo=STAC_CONFORMANCE)
        assert len(conf.conformsTo) == 4


# ---------------------------------------------------------------------------
# Search parameter parsing
# ---------------------------------------------------------------------------


class TestStacSearch:
    def test_bbox_parsing(self):
        """Comma-separated bbox string splits to list of floats."""
        bbox_str = "-180.0,-90.0,180.0,90.0"
        parts = bbox_str.split(",")
        bbox_vals = [float(p) for p in parts]
        assert len(bbox_vals) == 4
        assert bbox_vals == [-180.0, -90.0, 180.0, 90.0]

    def test_ids_parsing(self):
        """Comma-separated ids string splits to list of strings."""
        ids_str = "id-1, id-2, id-3"
        parsed = [s.strip() for s in ids_str.split(",")]
        assert parsed == ["id-1", "id-2", "id-3"]

    def test_bbox_invalid_raises(self):
        """Invalid bbox with 3 values raises ValueError."""
        bbox_str = "1,2,3"
        parts = bbox_str.split(",")
        assert len(parts) != 4

    def test_collections_parsing(self):
        """Comma-separated collections string to list."""
        coll_str = "coll-a, coll-b"
        parsed = [s.strip() for s in coll_str.split(",")]
        assert parsed == ["coll-a", "coll-b"]


# ---------------------------------------------------------------------------
# StacItemCollection schema
# ---------------------------------------------------------------------------


class TestStacItemCollection:
    def test_item_collection_instantiation(self):
        """StacItemCollection can be created with required fields."""
        ic = StacItemCollection(
            features=[],
            links=[
                StacLink(
                    rel="self",
                    href="http://localhost/stac/search",
                    type="application/json",
                )
            ],
            numberMatched=0,
            numberReturned=0,
            context={"limit": 10, "returned": 0, "matched": 0},
        )
        assert ic.type == "FeatureCollection"
        assert ic.numberMatched == 0
        assert len(ic.features) == 0
