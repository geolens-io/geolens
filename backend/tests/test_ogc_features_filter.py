"""Server-side CQL2 filtering on per-dataset feature collections (feat(#1614)).

Covers the OGC Features Part 3 surface that #430 BA-14 deliberately kept
unadvertised until it worked:

  - GET /collections/{dataset_id}/queryables derived from the LIVE table
    schema (stored column_info drift must not leak in)
  - filter= / filter-lang= / filter-crs= on /collections/{dataset_id}/items,
    every advertised operator tested in BOTH encodings (this is what gates
    advertising advanced-comparison-operators and basic-spatial-functions),
    including the encoding shims for final-spec cql2-json BETWEEN and BBox
    literals that pygeofilter 0.4.0 mis-parses
  - error contract: unknown property, type mismatch, unsupported constructs,
    oversized filters and injection attempts are 400s; the missing-table 503
    is preserved; nothing surfaces as a 500
  - composition with bbox + property filters, filtered counts, and filter
    propagation through pagination links
"""

import json
import uuid
from datetime import datetime
from urllib.parse import urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import create_raster_dataset, get_user_id

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_typed_table_and_dataset(
    session,
    *,
    created_by: uuid.UUID,
    geometry_attribute: bool = False,
) -> Dataset:
    """Create a data table with one column per queryable type family.

    ``WeirdCol`` (fails the lowercase identifier rule) and ``meta`` (jsonb, an
    unmappable type) must never appear in queryables. The stored column_info
    is deliberately DRIFTED — it lists a ghost column and omits ``height`` —
    so any test passing against it instead of the live schema fails.

    With ``geometry_attribute=True`` the table also carries a text column
    literally named ``geometry`` to pin the spatial-queryable precedence.
    """
    table_name = f"test_cql2_{uuid.uuid4().hex[:8]}"
    geometry_col_sql = '"geometry" TEXT, ' if geometry_attribute else ""
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"geom geometry(Point, 4326), "
            f"geom_4326 geometry(Geometry, 4326), "
            f"name TEXT, "
            f"height DOUBLE PRECISION, "
            f"cat INTEGER, "
            f"built TIMESTAMP, "
            f"active BOOLEAN, "
            f"ratio REAL, "
            f"price NUMERIC(12, 2), "
            f"x INTEGER, "
            f"{geometry_col_sql}"
            f'"WeirdCol" TEXT, '
            f"meta JSONB)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))

    rows = [
        # (name, height, cat, built, active, ratio, price, x, lng, lat)
        ("Alpha", 1.5, 1, "2020-01-01T00:00:00", True, 0.1, 19.99, 1, -74.00, 40.70),
        ("Beta", 2.5, 2, "2021-06-15T12:00:00", False, 0.2, 20.00, 2, -73.99, 40.71),
        ("Gamma", 3.5, 2, "2022-01-01T00:00:00", True, 0.3, 100.50, 3, -73.98, 40.72),
        ("Delta", 10.0, 3, "2023-01-01T00:00:00", False, 0.4, 0.05, 4, -73.97, 40.73),
        (None, 20.0, 3, "2024-01-01T00:00:00", True, 0.5, 6.01, 5, -73.96, 40.74),
    ]
    for name, height, cat, built, active, ratio, price, x, lng, lat in rows:
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} "
                f"(geom, geom_4326, name, height, cat, built, active, "
                f'ratio, price, "x") VALUES ('
                f"ST_SetSRID(ST_MakePoint({lng}, {lat}), 4326), "
                f"ST_SetSRID(ST_MakePoint({lng}, {lat}), 4326), "
                f":name, :height, :cat, :built, :active, "
                f":ratio, :price, :x)"
            ).bindparams(
                name=name,
                height=height,
                cat=cat,
                built=datetime.fromisoformat(built),
                active=active,
                ratio=ratio,
                price=price,
                x=x,
            )
        )

    record = Record(
        title=f"CQL2 Filter Test Layer {table_name}",
        summary="Test dataset for Part 3 server-side filtering",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=len(rows),
        # Deliberately drifted from the live table: queryables and filter
        # validation must come from information_schema, never from here.
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "cat", "type": "integer"},
            {"name": "ghost", "type": "text"},
        ],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _cleanup_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


