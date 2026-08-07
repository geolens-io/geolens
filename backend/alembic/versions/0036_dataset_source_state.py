"""Add source-origin and refresh-state columns to catalog.datasets.

feat(#1218) / ADR-002 Decision 3. Seven nullable columns, two CHECK
constraints, and one partial index, plus a best-effort per-origin backfill.

NULL is the only stored spelling of "never determined": the CHECK sets
deliberately exclude an 'unknown' literal, and the API projects NULL to
"unknown" at the response boundary. That keeps this migration cheap (no
full-table rewrite of health/drift) and removes a way to be wrong — with
both spellings legal, every query would have to handle two forever.

Revision ID: 0036_dataset_source_state
Revises: 0035_drop_quality_score_numeric
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_dataset_source_state"
down_revision: Union[str, None] = "0035_drop_quality_score_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Formats that were fetched from a remote OGC/Esri service. Their source_url
# was machine-written at ingest, so it is a usable pointer — but only when it
# still parses as a URL. A user may have PATCHed it to prose before this
# migration ran (source_url is in _DATASET_FIELD_MAP), and a pointer that does
# not parse must stay NULL rather than be backfilled into a broken refresh.
_SERVICE_FORMATS = ("wfs", "arcgis_featureserver", "ogcapi_features")

# Everything in chk_datasets_source_format that is neither a service format,
# nor 'stac', nor 'created'. These datasets hold a copy of uploaded bytes.
_UPLOAD_FORMATS = (
    "geojson",
    "shapefile",
    "shp",
    "gpkg",
    "csv",
    "kml",
    "gml",
    "fgdb",
    "geotiff",
    "parquet",
    "json",
    "xlsx",
    "xls",
)

# The data schema a dataset row's table lives in.
#
# Asked of the catalog rather than computed from tenant_id, because those two
# can disagree: `tenant_data_schema` returns the shared `data` schema in
# single-tenant mode whatever tenant_id holds, and tenant_id is a dormant
# column that gets stamped independently of where ingest actually put the
# table. Deriving `data_t_<uuid>` from a stamped id on a single-tenant
# instance would write a pointer at a schema that does not exist — and a
# wrong pointer is worse than none, since NULL at least reads as "unknown".
# A dropped table yields NULL here, which correctly leaves origin_uri NULL.
#
# Unambiguous-or-NULL (fix #1218 review, P1). Table names are unique per
# tenant but NOT across tenants (uq_datasets_table_name_tenant is partial on
# tenant_id), so in a multi-tenant install two tenants can both own a
# `parcels` table. An unconstrained LIMIT 1 would hand one tenant's dataset a
# pointer into the OTHER tenant's schema, permanently and silently.
#
# `HAVING count(*) = 1` makes that inexpressible: the aggregate yields a row
# only when exactly one candidate schema holds a matching relation, and a
# scalar subquery over zero rows is NULL, which the `IS NOT NULL` predicate
# below then skips. Ambiguous rows keep a NULL pointer and read as "unknown".
#
# Ambiguity is per table NAME, not per row: this subquery can see only
# `d.table_name`, so it cannot tell the two colliding datasets apart, and
# BOTH stay NULL. Resolving them would mean trusting `tenant_id`, which is
# the thing the comment above establishes we cannot trust. NULL for both is
# the only answer that cannot be wrong. A dropped table (count = 0) lands in
# the same branch, which is the behaviour this had before.
#
# relkind is filtered because count(*) is now load-bearing: an index or
# sequence sharing the table's name in another data schema would otherwise
# push the count to 2 and null out a row that resolves perfectly well.
#
# A correlated scalar subquery rather than a LATERAL join: PostgreSQL does not
# expose an UPDATE's target table to LATERAL items in its FROM clause, but it
# does to a correlated subquery in SET and WHERE.
_DATA_SCHEMA_SQL = r"""
    (SELECT min(n.nspname)
     FROM pg_class c
     JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = d.table_name
       AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
       AND (n.nspname = 'data' OR n.nspname LIKE 'data\_t\_%')
     HAVING count(*) = 1)
