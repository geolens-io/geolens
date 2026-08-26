"""OGC API Features Part 3 queryables, schema introspection, and CQL2 filtering.

# What this module does
# ---------------------
# OGC API Features Part 3 ("Filtering") defines the `/queryables` endpoint that
# tells clients which attributes are filterable for each collection, and the
# `filter` query parameter which accepts CQL2 expressions. This module:
#
#   1. Builds the `DatasetQueryables` JSON Schema document from a dataset's
#      `column_info` (used by `/collections/{id}/queryables`)
#   2. Parses CQL2-Text expressions into SQL WHERE fragments via cql2-text
#   3. Validates queryables against the dataset schema before query execution
#
# # CQL2 vs CQL1
# Only CQL2 is supported. CQL1 (the legacy WFS 2.0 filter syntax) is NOT
# accepted — clients must use the modern CQL2-Text or CQL2-JSON encoding
# defined in OGC 21-065.
"""

import json
import re
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.standards.ogc.utils import build_url
from app.modules.catalog.search.schemas import OGCRecordResponse


class DatasetQueryables(BaseModel):
    """Queryable properties for the datasets collection.

    Each field corresponds to a filterable property exposed via the
    /collections/datasets/queryables endpoint.
    """

    title: str = Field(description="Dataset title")
    description: str | None = Field(default=None, description="Dataset description")
    geometry_type: str | None = Field(default=None, description="Geometry type")
    srid: int | None = Field(
        default=None, description="Spatial Reference ID (EPSG code)"
    )
    source_organization: str | None = Field(
        default=None, description="Data source organization"
    )
    license: str | None = Field(default=None, description="Data license")
    created: datetime | None = Field(
        default=None, description="Record creation timestamp"
    )
    updated: datetime | None = Field(
        default=None, description="Record last update timestamp"
    )
    data_vintage_start: date | None = Field(
        default=None, description="Data vintage start date"
    )
    data_vintage_end: date | None = Field(
        default=None, description="Data vintage end date"
    )


# Maps OGC queryable property names to SQLAlchemy model columns.
# After records+datasets split, shared metadata fields are on Record.
FIELD_MAPPING = {
    "title": Record.title,
    "description": Record.summary,
    "geometry_type": Dataset.geometry_type,
    "srid": Dataset.srid,
    "source_organization": Record.source_organization,
    "license": Record.license,
    "created": Record.created_at,
    "updated": Record.updated_at,
    "data_vintage_start": Record.temporal_start,
    "data_vintage_end": Record.temporal_end,
    "geometry": Record.spatial_extent,  # spatial predicates
}


def parse_cql2_filter(filter_expr: str, filter_lang: str) -> Any:
    """Parse a CQL2 filter expression into an AST.

    Args:
        filter_expr: The CQL2 filter expression string.
        filter_lang: Either "cql2-text" or "cql2-json".

    Returns:
        Parsed AST from pygeofilter.

    Raises:
        HTTPException(400): On unsupported filter-lang or invalid expression.
    """
    from lark.exceptions import (
        UnexpectedCharacters,
        UnexpectedInput,
        UnexpectedToken,
    )

    if filter_lang == "cql2-text":
        from pygeofilter.parsers.cql2_text import parse

        try:
            return parse(filter_expr)
        except (
            UnexpectedToken,
            UnexpectedCharacters,
            UnexpectedInput,
            ValueError,
            KeyError,
            RecursionError,
        ) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid CQL2 expression: {e}",
            )
    elif filter_lang == "cql2-json":
        from pygeofilter.parsers.cql2_json import parse

        try:
            filter_dict = (
                json.loads(filter_expr) if isinstance(filter_expr, str) else filter_expr
            )
            filter_dict = _normalize_cql2_json(filter_dict)
        except (json.JSONDecodeError, RecursionError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid CQL2 expression: {e}",
            )
        # fix(#1614): pygeofilter's json walker raises bare Exception on an
        # embedded filter-lang key and RecursionError on deep nesting — both
        # 500'd. Every parse failure on caller input is a 400.
        try:
            return parse(filter_dict)
        except HTTPException:
            raise
        except Exception as e:  # broad: pygeofilter raises bare Exception/RecursionError on caller input; every parse failure is a 400
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid CQL2 expression: {e}",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported filter-lang: {filter_lang}. Use cql2-text or cql2-json.",
        )


