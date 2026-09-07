"""PostGIS metadata extraction functions.

Functions take an AsyncSession and a table name, validated against a strict
identifier pattern (SQL injection guard).

fix(#1042): implementations live in sibling ``metadata_*`` modules; this file
re-exports them as the stable import surface (ingest tasks, export paths,
extension defaults, and ``mock.patch("app.processing.ingest.metadata.<name>")``
in tests all resolve against it — import from here, not the sub-modules).

  - ``metadata_sql``         identifier validation and quoting (shared base)
  - ``metadata_geometry``    constructing ``geom``, laundering column names
  - ``metadata_extent``      reading metadata back off a landed table
  - ``metadata_mercator``    the clip, the 0..360 shift, the CRS predicates
  - ``metadata_projection``  the 4326 render column and the reader grant
  - ``metadata_quality``     dataset quality scoring
  - ``metadata_attributes``  attribute-metadata rows and their inference

Two tests import a sub-module directly on purpose: the
``_mercator_envelope_degenerates`` monkeypatch in
``tests/test_ingest_mercator_clip.py`` and the srtext-predicate imports in
``tests/test_crs_degree_agreement.py``.
"""

from app.processing.ingest.metadata_attributes import (
    _PG_TYPE_TO_DOMAIN,  # noqa: F401
    _UNIT_SUFFIX_MAP,  # noqa: F401
    _build_attribute_metadata,  # noqa: F401
    _build_geometry_attribute_row,  # noqa: F401
    _humanize_column_name,  # noqa: F401
    _infer_domain_type,  # noqa: F401
    _infer_semantic_role,  # noqa: F401
    _infer_units,  # noqa: F401
    generate_attribute_metadata,  # noqa: F401
    refresh_attribute_metadata,  # noqa: F401
)
from app.processing.ingest.metadata_extent import (
    _ABSTRACT_TO_CONCRETE_GEOMETRY_TYPE,  # noqa: F401
    _BOX3D_RE,  # noqa: F401
    _normalize_geometry_type,  # noqa: F401
    _parse_box3d_z_bounds,  # noqa: F401
    _seam_crossing_extent_wkt,  # noqa: F401
    _table_has_geometry,  # noqa: F401
    detect_3d_metadata,  # noqa: F401
    extract_metadata,  # noqa: F401
    get_column_info,  # noqa: F401
    get_extent,  # noqa: F401
    get_feature_count,  # noqa: F401
    get_geometry_type,  # noqa: F401
    get_sample_values,  # noqa: F401
    get_table_srid,  # noqa: F401
    promote_z_to_elev,  # noqa: F401
)
from app.processing.ingest.metadata_geometry import (
    construct_point_geometry,  # noqa: F401
    construct_wkt_geometry,  # noqa: F401
    detect_dbf_truncation_collisions,  # noqa: F401
    ensure_geom_column,  # noqa: F401
    rename_reserved_columns,  # noqa: F401
)
from app.processing.ingest.metadata_mercator import (
    _DEGREE_UNIT_SRTEXT_RE,  # noqa: F401
    _GEOGRAPHIC_SRTEXT_RE,  # noqa: F401
    _MERCATOR_SAFE_ENVELOPE,  # noqa: F401
    _mercator_envelope_degenerates,  # noqa: F401
    _shift_zero_to_360_longitudes,  # noqa: F401
    clip_to_mercator_bounds,  # noqa: F401
)
from app.processing.ingest.metadata_projection import (
    REPAIR_APPLIED,  # noqa: F401
    REPAIR_GENERATED,  # noqa: F401
    REPAIR_NO_GEOMETRY,  # noqa: F401
    Geom4326Repair,  # noqa: F401
    Geom4326State,  # noqa: F401
    add_4326_column,  # noqa: F401
    ensure_geom_4326_gist_index,  # noqa: F401
    grant_reader_access,  # noqa: F401
    linearize_existing_4326,  # noqa: F401
    probe_geom_4326,  # noqa: F401
    rederive_geom_4326,  # noqa: F401
)
from app.processing.ingest.metadata_quality import (
    _score_attribute_completeness,  # noqa: F401
    _score_crs,  # noqa: F401
    _score_geometry_validity,  # noqa: F401
    _score_metadata_completeness,  # noqa: F401
    compute_quality_score,  # noqa: F401
)
from app.processing.ingest.metadata_sql import (
    _TABLE_NAME_RE,  # noqa: F401
    _qtable,  # noqa: F401
    _sql_quote_ident,  # noqa: F401
    _validate_table_name,  # noqa: F401
)

__all__ = [
    "REPAIR_APPLIED",
    "REPAIR_GENERATED",
    "REPAIR_NO_GEOMETRY",
    "Geom4326Repair",
    "Geom4326State",
    "_ABSTRACT_TO_CONCRETE_GEOMETRY_TYPE",
    "_BOX3D_RE",
    "_DEGREE_UNIT_SRTEXT_RE",
    "_GEOGRAPHIC_SRTEXT_RE",
    "_MERCATOR_SAFE_ENVELOPE",
    "_PG_TYPE_TO_DOMAIN",
    "_TABLE_NAME_RE",
    "_UNIT_SUFFIX_MAP",
    "_build_attribute_metadata",
    "_build_geometry_attribute_row",
    "_humanize_column_name",
    "_infer_domain_type",
    "_infer_semantic_role",
    "_infer_units",
    "_mercator_envelope_degenerates",
    "_normalize_geometry_type",
    "_parse_box3d_z_bounds",
    "_qtable",
    "_score_attribute_completeness",
    "_score_crs",
    "_score_geometry_validity",
    "_score_metadata_completeness",
    "_seam_crossing_extent_wkt",
    "_shift_zero_to_360_longitudes",
    "_sql_quote_ident",
    "_table_has_geometry",
    "_validate_table_name",
    "add_4326_column",
    "clip_to_mercator_bounds",
    "compute_quality_score",
    "construct_point_geometry",
    "construct_wkt_geometry",
    "detect_3d_metadata",
    "detect_dbf_truncation_collisions",
    "ensure_geom_4326_gist_index",
    "ensure_geom_column",
    "extract_metadata",
    "generate_attribute_metadata",
    "get_column_info",
    "get_extent",
    "get_feature_count",
    "get_geometry_type",
    "get_sample_values",
    "get_table_srid",
    "grant_reader_access",
    "linearize_existing_4326",
    "probe_geom_4326",
    "promote_z_to_elev",
    "rederive_geom_4326",
    "refresh_attribute_metadata",
    "rename_reserved_columns",
]