"""


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("origin_uri", sa.String(length=2000), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("origin_ref", postgresql.JSONB(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("source_health", sa.String(length=20), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("source_health_detail", sa.Text(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "datasets",
        sa.Column("schema_drift_status", sa.String(length=20), nullable=True),
        schema="catalog",
    )

    op.create_check_constraint(
        "chk_datasets_source_health",
        "datasets",
        "source_health IS NULL OR source_health IN "
        "('healthy', 'missing', 'inaccessible')",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_datasets_schema_drift_status",
        "datasets",
        "schema_drift_status IS NULL OR schema_drift_status IN ('none', 'drifted')",
        schema="catalog",
    )
    op.create_index(
        "ix_datasets_origin_uri",
        "datasets",
        ["origin_uri"],
        schema="catalog",
        postgresql_where=sa.text("origin_uri IS NOT NULL"),
    )

    for statement in backfill_statements():
        op.execute(statement)

    # last_checked_at, source_health, source_health_detail and
    # schema_drift_status are left NULL on every row on purpose: GeoLens has
    # never contacted an origin, so any value here would be invented.


def _quoted(values: Sequence[str]) -> str:
    """SQL literal list. Every value is a hard-coded constant in this file."""
    return ", ".join(f"'{value}'" for value in values)


# Service datasets: source_url is the enriched URL ingest composed.
# ``tasks_vector`` stores ``<base>/<layer_id>`` for ArcGIS FeatureServer
# layers, so the trailing numeric segment splits back out into ``layer_id``
# and the remainder becomes ``url``. WFS and OGC API Features address their
# layer by typename/collection inside the request rather than by a path
# suffix, so their whole URL is the base.
#
# fix(#1218 review r3): a WFS/OGC row's layer identity is its typename or
# collection id, which lives on the ingest job rather than on the dataset.
# It is recovered from ``catalog.ingest_jobs.source_layer`` because the
# retention sweep in platform/jobs/router.py deliberately EXEMPTS each
# dataset's most recent complete job ("the reupload source_layer hint"), so
# that row survives regardless of age. Older jobs are purged, hence the
# newest-first pick.
#
# datasets.source_filename is deliberately NOT used as a fallback. Service
# imports set it to ``layer_title or layer_name`` (sources/router.py), so it
# is often a human title, and nothing on the row says which of the two it
# holds — writing it into layer_id would hand a refresh a display string to
# use as a typename. A dataset whose job row is gone therefore keeps a ref
# with no layer_id and needs its layer identified once before a first
# refresh; an honest gap beats invented data.
_SERVICE_BACKFILL = f"""
    UPDATE catalog.datasets AS d
    SET origin_uri = d.source_url,
        origin_ref = jsonb_strip_nulls(
            jsonb_build_object(
                'kind', 'service',
                'service_type', d.source_format,
                'url', CASE
                    WHEN d.source_format = 'arcgis_featureserver'
                         AND d.source_url ~ '/[0-9]+$'
                    THEN regexp_replace(d.source_url, '/[0-9]+$', '')
                    ELSE d.source_url
                END,
                'layer_id', CASE
                    WHEN d.source_format = 'arcgis_featureserver'
                         AND d.source_url ~ '/[0-9]+$'
                    THEN substring(d.source_url from '/([0-9]+)$')
                    WHEN d.source_format IN ('wfs', 'ogcapi_features')
                    THEN (
                        SELECT j.source_layer
                        FROM catalog.ingest_jobs AS j
                        WHERE j.dataset_id = d.id
                          AND j.status = 'complete'
                          AND j.source_layer IS NOT NULL
                        ORDER BY j.created_at DESC
                        LIMIT 1
                    )
                    ELSE NULL
                END
            )
        )
    WHERE d.source_format IN ({_quoted(_SERVICE_FORMATS)})
      AND d.source_url ~* '^https?://'
"""

# STAC datasets point at the referenced asset. ``stac_router`` stores the
# item's data-asset href in source_url and never captures the item's own
# href, so ``asset_href`` is what this can honestly record. It is also the
# value the duplicate-source guard keys on today, so re-keying that guard to
# origin_uri (ADR-002 Decision 6) leaves its behaviour unchanged on
# existing rows.
_STAC_BACKFILL = """
    UPDATE catalog.datasets AS d
    SET origin_uri = d.source_url,
        origin_ref = jsonb_build_object(
            'kind', 'stac', 'asset_href', d.source_url
        )
    WHERE d.source_format = 'stac'
      AND d.source_url ~* '^https?://'