def apply_cql2_filter(
    stmt: Any, filter_expr: str, filter_lang: str = "cql2-text"
) -> Any:
    """Parse a CQL2 expression and apply it as a WHERE clause to a SQLAlchemy statement.

    Args:
        stmt: SQLAlchemy select statement to add the filter to.
        filter_expr: The CQL2 filter expression string.
        filter_lang: Either "cql2-text" or "cql2-json".

    Returns:
        The statement with the CQL2 filter applied.

    Raises:
        HTTPException(400): On invalid CQL2 expression or filter translation error.
    """
    from pygeofilter.backends.sqlalchemy import to_filter

    ast = parse_cql2_filter(filter_expr, filter_lang)
    try:
        sa_filter = to_filter(ast, FIELD_MAPPING)
    except Exception as e:  # broad: pygeofilter to_filter can throw varied errors on unsupported CQL2; map to 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CQL2 expression: {e}",
        )
    return stmt.where(sa_filter)


def build_queryables_response(public_api_url: str) -> dict:
    """Build a JSON Schema describing queryable properties (OGC Part 3)."""
    schema = DatasetQueryables.model_json_schema()
    schema["$id"] = build_url(
        "/collections/datasets/queryables", base_url=public_api_url
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["type"] = "object"
    schema["additionalProperties"] = True

    # Add geometry property (not on the Pydantic model since it's spatial-only)
    props = schema.setdefault("properties", {})
    props["geometry"] = {
        "description": "Dataset spatial extent",
        "format": "geometry-polygon",
    }

    return schema


def build_record_schema_response(public_api_url: str) -> dict:
    """Build a JSON Schema describing the full OGC Record structure."""
    schema = OGCRecordResponse.model_json_schema()
    schema["$id"] = build_url("/collections/datasets/schema", base_url=public_api_url)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


# ---------------------------------------------------------------------------
# Per-dataset feature-collection filtering (OGC Features Part 3, #1614)
# ---------------------------------------------------------------------------
#
# The Records collection above filters ORM columns through a static
# FIELD_MAPPING. Feature collections filter *arbitrary per-dataset data
# tables*, so the mapping is built per request from the live table schema and
# the resulting SQLAlchemy expression is compiled into a parameterized SQL
# fragment that features.service.get_features() appends to its WHERE clauses.
# Identifiers only ever come from the live schema vetted by
# _FEATURE_QUERYABLE_NAME_RE; values only ever travel as bind parameters.

# Mirrors _COLUMN_NAME_RE in app.modules.catalog.features.service (kept as a
# literal so this standards module gains no product-module import; the
# layering test freezes this file's import surface). Excluding anything else
# (e.g. Socrata ':id' columns) also sidesteps the colon-inside-text()
# quoting traps (fix(#640)/fix(#1113)).
_FEATURE_QUERYABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Cap caller filter size before parsing: deeply nested cql2-json otherwise
# recurses arbitrarily and un-indexed predicates cost per byte anyway.
MAX_FEATURE_FILTER_LENGTH = 10_000

_GEOMETRY_MARKER = "geometry"

# Postgres type -> JSON Schema fragment for the queryables document. A column
# whose type is absent here is not filterable and is omitted from queryables.
_PG_TYPE_TO_SCHEMA: dict[str, dict] = {
    "text": {"type": "string"},
    "character varying": {"type": "string"},
    "character": {"type": "string"},
    "smallint": {"type": "integer"},
    "integer": {"type": "integer"},
    "bigint": {"type": "integer"},
    "real": {"type": "number"},
    "double precision": {"type": "number"},
    "numeric": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "timestamp without time zone": {"type": "string", "format": "date-time"},
    "timestamp with time zone": {"type": "string", "format": "date-time"},
}

_STRING_PG_TYPES = {"text", "character varying", "character"}
_INTEGER_PG_TYPES = {"smallint", "integer", "bigint"}
_NUMBER_PG_TYPES = {"real", "double precision", "numeric"}
_TEMPORAL_PG_TYPES = {
    "date",
    "timestamp without time zone",
    "timestamp with time zone",
}


def feature_queryable_columns(
    column_info: list[dict], geometry_type: str | None
) -> dict[str, str]:
    """Map queryable property name -> postgres type for one feature table.

    ``column_info`` rows come from the live information_schema
    (CatalogPort.get_column_info), NOT from the stored Dataset.column_info —
    same authority rule as live_property_columns (fix(#1104)): stored metadata
    can drift from the table on re-upload, and the filter's allowed set must
    match what the SQL will see.

    The spatial ``geometry`` queryable wins over any attribute column
    literally named ``geometry`` (the attribute becomes non-filterable).
    """
    out: dict[str, str] = {}
    for col in column_info:
        name = col.get("name")
        pg_type = col.get("type")
        if (
            isinstance(name, str)
            and pg_type in _PG_TYPE_TO_SCHEMA
            and _FEATURE_QUERYABLE_NAME_RE.match(name)
        ):
            out[name] = pg_type
    if geometry_type:
        out[_GEOMETRY_MARKER] = _GEOMETRY_MARKER
    return out


def build_feature_queryables_response(
    dataset_id: str,
    title: str | None,
    queryables: dict[str, str],
    public_api_url: str,
) -> dict:
    """JSON Schema queryables document for one feature collection (Part 3).

    ``additionalProperties: false`` is deliberate: it is the Part 3 lever that
    makes rejecting filters on non-queryable properties (400) spec-conformant.
    """
    props: dict[str, dict] = {}
    for name, pg_type in sorted(queryables.items()):
        if pg_type == _GEOMETRY_MARKER:
            props[name] = {
                "description": "Feature geometry",
                "format": "geometry-any",
            }
        else:
            props[name] = dict(_PG_TYPE_TO_SCHEMA[pg_type])
    schema: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": build_url(
            f"/collections/{dataset_id}/queryables", base_url=public_api_url
        ),
        "type": "object",
        "properties": props,
        "additionalProperties": False,
    }
    if title:
        schema["title"] = title
    return schema