def _items_url(dataset: Dataset) -> str:
    return f"/collections/{dataset.id}/items"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def filter_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_typed_table_and_dataset(
        test_db_session, created_by=admin_id
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


@pytest.fixture
async def geometry_named_column_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_typed_table_and_dataset(
        test_db_session, created_by=admin_id, geometry_attribute=True
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


@pytest.fixture
async def raster_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"CQL2 Raster {uuid.uuid4().hex[:8]}",
        description="Raster dataset: no feature table, no queryables",
        theme_category=["test"],
        visibility="public",
        record_type="raster_dataset",
        table_name=f"test_cql2_raster_{uuid.uuid4().hex[:8]}",
    )
    yield dataset


@pytest.fixture
async def missing_table_dataset(client: AsyncClient, test_db_session):
    """Vector dataset whose backing table does not exist (503 contract)."""
    admin_id = await get_user_id(test_db_session, "admin")
    record = Record(
        title=f"CQL2 Missing Table {uuid.uuid4().hex[:8]}",
        summary="Vector dataset with no backing table",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type="vector_dataset",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"test_cql2_missing_{uuid.uuid4().hex[:8]}",
        srid=4326,
        geometry_type="POINT",
        feature_count=0,
        column_info=[],
        source_format="created",
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)
    yield dataset


# ---------------------------------------------------------------------------
# Queryables document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_queryables_document_shape(client: AsyncClient, filter_dataset: Dataset):
    resp = await client.get(f"/collections/{filter_dataset.id}/queryables")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/schema+json")
    doc = resp.json()

    assert doc["type"] == "object"
    assert doc["additionalProperties"] is False
    assert doc["$id"].endswith(f"/collections/{filter_dataset.id}/queryables")

    props = doc["properties"]
    assert props["name"] == {"type": "string"}
    assert props["height"] == {"type": "number"}
    assert props["cat"] == {"type": "integer"}
    assert props["built"] == {"type": "string", "format": "date-time"}
    assert props["active"] == {"type": "boolean"}
    assert props["ratio"] == {"type": "number"}
    assert props["price"] == {"type": "number"}
    assert props["x"] == {"type": "integer"}
    assert props["geometry"]["format"] == "geometry-any"

    # Live-schema derivation: the drifted stored column_info lists "ghost"
    # and omits "height"; the document must reflect the table, not the store.
    assert "ghost" not in props
    # Name and type exclusion rules.
    assert "WeirdCol" not in props
    assert "meta" not in props
    # Internal columns never leak.
    for hidden in ("gid", "geom", "geom_4326"):
        assert hidden not in props


@pytest.mark.anyio
async def test_queryables_geometry_wins_over_attribute_named_geometry(
    client: AsyncClient, geometry_named_column_dataset: Dataset
):
    resp = await client.get(
        f"/collections/{geometry_named_column_dataset.id}/queryables"
    )
    assert resp.status_code == 200
    geometry = resp.json()["properties"]["geometry"]
    assert geometry.get("format") == "geometry-any"
    assert geometry.get("type") != "string"

    # And the attribute column is not filterable under that name either.
    resp = await client.get(
        _items_url(geometry_named_column_dataset),
        params={"filter": "geometry LIKE 'x%'"},
    )
    assert resp.status_code == 400
    assert "LIKE only applies to string properties" in resp.json()["detail"]


@pytest.mark.anyio
async def test_queryables_raster_collection_404(
    client: AsyncClient, raster_dataset: Dataset
):
    resp = await client.get(f"/collections/{raster_dataset.id}/queryables")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_records_queryables_still_served(client: AsyncClient):
    """Route-ordering regression: /collections/datasets/queryables must keep
    serving the RECORDS document, not fall through to the per-dataset route."""
    resp = await client.get("/collections/datasets/queryables")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/schema+json")
    doc = resp.json()
    assert "title" in doc["properties"]
    assert doc["$id"].endswith("/collections/datasets/queryables")


@pytest.mark.anyio
async def test_collection_metadata_queryables_link(
    client: AsyncClient, filter_dataset: Dataset, raster_dataset: Dataset
):
    resp = await client.get(f"/collections/{filter_dataset.id}")
    assert resp.status_code == 200
    links = [
        link
        for link in resp.json()["links"]
        if link["rel"] == "http://www.opengis.net/def/rel/ogc/1.0/queryables"
    ]
    assert len(links) == 1
    assert links[0]["href"].endswith(f"/collections/{filter_dataset.id}/queryables")
    assert links[0]["type"] == "application/schema+json"

    resp = await client.get(f"/collections/{raster_dataset.id}")
    assert resp.status_code == 200
    assert not any(
        link["rel"] == "http://www.opengis.net/def/rel/ogc/1.0/queryables"
        for link in resp.json()["links"]
    )


# ---------------------------------------------------------------------------
# Operator matrix — every advertised operator, both encodings
# ---------------------------------------------------------------------------

BBOX_12 = [-74.005, 40.695, -73.985, 40.715]  # covers Alpha and Beta
POLYGON_12 = {
    "type": "Polygon",
    "coordinates": [
        [
            [-74.005, 40.695],
            [-73.985, 40.695],
            [-73.985, 40.715],
            [-74.005, 40.715],
            [-74.005, 40.695],
        ]
    ],
}


def _j(op: str, *args) -> str:
    return json.dumps({"op": op, "args": list(args)})


P = {"property": "height"}

OPERATOR_CASES = [
    # (label, cql2-text, cql2-json, expected feature count)
    ("eq", "name = 'Alpha'", _j("=", {"property": "name"}, "Alpha"), 1),
    ("neq", "name <> 'Alpha'", _j("<>", {"property": "name"}, "Alpha"), 3),
    ("gt", "height > 3", _j(">", P, 3), 3),
    ("gte", "height >= 3.5", _j(">=", P, 3.5), 3),
    ("lt", "height < 2", _j("<", P, 2), 1),
    ("lte", "height <= 2.5", _j("<=", P, 2.5), 2),
    ("bool_eq", "active = TRUE", _j("=", {"property": "active"}, True), 3),
    # fix(#1614 codex r3): a float8-cast bind against a REAL column promotes
    # the stored float4 and 0.1 never matches; the typed REAL bind does.
    ("real_eq", "ratio = 0.1", _j("=", {"property": "ratio"}, 0.1), 1),
    ("numeric_eq", "price = 19.99", _j("=", {"property": "price"}, 19.99), 1),
    # fix(#1614 codex r3): the text grammar's unquoted identifier needs two
    # characters; the shim quotes lone letters so bare `x = 3` parses.
    ("single_char_prop", "x = 3", _j("=", {"property": "x"}, 3), 1),
    ("like", "name LIKE 'A%'", _j("like", {"property": "name"}, "A%"), 1),
    ("like_suffix", "name LIKE '%a'", _j("like", {"property": "name"}, "%a"), 4),
    # cql2-json BETWEEN uses the FINAL flat 3-element args (the shim rewrites
    # it to the draft shape pygeofilter parses).
    ("between", "height BETWEEN 2 AND 4", _j("between", P, 2, 4), 2),
    ("in", "cat IN (1, 3)", _j("in", {"property": "cat"}, [1, 3]), 3),
    ("is_null", "name IS NULL", _j("isNull", {"property": "name"}), 1),
    ("not", "NOT height > 3", _j("not", json.loads(_j(">", P, 3))), 2),
    (
        "and",
        "height > 3 AND cat = 3",
        _j(
            "and",
            json.loads(_j(">", P, 3)),
            json.loads(_j("=", {"property": "cat"}, 3)),
        ),
        2,
    ),
    (
        "or",
        "name = 'Alpha' OR name = 'Beta'",
        _j(
            "or",
            json.loads(_j("=", {"property": "name"}, "Alpha")),
            json.loads(_j("=", {"property": "name"}, "Beta")),
        ),
        2,
    ),
    (
        "timestamp_gte",
        "built >= TIMESTAMP('2022-01-01T00:00:00Z')",
        _j(">=", {"property": "built"}, {"timestamp": "2022-01-01T00:00:00Z"}),
        3,
    ),
    # basic-spatial-functions: S_INTERSECTS with BBox literal — the text form
    # needs the Function("bbox") rewrite, the json form the Envelope bypass.
    (
        "s_intersects_bbox",
        f"S_INTERSECTS(geometry, BBOX({BBOX_12[0]}, {BBOX_12[1]}, {BBOX_12[2]}, {BBOX_12[3]}))",
        _j("s_intersects", {"property": "geometry"}, {"bbox": BBOX_12}),
        2,
    ),
    # ... and with Point / Polygon literals.
    (
        "s_intersects_geom",
        "S_INTERSECTS(geometry, POINT(-74.0 40.7))",
        _j("s_intersects", {"property": "geometry"}, POLYGON_12),
        None,  # text: 1 (point hit); json: 2 (polygon) — checked below
    ),
]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "label,text_expr,json_expr,expected",
    OPERATOR_CASES,
    ids=[c[0] for c in OPERATOR_CASES],
)
async def test_operator_matrix_both_encodings(
    client: AsyncClient,
    filter_dataset: Dataset,
    label: str,
    text_expr: str,
    json_expr: str,
    expected: int | None,
):
    resp_text = await client.get(
        _items_url(filter_dataset), params={"filter": text_expr}
    )
    assert resp_text.status_code == 200, (label, "text", resp_text.text)
    resp_json = await client.get(
        _items_url(filter_dataset),
        params={"filter": json_expr, "filter-lang": "cql2-json"},
    )
    assert resp_json.status_code == 200, (label, "json", resp_json.text)

    if expected is not None:
        assert resp_text.json()["numberReturned"] == expected, (label, "text")
        assert resp_json.json()["numberReturned"] == expected, (label, "json")
    else:  # s_intersects_geom: different literals per encoding
        assert resp_text.json()["numberReturned"] == 1
        assert resp_json.json()["numberReturned"] == 2