"""

# Registered PostGIS tables: no source_format, referenced in place.
#
# Both record types registration can produce are covered. `create_dataset`
# assigns 'table' when the source has no geometry and 'vector_dataset'
# otherwise, and `register_existing_table` stamps the origin either way, so
# restricting this to 'vector_dataset' would leave registered non-spatial
# tables as the only rows whose pointer depends on whether they were
# registered before or after this migration. ADR-002's predicate names the
# common case rather than an exclusion (widened deliberately, #1218 review).
#
# VRT datasets also store a null source_format (they have no single source
# file), and the record_type predicate is still what keeps them out: a VRT is
# composed from other datasets and has no origin of its own.
#
# RESOLUTION REQUIRES BOTH: exactly one physical relation carrying the name
# (the HAVING count(*) = 1 above) AND exactly one catalog row claiming it (the
# NOT EXISTS below). Ambiguity on either side leaves the row NULL.
#
# The two guards are NOT redundant and neither can be simplified away
# (fix #1218 review rounds 1 and 2):
#
#   - Two physical relations, one claimant: the round-1 finding. The catalog
#     side sees nothing wrong; only the physical count catches it.
#   - One physical relation, two claimants: the round-2 finding. Two tenants
#     both registered `parcels` and one tenant's table was later dropped, so
#     the physical count is a clean 1 and BOTH catalog rows would otherwise
#     bind to the surviving tenant's schema. One of them is an orphan holding
#     a pointer into another tenant's data.
#
# The `IS NOT NULL` predicate also skips a catalog row whose physical table is
# gone entirely, rather than building a pointer from a NULL schema.
_POSTGIS_BACKFILL = f"""
    UPDATE catalog.datasets AS d
    SET origin_uri = 'postgis://' || ({_DATA_SCHEMA_SQL})
                     || '.' || d.table_name,
        origin_ref = jsonb_build_object(
            'kind', 'postgis',
            'table_name', ({_DATA_SCHEMA_SQL}) || '.' || d.table_name
        )
    FROM catalog.records AS r
    WHERE r.id = d.record_id
      AND d.source_format IS NULL
      AND r.record_type IN ('vector_dataset', 'table')
      AND ({_DATA_SCHEMA_SQL}) IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM catalog.datasets AS d2
          JOIN catalog.records AS r2 ON r2.id = d2.record_id
          WHERE d2.table_name = d.table_name
            AND d2.id <> d.id
            AND d2.source_format IS NULL
            AND r2.record_type IN ('vector_dataset', 'table')
      )
"""

# Uploaded files have no remote origin, so origin_uri stays NULL. The hash
# comes from the newest DatasetVersion that has one; rows ingested before
# hashing existed simply omit the key.
_UPLOAD_BACKFILL = f"""
    UPDATE catalog.datasets AS d
    SET origin_ref = jsonb_strip_nulls(
            jsonb_build_object(
                'kind', 'upload',
                'filename', d.source_filename,
                'file_hash', (
                    SELECT dv.file_hash
                    FROM catalog.dataset_versions AS dv
                    WHERE dv.dataset_id = d.id
                      AND dv.file_hash IS NOT NULL
                    ORDER BY dv.version_number DESC
                    LIMIT 1
                )
            )
        )
    WHERE d.source_format IN ({_quoted(_UPLOAD_FORMATS)})
"""

# Newest version upload where the dataset has version history, else creation.
# A re-uploaded dataset was genuinely refreshed after its import, so the
# version table is the better answer wherever it has rows; records.created_at
# is the floor for datasets that were never re-uploaded.
_LAST_REFRESHED_BACKFILL = """
    UPDATE catalog.datasets AS d
    SET last_refreshed_at = COALESCE(
        (
            SELECT max(dv.uploaded_at)
            FROM catalog.dataset_versions AS dv
            WHERE dv.dataset_id = d.id
        ),
        r.created_at
    )
    FROM catalog.records AS r
    WHERE r.id = d.record_id
"""


def backfill_statements() -> list[sa.TextClause]:
    """The backfill, in order, as executable statements.

    Exposed rather than inlined into ``upgrade()`` so
    ``tests/test_dataset_source_state.py`` can run the REAL statements against
    pre-migration-shaped rows. A test that re-copied the SQL would prove only
    that the copy works.
    """
    return [
        sa.text(_SERVICE_BACKFILL),
        sa.text(_STAC_BACKFILL),
        sa.text(_POSTGIS_BACKFILL),
        sa.text(_UPLOAD_BACKFILL),
        sa.text(_LAST_REFRESHED_BACKFILL),
    ]


def downgrade() -> None:
    op.drop_index("ix_datasets_origin_uri", table_name="datasets", schema="catalog")
    op.drop_constraint(
        "chk_datasets_schema_drift_status",
        "datasets",
        schema="catalog",
        type_="check",
    )
    op.drop_constraint(
        "chk_datasets_source_health", "datasets", schema="catalog", type_="check"
    )
    for column in (
        "schema_drift_status",
        "source_health_detail",
        "source_health",
        "last_checked_at",
        "last_refreshed_at",
        "origin_ref",
        "origin_uri",
    ):
        op.drop_column("datasets", column, schema="catalog")