def _bbox_ring(minx, miny, maxx, maxy) -> list:
    return [
        [
            [minx, miny],
            [maxx, miny],
            [maxx, maxy],
            [minx, maxy],
            [minx, miny],
        ]
    ]


def _bbox_geometry(minx, miny, maxx, maxy) -> dict:
    """GeoJSON geometry for a BBox literal.

    fix(#1614 codex r1): minx > maxx is a legal antimeridian-crossing box
    (same convention as the ``bbox=`` parameter). A single planar rectangle
    would invert it into nearly the whole globe, so split at the dateline
    into a MultiPolygon — mirroring what get_features() does for ``bbox=``.
    """
    if minx > maxx:
        return {
            "type": "MultiPolygon",
            "coordinates": [
                _bbox_ring(minx, miny, 180, maxy),
                _bbox_ring(-180, miny, maxx, maxy),
            ],
        }
    return {"type": "Polygon", "coordinates": _bbox_ring(minx, miny, maxx, maxy)}


def _normalize_cql2_json(node):
    """Rewrite final-spec (21-065r2) JSON shapes pygeofilter 0.4.0 mis-parses.

    fix(#1614), verified against the vendored parser:
    - ``between``: the spec defines flat 3-element ``args``; the parser reads
      the draft nested ``[expr, [low, high]]`` and TypeErrors on the flat form.
    - ``{"bbox": [...]}``: the parser unpacks GeoJSON bbox order into
      ``values.Envelope(x1, x2, y1, y2)``, scrambling axes so the SQLAlchemy
      backend renders a silently wrong polygon. Rewritten to an explicit
      GeoJSON Polygon, which renders correctly via parse_geometry.
    """
    if isinstance(node, list):
        return [_normalize_cql2_json(n) for n in node]
    if not isinstance(node, dict):
        return node
    if "type" in node and "coordinates" in node:
        # fix(#1614 codex r2): a GeoJSON geometry may carry the optional
        # ``bbox`` member; it is metadata, not a BBox literal — rewriting it
        # would silently replace the shape with its bounding rectangle. Same
        # precedence as pygeofilter's own walker (geometry before bbox).
        return node
    bbox = node.get("bbox")
    if (
        isinstance(bbox, list)
        and len(bbox) in (4, 6)
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox)
    ):
        if len(bbox) == 6:  # 3D bbox: Z bounds are ignored, like parse_bbox
            bbox = [bbox[0], bbox[1], bbox[3], bbox[4]]
        return _bbox_geometry(*bbox)
    out = {k: _normalize_cql2_json(v) for k, v in node.items()}
    args = out.get("args")
    if out.get("op") == "between" and isinstance(args, list) and len(args) == 3:
        out["args"] = [args[0], [args[1], args[2]]]
    return out


