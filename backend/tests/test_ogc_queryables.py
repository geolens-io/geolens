"""Tests for OGC API Features Part 3 queryables and schema introspection.

Verifies:
  - /collections/datasets/queryables returns JSON Schema with filterable properties
  - /collections/datasets/schema returns JSON Schema describing full record structure
  - Conformance endpoint declares Part 3 and CQL2 conformance classes
  - Collection metadata includes a queryables link
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Queryables endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_queryables_endpoint(client: AsyncClient):
    """GET /collections/datasets/queryables returns valid JSON Schema with all filterable properties."""
    resp = await client.get("/collections/datasets/queryables")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/schema+json"

    data = resp.json()
    assert data["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert data["$id"].endswith("/collections/datasets/queryables")
    assert data["type"] == "object"
    assert data["additionalProperties"] is True

    expected_props = [
        "title",
        "description",
        "geometry_type",
        "srid",
        "source_organization",
        "license",
        "created",
        "updated",
        "data_vintage_start",
        "data_vintage_end",
        "geometry",
    ]
    for prop in expected_props:
        assert prop in data["properties"], f"Missing queryable property: {prop}"

    # Geometry property must declare polygon format
    assert data["properties"]["geometry"]["format"] == "geometry-polygon"


# ---------------------------------------------------------------------------
# Record schema endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_schema_endpoint(client: AsyncClient):
    """GET /collections/datasets/schema returns JSON Schema describing OGC Record Feature."""
    resp = await client.get("/collections/datasets/schema")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/schema+json"

    data = resp.json()
    assert "$schema" in data
    assert "$id" in data
    assert data["$id"].endswith("/collections/datasets/schema")

    # The schema should describe a Feature with standard GeoJSON fields.
    # Pydantic generates a top-level schema with $defs for nested models.
    # Check that the top-level properties reference the Feature structure.
    props = data.get("properties", {})
    for field in ("type", "id", "geometry", "properties", "links"):
        assert field in props, f"Missing Feature field in schema: {field}"


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_conformance_includes_part3(client: AsyncClient):
    """GET /conformance includes OGC API Features Part 3 filtering and CQL2 conformance classes.

    Note: queryables conformance class is not declared because queryables
    only apply to the catalog collection, not per-dataset features.
    """
    resp = await client.get("/conformance")
    assert resp.status_code == 200
    data = resp.json()

    part3_classes = [
        "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter",
        "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter",
        "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
        "http://www.opengis.net/spec/cql2/1.0/conf/cql2-json",
        "http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2",
    ]
    for cls in part3_classes:
        assert cls in data["conformsTo"], f"Missing conformance class: {cls}"


# ---------------------------------------------------------------------------
# Collection metadata queryables link
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_metadata_has_queryables_link(client: AsyncClient):
    """GET /collections/datasets includes a queryables link with correct rel and type."""
    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()

    links = data["links"]
    queryable_links = [
        link
        for link in links
        if link.get("rel") == "http://www.opengis.net/def/rel/ogc/1.0/queryables"
    ]
    assert len(queryable_links) == 1, "Expected exactly one queryables link"
    link = queryable_links[0]
    assert link["type"] == "application/schema+json"
    assert link["href"].endswith("/collections/datasets/queryables")
