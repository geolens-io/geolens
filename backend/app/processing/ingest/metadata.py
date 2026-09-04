"""PostGIS metadata extraction functions.

All functions take an AsyncSession and a table name. Table names are validated
against a strict pattern to prevent SQL injection (they are identifiers, not
parameterizable values).

fix(#1042): the implementations now live in sibling ``metadata_*`` modules and
this file re-exports them. It reached 2151 lines with five carve-outs on its
size cap, each one a correctness fix that had to argue for its lines; the seams
below are the ones the carve-outs kept landing on.

  - ``metadata_sql``         identifier validation and quoting (the shared base)
  - ``metadata_geometry``    constructing ``geom``, laundering column names
  - ``metadata_extent``      reading metadata back off a landed table
  - ``metadata_mercator``    the clip, the 0..360 shift, the CRS predicates
  - ``metadata_projection``  the 4326 render column and the reader grant
  - ``metadata_quality``     dataset quality scoring
  - ``metadata_attributes``  attribute-metadata rows and their inference

Import from here, not from the sub-modules: this façade is what the ingest
tasks, the export paths and the extension defaults have always imported, and
what the ``mock.patch("app.processing.ingest.metadata.<name>")`` targets in the
test suite resolve against. Two references point at a sub-module on purpose,
because they need the module a call physically lives in rather than the name it
is published under: the ``_mercator_envelope_degenerates`` monkeypatch in
``tests/test_ingest_mercator_clip.py`` and the srtext-predicate imports in
``tests/test_crs_degree_agreement.py``.
"""

from app.processing.ingest.metadata_attributes import (
    _PG_TYPE_TO_DOMAIN,  # noqa: F401 -- re-exported, see __all__
    _UNIT_SUFFIX_MAP,  # noqa: F401 -- re-exported, see __all__
    _build_attribute_metadata,  # noqa: F401 -- re-exported, see __all__
    _build_geometry_attribute_row,  # noqa: F401 -- re-exported, see __all__
    _humanize_column_name,  # noqa: F401 -- re-exported, see __all__
    _infer_domain_type,  # noqa: F401 -- re-exported, see __all__
    _infer_semantic_role,  # noqa: F401 -- re-exported, see __all__
    _infer_units,  # noqa: F401 -- re-exported, see __all__
    generate_attribute_metadata,  # noqa: F401 -- re-exported, see __all__
    refresh_attribute_metadata,  # noqa: F401 -- re-exported, see __all__
)
from app.processing.ingest.metadata_extent import (
    _ABSTRACT_TO_CONCRETE_GEOMETRY_TYPE,  # noqa: F401 -- re-exported, see __all__
    _BOX3D_RE,  # noqa: F401 -- re-exported, see __all__
    _normalize_geometry_type,  # noqa: F401 -- re-exported, see __all__
    _parse_box3d_z_bounds,  # noqa: F401 -- re-exported, see __all__
    _seam_crossing_extent_wkt,  # noqa: F401 -- re-exported, see __all__
    _table_has_geometry,  # noqa: F401 -- re-exported, see __all__
    detect_3d_metadata,  # noqa: F401 -- re-exported, see __all__
    extract_metadata,  # noqa: F401 -- re-exported, see __all__
    get_column_info,  # noqa: F401 -- re-exported, see __all__
    get_extent,  # noqa: F401 -- re-exported, see __all__
    get_feature_count,  # noqa: F401 -- re-exported, see __all__
    get_geometry_type,  # noqa: F401 -- re-exported, see __all__
    get_sample_values,  # noqa: F401 -- re-exported, see __all__
    get_table_srid,  # noqa: F401 -- re-exported, see __all__
    promote_z_to_elev,  # noqa: F401 -- re-exported, see __all__
)
from app.processing.ingest.metadata_geometry import (
    construct_point_geometry,  # noqa: F401 -- re-exported, see __all__
    construct_wkt_geometry,  # noqa: F401 -- re-exported, see __all__
    detect_dbf_truncation_collisions,  # noqa: F401 -- re-exported, see __all__
    ensure_geom_column,  # noqa: F401 -- re-exported, see __all__
    rename_reserved_columns,  # noqa: F401 -- re-exported, see __all__
)
from app.processing.ingest.metadata_mercator import (
    _DEGREE_UNIT_SRTEXT_RE,  # noqa: F401 -- re-exported, see __all__
    _GEOGRAPHIC_SRTEXT_RE,  # noqa: F401 -- re-exported, see __all__
    _MERCATOR_SAFE_ENVELOPE,  # noqa: F401 -- re-exported, see __all__
    _mercator_envelope_degenerates,  # noqa: F401 -- re-exported, see __all__
    _shift_zero_to_360_longitudes,  # noqa: F401 -- re-exported, see __all__
    clip_to_mercator_bounds,  # noqa: F401 -- re-exported, see __all__
)
from app.processing.ingest.metadata_projection import (
    REPAIR_APPLIED,  # noqa: F401 -- re-exported, see __all__
    REPAIR_GENERATED,  # noqa: F401 -- re-exported, see __all__
    REPAIR_NO_GEOMETRY,  # noqa: F401 -- re-exported, see __all__
    Geom4326Repair,  # noqa: F401 -- re-exported, see __all__
    add_4326_column,  # noqa: F401 -- re-exported, see __all__
    ensure_geom_4326_gist_index,  # noqa: F401 -- re-exported, see __all__
    grant_reader_access,  # noqa: F401 -- re-exported, see __all__
    linearize_existing_4326,  # noqa: F401 -- re-exported, see __all__
    rederive_geom_4326,  # noqa: F401 -- re-exported, see __all__
)
from app.processing.ingest.metadata_quality import (
    _score_attribute_completeness,  # noqa: F401 -- re-exported, see __all__
    _score_crs,  # noqa: F401 -- re-exported, see __all__
    _score_geometry_validity,  # noqa: F401 -- re-exported, see __all__
    _score_metadata_completeness,  # noqa: F401 -- re-exported, see __all__
    compute_quality_score,  # noqa: F401 -- re-exported, see __all__
)
from app.processing.ingest.metadata_sql import (
    _TABLE_NAME_RE,  # noqa: F401 -- re-exported, see __all__
    _qtable,  # noqa: F401 -- re-exported, see __all__
    _sql_quote_ident,  # noqa: F401 -- re-exported, see __all__
    _validate_table_name,  # noqa: F401 -- re-exported, see __all__
)

__all__ = [
    "REPAIR_APPLIED",
    "REPAIR_GENERATED",
    "REPAIR_NO_GEOMETRY",
    "Geom4326Repair",
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
    "promote_z_to_elev",
    "rederive_geom_4326",
    "refresh_attribute_metadata",
    "rename_reserved_columns",
]