def _rewrite_text_bbox_literals(node):
    """Rewrite cql2-text ``BBOX(minx,miny,maxx,maxy)`` geometry literals.

    fix(#1614): the text grammar only knows BBOX as the legacy 5-argument
    *predicate*, so a Part 3 BBox literal inside e.g. S_INTERSECTS parses as a
    generic ``Function("bbox", [4 numbers])`` that the SQLAlchemy backend
    KeyErrors on. Rewrite it to a Polygon literal. Anything else is left
    untouched for validation to reject.
    """
    from pygeofilter import ast as pgf_ast
    from pygeofilter import values as pgf_values

    if isinstance(node, (list, tuple)):
        return type(node)(_rewrite_text_bbox_literals(n) for n in node)
    if isinstance(node, pgf_ast.Function) and str(node.name).lower() == "bbox":
        args = node.arguments
        if len(args) == 4 and all(
            isinstance(a, (int, float)) and not isinstance(a, bool) for a in args
        ):
            return pgf_values.Geometry(_bbox_geometry(*args))
        return node
    if isinstance(node, pgf_ast.BBox) and node.crs is None:
        # fix(#1614 codex r1): the legacy BBOX(prop, ...) predicate renders a
        # planar rectangle upstream, inverting antimeridian-crossing boxes.
        # Route it through the same split geometry as the BBox literal.
        return pgf_ast.GeometryIntersects(
            node.lhs,
            pgf_values.Geometry(
                _bbox_geometry(node.minx, node.miny, node.maxx, node.maxy)
            ),
        )
    if isinstance(node, pgf_ast.Node):
        for field, value in vars(node).items():
            setattr(node, field, _rewrite_text_bbox_literals(value))
    return node


def _require_attribute(node, queryables: dict[str, str], errors: list[str]):
    """Return the pg type of an Attribute node, recording an error otherwise."""
    from pygeofilter import ast as pgf_ast

    if not isinstance(node, pgf_ast.Attribute):
        errors.append("predicate operand must be a property name")
        return None
    pg_type = queryables.get(node.name)
    if pg_type is None:
        errors.append(f"unknown or non-filterable property {node.name!r}")
    return pg_type


def _checked_value(value, pg_type: str | None, errors: list[str]):
    """Type-check a literal against a property's pg type; return it normalized.

    Catching type mismatches here turns the mainline user typo (``name > 5``
    on a text column) into a 400 naming the mismatch, instead of a database
    error surfacing as a misleading 503/500 (QA finding B3). Also normalizes
    tz-aware datetime literals for timestamp-without-tz columns, which asyncpg
    would otherwise refuse at bind time.
    """
    from pygeofilter import ast as pgf_ast

    if isinstance(value, pgf_ast.Node):
        errors.append("nested expressions are not supported in comparisons")
        return value
    if pg_type is None:
        return value  # the attribute side already recorded an error
    if pg_type in _TEMPORAL_PG_TYPES:
        if not isinstance(value, (date, datetime)):
            errors.append(
                f"property typed {pg_type!r} needs a DATE('...')/TIMESTAMP('...') "
                'literal (cql2-json: {"date"/"timestamp": ...})'
            )
        elif (
            pg_type == "timestamp without time zone"
            and isinstance(value, datetime)
            and value.tzinfo is not None
        ):
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if pg_type in _STRING_PG_TYPES:
        ok = isinstance(value, str)
    elif pg_type in _INTEGER_PG_TYPES:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif pg_type in _NUMBER_PG_TYPES:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif pg_type == "boolean":
        ok = isinstance(value, bool)
    else:  # geometry marker in a scalar position
        ok = False
    if not ok:
        errors.append(
            f"literal {value!r} does not match the property's {pg_type!r} type"
        )
    return value