@pytest.mark.anyio
async def test_single_char_property_quoted_form_still_parses(
    client: AsyncClient, filter_dataset: Dataset
):
    resp = await client.get(_items_url(filter_dataset), params={"filter": '"x" = 3'})
    assert resp.status_code == 200, resp.text
    assert resp.json()["numberReturned"] == 1


@pytest.mark.anyio
async def test_filtered_count_and_rows_are_consistent(
    client: AsyncClient, filter_dataset: Dataset
):
    """numberMatched reflects the filter (cached feature_count is bypassed)."""
    resp = await client.get(
        _items_url(filter_dataset), params={"filter": "height > 3", "limit": 1}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] == 3
    assert data["numberReturned"] == 1
    assert all(f["properties"]["height"] > 3 for f in data["features"])


@pytest.mark.anyio
async def test_filter_composes_with_bbox_and_property_filters(
    client: AsyncClient, filter_dataset: Dataset
):
    """filter ANDs with bbox and the property-filter extension."""
    bbox = ",".join(str(v) for v in BBOX_12)  # Alpha + Beta
    resp = await client.get(
        _items_url(filter_dataset),
        params={"bbox": bbox, "filter": "height > 2", "name": "Beta"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] == 1
    assert data["features"][0]["properties"]["name"] == "Beta"


@pytest.mark.anyio
async def test_filter_propagates_through_pagination_links(
    client: AsyncClient, filter_dataset: Dataset
):
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": "cat IN (2, 3)", "limit": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] == 4
    assert data["numberReturned"] == 2
    next_links = [link for link in data["links"] if link["rel"] == "next"]
    assert len(next_links) == 1
    assert "filter=" in next_links[0]["href"]

    # Follow the keyset next link: still filtered, no overlap with page 1.
    next_path = next_links[0]["href"].split("/api", 1)[-1]
    resp2 = await client.get(next_path)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["numberReturned"] == 2
    page1_ids = {f["id"] for f in data["features"]}
    page2_ids = {f["id"] for f in data2["features"]}
    assert not page1_ids & page2_ids
    for feature in data2["features"]:
        assert feature["properties"]["cat"] in (2, 3)


@pytest.mark.anyio
async def test_filter_crs_crs84_accepted(client: AsyncClient, filter_dataset: Dataset):
    resp = await client.get(
        _items_url(filter_dataset),
        params={
            "filter": "S_INTERSECTS(geometry, POINT(-74.0 40.7))",
            "filter-crs": CRS84,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["numberReturned"] == 1


# ---------------------------------------------------------------------------
# Error contract — everything invalid is a 400, never a 500
# ---------------------------------------------------------------------------

ERROR_CASES = [
    ("unknown_property", {"filter": "bogus = 1"}, "bogus"),
    ("type_mismatch", {"filter": "name > 5"}, "'text'"),
    ("like_on_integer", {"filter": "cat LIKE 'x%'"}, "LIKE"),
    ("geometry_scalar_compare", {"filter": "geometry = 'x'"}, "spatial predicate"),
    (
        "spatial_on_attribute",
        {"filter": "S_INTERSECTS(name, POINT(0 0))"},
        "geometry",
    ),
    (
        "temporal_predicate_json",
        {
            "filter": _j(
                "t_after",
                {"property": "built"},
                {"timestamp": "2020-01-01T00:00:00Z"},
            ),
            "filter-lang": "cql2-json",
        },
        "temporal",
    ),
    (
        "bad_filter_lang",
        {"filter": "name = 'x'", "filter-lang": "cql-text"},
        "filter-lang",
    ),
    (
        "bad_filter_crs",
        {
            "filter": "name = 'x'",
            "filter-crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
        },
        "filter-crs",
    ),
    (
        "quoted_hostile_identifier",
        {"filter": "\"name; DROP TABLE data.x\" = 'x'"},
        "non-filterable",
    ),
    (
        "excluded_column_not_filterable",
        {"filter": "\"WeirdCol\" = 'x'"},
        "non-filterable",
    ),
    (
        "embedded_filter_lang_json",
        {
            "filter": json.dumps(
                {
                    "filter-lang": "cql-text",
                    "op": "=",
                    "args": [{"property": "name"}, "x"],
                }
            ),
            "filter-lang": "cql2-json",
        },
        "Invalid CQL2",
    ),
    ("unparseable", {"filter": "junk ((("}, "Invalid CQL2"),
]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "label,params,detail_fragment",
    ERROR_CASES,
    ids=[c[0] for c in ERROR_CASES],
)
async def test_invalid_filters_return_400(
    client: AsyncClient,
    filter_dataset: Dataset,
    label: str,
    params: dict,
    detail_fragment: str,
):
    resp = await client.get(_items_url(filter_dataset), params=params)
    assert resp.status_code == 400, (label, resp.text)
    assert detail_fragment in resp.json()["detail"], (label, resp.text)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "filter_json",
    [
        pytest.param(
            '{"op":"<","args":[{"property":"height"},Infinity]}', id="infinity"
        ),
        pytest.param('{"op":"=","args":[{"property":"height"},NaN]}', id="nan"),
        pytest.param(
            '{"op":"=","args":[{"property":"cat"},' + "9" * 401 + "]}",
            id="huge-int-int8",
        ),
        pytest.param(
            '{"op":"s_intersects","args":[{"property":"geometry"},'
            '{"bbox":[' + "9" * 401 + ",0,1,1]}]}",
            id="huge-int-bbox",
        ),
        pytest.param(
            '{"op":"s_intersects","args":[{"property":"geometry"},'
            '{"type":"Point","coordinates":[NaN,0]}]}',
            id="nan-geometry-coordinate",
        ),
    ],
)
async def test_non_finite_and_oversized_literals_rejected(
    client: AsyncClient, filter_dataset: Dataset, filter_json: str
):
    """fix(#1614 codex r5): Python's JSON decoder accepts NaN/Infinity, and
    math.isfinite raises OverflowError on a 401-digit integer — all of these
    must be the caller's 400, never a match-everything filter or a 500."""
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": filter_json, "filter-lang": "cql2-json"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.anyio
async def test_oversized_filter_rejected(client: AsyncClient, filter_dataset: Dataset):
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": "name = '" + "x" * 10_001 + "'"},
    )
    assert resp.status_code == 400
    assert "character limit" in resp.json()["detail"]