def _validate_scalar_predicate(node, queryables: dict[str, str], errors: list[str]):
    """Comparison / BETWEEN / LIKE / IN / IS NULL over attribute columns."""
    from pygeofilter import ast as pgf_ast

    geom_error = "geometry needs a spatial predicate (e.g. S_INTERSECTS)"
    if isinstance(node, pgf_ast.Comparison):
        lhs_attr = isinstance(node.lhs, pgf_ast.Attribute)
        rhs_attr = isinstance(node.rhs, pgf_ast.Attribute)
        if not lhs_attr and not rhs_attr:
            errors.append("comparison must reference a property")
            return
        lhs_t = _require_attribute(node.lhs, queryables, errors) if lhs_attr else None
        rhs_t = _require_attribute(node.rhs, queryables, errors) if rhs_attr else None
        if _GEOMETRY_MARKER in (lhs_t, rhs_t):
            errors.append(geom_error)
        elif lhs_attr and not rhs_attr:
            node.rhs = _checked_value(node.rhs, lhs_t, errors)
        elif rhs_attr and not lhs_attr:
            node.lhs = _checked_value(node.lhs, rhs_t, errors)
        # property-to-property comparisons pass through; the execute-time
        # guard maps an incomparable pair to 400.
    elif isinstance(node, pgf_ast.Between):
        pg_type = _require_attribute(node.lhs, queryables, errors)
        if pg_type == _GEOMETRY_MARKER:
            errors.append(geom_error)
            return
        node.low = _checked_value(node.low, pg_type, errors)
        node.high = _checked_value(node.high, pg_type, errors)
    elif isinstance(node, pgf_ast.Like):
        pg_type = _require_attribute(node.lhs, queryables, errors)
        if pg_type is not None and pg_type not in _STRING_PG_TYPES:
            errors.append("LIKE only applies to string properties")
        if not isinstance(node.pattern, str):
            errors.append("LIKE pattern must be a string")
    elif isinstance(node, pgf_ast.In):
        pg_type = _require_attribute(node.lhs, queryables, errors)
        if pg_type == _GEOMETRY_MARKER:
            errors.append(geom_error)
            return
        node.sub_nodes = [
            _checked_value(sub, pg_type, errors) for sub in node.sub_nodes
        ]
    else:  # IsNull
        _require_attribute(node.lhs, queryables, errors)


def _validate_spatial_predicate(node, queryables: dict[str, str], errors: list[str]):
    """S_* binary predicates and the legacy BBOX(prop, ...) predicate."""
    from pygeofilter import ast as pgf_ast
    from pygeofilter import values as pgf_values

    if isinstance(node, pgf_ast.BBox):
        # crs-less BBox predicates were rewritten to S_INTERSECTS above; only
        # a crs-qualified form reaches here, and only CRS84 boxes are defined.
        errors.append("BBOX with an explicit CRS is not supported")
        return
    attr_side, literal_side = node.lhs, node.rhs
    if isinstance(literal_side, pgf_ast.Attribute) and not isinstance(
        attr_side, pgf_ast.Attribute
    ):
        attr_side, literal_side = literal_side, attr_side
    pg_type = _require_attribute(attr_side, queryables, errors)
    if pg_type is not None and pg_type != _GEOMETRY_MARKER:
        errors.append(
            "spatial predicates apply to the geometry property"
            if _GEOMETRY_MARKER in queryables
            else "this collection has no geometry"
        )
    if not isinstance(literal_side, (pgf_values.Geometry, pgf_values.Envelope)):
        errors.append(
            "spatial predicates need a geometry literal (WKT, BBOX or GeoJSON)"
        )


def _validate_feature_filter_node(node, queryables: dict[str, str], errors: list[str]):
    """Whitelist walk: every supported predicate shape is handled explicitly.

    Anything unlisted (functions, arithmetic, arrays, S_DWITHIN/S_BEYOND with
    its inverted upstream unit math, T_* predicates with their collapsed
    BETWEEN semantics) is rejected up front, so only constructs with tests
    behind the advertised conformance classes ever reach SQL.
    """
    from pygeofilter import ast as pgf_ast

    if isinstance(node, (pgf_ast.And, pgf_ast.Or)):
        _validate_feature_filter_node(node.lhs, queryables, errors)
        _validate_feature_filter_node(node.rhs, queryables, errors)
    elif isinstance(node, pgf_ast.Not):
        _validate_feature_filter_node(node.sub_node, queryables, errors)
    elif isinstance(
        node,
        (pgf_ast.Comparison, pgf_ast.Between, pgf_ast.Like, pgf_ast.In, pgf_ast.IsNull),
    ):
        _validate_scalar_predicate(node, queryables, errors)
    elif isinstance(node, pgf_ast.SpatialDistancePredicate):
        errors.append("S_DWITHIN/S_BEYOND are not supported")
    elif isinstance(node, pgf_ast.Relate):
        errors.append("RELATE is not supported")
    elif isinstance(node, (pgf_ast.SpatialComparisonPredicate, pgf_ast.BBox)):
        _validate_spatial_predicate(node, queryables, errors)
    elif isinstance(node, pgf_ast.TemporalPredicate):
        errors.append(
            "temporal predicates (T_*) are not supported; use >=/<= comparisons "
            "on date/timestamp properties"
        )
    else:
        errors.append(f"unsupported expression: {type(node).__name__}")