@pytest.mark.anyio
async def test_hostile_literal_is_just_a_value(
    client: AsyncClient, filter_dataset: Dataset
):
    """A hostile string travels as a bind parameter: 200 with zero matches."""
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": "name = 'x; DROP TABLE data.nope; --'"},
    )
    assert resp.status_code == 200
    assert resp.json()["numberReturned"] == 0
    # The table is intact.
    resp = await client.get(_items_url(filter_dataset))
    assert resp.status_code == 200
    assert resp.json()["numberMatched"] == 5


@pytest.mark.anyio
async def test_incomparable_property_pair_is_400_not_500(
    client: AsyncClient, filter_dataset: Dataset
):
    """A property-property comparison PostgreSQL cannot type passes AST
    validation and fails at execute time — mapped to 400, not 503/500."""
    resp = await client.get(
        _items_url(filter_dataset), params={"filter": "name = height"}
    )
    assert resp.status_code == 400
    assert "not evaluable" in resp.json()["detail"]


@pytest.mark.anyio
async def test_schema_introspection_outage_is_503(
    client: AsyncClient, filter_dataset: Dataset, monkeypatch
):
    """fix(#1614 codex r6): a transient database failure during the
    existence/live-schema lookups classifies like the feature query's 503,
    not a 500."""
    from sqlalchemy.exc import OperationalError

    import app.standards.ogc.router as ogc_router

    async def _boom(db, table_name):
        raise OperationalError("SELECT 1", {}, Exception("connection dropped"))

    monkeypatch.setattr(ogc_router, "feature_table_exists", _boom)
    resp = await client.get(
        _items_url(filter_dataset), params={"filter": "name = 'Alpha'"}
    )
    assert resp.status_code == 503

    resp = await client.get(f"/collections/{filter_dataset.id}/queryables")
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_missing_table_with_filter_keeps_503(
    client: AsyncClient, missing_table_dataset: Dataset
):
    """A missing table stays the retryable 503, whatever the filter shape.

    fix(#1614 codex r2): an attribute filter must not be misreported as an
    unknown-property 400 just because the missing table has an empty live
    schema, and /queryables must not publish that empty schema as a 200.
    """
    for params in (
        {"filter": "S_INTERSECTS(geometry, POINT(0 0))"},
        {"filter": "name = 'x'"},
    ):
        resp = await client.get(_items_url(missing_table_dataset), params=params)
        assert resp.status_code == 503, (params, resp.text)

    resp = await client.get(f"/collections/{missing_table_dataset.id}/queryables")
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_geojson_geometry_with_bbox_member_keeps_its_shape(
    client: AsyncClient, filter_dataset: Dataset
):
    """fix(#1614 codex r2): GeoJSON's optional bbox member is metadata.

    A triangle near (0,0) carrying a bbox that covers every feature must
    match nothing — rewriting the geometry to its bounding rectangle would
    match all five.
    """
    triangle = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
        "bbox": [-75, 40, -73, 41],
    }
    resp = await client.get(
        _items_url(filter_dataset),
        params={
            "filter": _j("s_intersects", {"property": "geometry"}, triangle),
            "filter-lang": "cql2-json",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["numberMatched"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param(
            {"filter": "S_INTERSECTS(geometry, BBOX(170, 40.6, -170, 40.8))"},
            id="text-literal",
        ),
        pytest.param(
            {
                "filter": _j(
                    "s_intersects",
                    {"property": "geometry"},
                    {"bbox": [170, 40.6, -170, 40.8]},
                ),
                "filter-lang": "cql2-json",
            },
            id="json-literal",
        ),
        pytest.param(
            {"filter": "BBOX(geometry, 170, 40.6, -170, 40.8)"},
            id="legacy-predicate",
        ),
    ],
)
async def test_antimeridian_bbox_is_a_dateline_strip_not_the_globe(
    client: AsyncClient, filter_dataset: Dataset, params: dict
):
    """fix(#1614 codex r1): minx > maxx is a dateline-crossing box.

    A planar rectangle rendering would invert it into x in [-170, 170] and
    match every NYC-longitude feature; the split MultiPolygon matches none.
    """
    resp = await client.get(_items_url(filter_dataset), params=params)
    assert resp.status_code == 200, resp.text
    assert resp.json()["numberMatched"] == 0


def test_antimeridian_bbox_compiles_to_a_split_multipolygon():
    """The crossing box renders as two hemispheres, not a rejection."""
    from app.standards.ogc.filtering import compile_feature_cql2

    sql, binds = compile_feature_cql2(
        "S_INTERSECTS(geometry, BBOX(170, -45, -170, -30))",
        "cql2-text",
        {"geometry": "geometry"},
    )
    assert "ST_Intersects" in sql
    (bind,) = binds
    assert "MULTIPOLYGON" in bind.value
    assert "170 -45" in bind.value and "-180 -45" in bind.value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bbox_args,expected_matched",
    [
        pytest.param("-74.0, 40.7, -74.0, 40.7", 1, id="point-envelope"),
        pytest.param("-74.005, 40.7, -73.985, 40.7", 1, id="line-envelope"),
    ],
)
async def test_degenerate_bbox_envelopes_evaluate(
    client: AsyncClient, filter_dataset: Dataset, bbox_args: str, expected_matched: int
):
    """fix(#1614 codex r4): equal bounds are a legal point/line envelope."""
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": f"S_INTERSECTS(geometry, BBOX({bbox_args}))"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["numberMatched"] == expected_matched


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params,fragment",
    [
        pytest.param(
            {"filter": "S_INTERSECTS(geometry, BBOX(0, 10, 1, -10))"},
            "miny",
            id="inverted-latitude",
        ),
        pytest.param(
            {"filter": "S_INTERSECTS(geometry, BBOX(170, 40, -170, 40))"},
            "degenerate antimeridian",
            id="degenerate-crossing",
        ),
        pytest.param(
            {
                "filter": '{"op":"s_intersects","args":[{"property":"geometry"},'
                '{"bbox":[NaN,0,1,1]}]}',
                "filter-lang": "cql2-json",
            },
            "finite",
            id="nan-json",
        ),
    ],
)
async def test_invalid_bbox_bounds_rejected(
    client: AsyncClient, filter_dataset: Dataset, params: dict, fragment: str
):
    """fix(#1614 codex r4): NaN and inverted bounds 400 like parse_bbox()."""
    resp = await client.get(_items_url(filter_dataset), params=params)
    assert resp.status_code == 400, resp.text
    assert fragment in resp.json()["detail"]


@pytest.mark.anyio
async def test_legacy_bbox_predicate_with_crs_rejected(
    client: AsyncClient, filter_dataset: Dataset
):
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": "BBOX(geometry, 1, 2, 3, 4, 'EPSG:3857')"},
    )
    assert resp.status_code == 400
    assert "explicit CRS" in resp.json()["detail"]


@pytest.mark.anyio
async def test_filter_still_rejected_without_value_types(
    client: AsyncClient, filter_dataset: Dataset
):
    """S_DWITHIN never executes: its upstream unit math is inverted."""
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter": "S_DWITHIN(geometry, POINT(0 0), 10, 'meters')"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# QGIS >=3.44 client-shaped integration replay (qgis/QGIS#62156)
# ---------------------------------------------------------------------------
#
# QGIS's OAPIF provider issues this exact sequence before it ever emits a
# filter=: landing page -> /conformance (capability detection, gating
# mServerSupportsFilterCql2Text + mServerSupportsBasicSpatialFunctions) ->
# /collections/{id} (find the rel=queryables link, only fetched at all when
# the conformance check passed) -> /collections/{id}/queryables (build the
# field list) -> /collections/{id}/items?filter=...&filter-lang=cql2-text
# once a QgsFeatureRequest carries a spatial predicate QGIS's
# QgsOapifCql2TextExpressionCompiler can push down. Replaying the whole
# sequence catches a break in any leg -- not just the CQL2 compiler itself --
# before it reaches a real QGIS session.