def parse_feature_cql2(filter_expr: str, filter_lang: str) -> Any:
    """Length-cap, parse, and shim-rewrite a feature-collection filter.

    Split from compilation (fix(#1614 codex r2) follow-up) so the router can
    order its checks precisely: a parse failure is the caller's bug and 400s
    with no database access at all; table availability (503) is checked next;
    only then does schema-dependent validation/compilation run.
    """
    if len(filter_expr) > MAX_FEATURE_FILTER_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"filter exceeds the {MAX_FEATURE_FILTER_LENGTH}-character limit"),
        )
    ast_root = parse_cql2_filter(filter_expr, filter_lang)
    return _rewrite_text_bbox_literals(ast_root)


def compile_feature_cql2(
    filter_expr: str,
    filter_lang: str,
    queryables: dict[str, str],
) -> tuple[str, dict]:
    """Parse + compile in one step (kept for callers that need no ordering)."""
    return compile_feature_cql2_ast(
        parse_feature_cql2(filter_expr, filter_lang), queryables
    )


def compile_feature_cql2_ast(
    ast_root: Any,
    queryables: dict[str, str],
) -> tuple[str, dict]:
    """Compile a parsed CQL2 AST into a (sql_fragment, bind_params) pair.

    The fragment references only unqualified, live-schema-vetted column names
    (bare ``sqlalchemy.column()`` — a table-qualified column would not resolve
    against the ``t`` alias both feature queries use) and carries every value
    as a ``:cql2_N``-prefixed bind parameter, so it can be appended verbatim
    to get_features()'s WHERE clauses inside ``text()``.

    Raises HTTPException(400) on any unsupported or type-mismatched filter.
    """
    from geoalchemy2 import Geometry
    from pygeofilter.backends.sqlalchemy import to_filter
    from sqlalchemy import column as sa_column
    from sqlalchemy import types as sa_types
    from sqlalchemy.dialects import postgresql

    errors: list[str] = []
    _validate_feature_filter_node(ast_root, queryables, errors)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported CQL2 filter: " + "; ".join(sorted(set(errors))),
        )

    sa_type_for_pg = {
        **{t: sa_types.Text() for t in _STRING_PG_TYPES},
        **{t: sa_types.BigInteger() for t in _INTEGER_PG_TYPES},
        **{t: sa_types.Float() for t in _NUMBER_PG_TYPES},
        "boolean": sa_types.Boolean(),
        "date": sa_types.Date(),
        "timestamp without time zone": sa_types.DateTime(),
        "timestamp with time zone": sa_types.DateTime(timezone=True),
    }
    field_mapping = {}
    for name, pg_type in queryables.items():
        if pg_type == _GEOMETRY_MARKER:
            field_mapping[name] = sa_column("geom_4326", Geometry(srid=4326))
        else:
            field_mapping[name] = sa_column(name, sa_type_for_pg[pg_type])

    try:
        sa_filter = to_filter(ast_root, field_mapping, undefined_as_null=False)
        compiled = sa_filter.compile(
            dialect=postgresql.dialect(paramstyle="named"),
            compile_kwargs={"render_postcompile": True},
        )
    except HTTPException:
        raise
    except Exception as e:  # broad: same contract as apply_cql2_filter — pygeofilter/compile errors on caller input map to 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CQL2 expression: {e}",
        )

    sql = str(compiled)
    params: dict = {}
    for i, (key, value) in enumerate(compiled.params.items()):
        new_key = f"cql2_{i}"
        # (?<!:) skips ::casts; \b keeps :param_1 from matching inside
        # :param_10 (word boundary fails between two word characters).
        sql, n = re.subn(rf"(?<!:):{re.escape(key)}\b", f":{new_key}", sql)
        if n != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid CQL2 expression: parameter rendering failed",
            )
        params[new_key] = value
    return f"({sql})", params