def _same_origin_path(href: str, expected_origin: str) -> str:
    """Path+query of ``href`` iff it shares ``expected_origin``.

    fix(#1680 codex r3): urlparse(href).path alone discards scheme/host, so a
    PUBLIC_API_URL that resolved a *different* origin on one leg would still
    resolve locally via ASGITransport and pass every suffix assertion -- a
    real client (QGIS) would instead be pointed off-server and fail to
    connect. Asserting the origin before discarding it makes that class of
    bug fail loudly here instead of shipping silently.
    """
    parsed = urlparse(href)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    assert origin == expected_origin, (
        f"advertised link {href!r} has origin {origin!r}, expected "
        f"{expected_origin!r} -- a real client could not follow it"
    )
    path = parsed.path
    return f"{path}?{parsed.query}" if parsed.query else path


@pytest.mark.anyio
async def test_qgis_344_request_sequence_end_to_end(
    client: AsyncClient, filter_dataset: Dataset
):
    # 1. Landing page: QGIS follows rel=data (collections) and rel=conformance
    # from here. Every subsequent leg is fetched via its *discovered* href,
    # validated to share the landing page's own origin (fix(#1680 codex
    # r1-r3): a hard-coded path would still land on the right local route even
    # if an advertised link pointed somewhere QGIS could never actually reach,
    # silently defeating the whole point of replaying advertised links).
    landing = await client.get("/")
    assert landing.status_code == 200
    landing_links = landing.json()["links"]
    self_href = next(link["href"] for link in landing_links if link["rel"] == "self")
    origin = f"{urlparse(self_href).scheme}://{urlparse(self_href).netloc}"

    conformance_href = next(
        link["href"] for link in landing_links if link["rel"] == "conformance"
    )
    assert conformance_href.endswith("/conformance")
    data_href = next(link["href"] for link in landing_links if link["rel"] == "data")
    assert data_href.endswith("/collections")

    # 2. Conformance: gates mServerSupportsFilterCql2Text (base push-down) AND
    # mServerSupportsBasicSpatialFunctions (spatial predicate push-down), per
    # qgis/QGIS#62156 (see test_ogc_discovery.py for the full URI-by-URI pin).
    conformance = await client.get(_same_origin_path(conformance_href, origin))
    assert conformance.status_code == 200
    conforms_to = set(conformance.json()["conformsTo"])
    required = {
        "http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2",
        "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter",
        "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter",
        "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
        "http://www.opengis.net/spec/cql2/1.0/conf/basic-spatial-functions",
    }
    assert required <= conforms_to

    # 3. Collections list, reached via the landing page's rel=data link (the
    # ONE hand-known value left is *which* collection id to pick, matching
    # how a QGIS user browses the list and clicks a layer -- every href that
    # gets followed, including paging, comes from a response, never from
    # re-deriving it from the id). Other tests in this shared-DB file leave
    # their fixture datasets' catalog rows behind (only the backing table is
    # dropped), so the target collection is not guaranteed to be on page one
    # -- follow rel=next like a real client paging a large catalog would.
    target_id = str(filter_dataset.id)
    collections_href = data_href
    collection_entry = None
    for _ in range(50):  # generous bound; a real catalog would still terminate
        collections = await client.get(_same_origin_path(collections_href, origin))
        assert collections.status_code == 200
        payload = collections.json()
        collection_entry = next(
            (e for e in payload["collections"] if e["id"] == target_id), None
        )
        if collection_entry is not None:
            break
        next_href = next(
            (link["href"] for link in payload["links"] if link["rel"] == "next"),
            None,
        )
        assert next_href is not None, (
            f"collection {target_id} not found in /collections and no "
            "rel=next page remains"
        )
        collections_href = next_href
    assert collection_entry is not None
    collection_self_href = next(
        link["href"] for link in collection_entry["links"] if link["rel"] == "self"
    )
    assert collection_self_href.endswith(f"/collections/{filter_dataset.id}")

    # 4. Collection metadata, reached via the collections-list entry's own
    # rel=self link discovered above.
    collection = await client.get(_same_origin_path(collection_self_href, origin))
    assert collection.status_code == 200
    collection_links = collection.json()["links"]
    queryables_href = next(
        link["href"]
        for link in collection_links
        if link["rel"] == "http://www.opengis.net/def/rel/ogc/1.0/queryables"
    )
    assert queryables_href.endswith(f"/collections/{filter_dataset.id}/queryables")
    items_href = next(
        link["href"] for link in collection_links if link["rel"] == "items"
    )
    assert items_href.endswith(f"/collections/{filter_dataset.id}/items")

    # 5. Queryables: QGIS builds its field list + geometry queryable from
    # this -- again via the discovered href, not a re-typed path.
    queryables = await client.get(_same_origin_path(queryables_href, origin))
    assert queryables.status_code == 200
    props = queryables.json()["properties"]
    assert "geometry" in props
    assert "name" in props

    # 6. Items with a pushed-down spatial predicate, exactly as QGIS's
    # QgsOapifCql2TextExpressionCompiler emits it for a map-canvas-extent
    # request (S_INTERSECTS + a BBOX() literal), cql2-text encoded. Issued
    # against the discovered items_href, not a re-typed path.
    items = await client.get(
        _same_origin_path(items_href, origin),
        params={
            "filter": f"S_INTERSECTS(geometry,BBOX({','.join(str(v) for v in BBOX_12)}))",
            "filter-lang": "cql2-text",
        },
    )
    assert items.status_code == 200, items.text
    body = items.json()
    assert body["numberMatched"] == 2
    names = {f["properties"]["name"] for f in body["features"]}
    assert names == {"Alpha", "Beta"}
