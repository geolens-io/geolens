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

    # The authority pass. See purge_credential_bearing_pointers: the SQL above
    # is a pre-filter, this is what actually decides.
    purge_credential_bearing_pointers(op.get_bind())

    # last_checked_at, source_health, source_health_detail and
    # schema_drift_status are left NULL on every row on purpose: GeoLens has
    # never contacted an origin, so any value here would be invented.


def _quoted(values: Sequence[str]) -> str:
    """SQL literal list. Every value is a hard-coded constant in this file."""
    return ", ".join(f"'{value}'" for value in values)


def _url_is_safe(expr: str) -> str:
    """SQL predicate mirroring ``has_url_credentials`` for one URL column.

    fix(#1218 review r5): a legacy service URL can carry ``user:pass@`` or a
    ``?token=`` parameter. Those predate the submission-time gate
    (``_validate_service_url`` in ``modules/catalog/sources/schemas.py:91``,
    which refuses both on ``ProbeRequest`` and ``ServicePreviewRequest``), so a
    NEW ingest cannot persist one, but an OLD row can still hold it. Copying it
    into ``origin_uri``/``origin_ref`` would be strictly worse than leaving it
    in ``source_url``: those two columns are read-only on ``DatasetResponse``,
    so an operator who spots the secret cannot edit it away.

    The parameter names come from ``SENSITIVE_QUERY_PARAMS`` itself rather than
    a transcription, so this cannot drift from the runtime rule. Importing app
    code here follows ``alembic/env.py``, which already imports
    ``app.core.config`` and ``app.core.db``.

    fix(#1218 review r7): this predicate is a PRE-FILTER, not the authority.
    ``purge_credential_bearing_pointers`` runs the real ``has_url_credentials``
    over everything the backfill populated and clears any offender it finds,
    so completeness of the arms below is no longer a correctness requirement.
    That restructure exists because three review rounds each reported one
    spelling of the same class (``?token=``, ``?%74oken=``, ``?+token+=``):
    a regex mirror has to be re-proven complete every time ``parse_qsl`` grows
    a normalization, and nothing fails loudly when it stops being complete.

    What the arms buy, now that they are not load-bearing, is cheapness: the
    common shapes never reach the Python pass at all. They cover the literal
    names, plus the two encodings that turn a harmless-looking name into a
    sensitive one — percent-escapes and ``+`` (which ``parse_qsl`` decodes to a
    space that ``_is_sensitive_query_param`` then strips). Whitespace rides
    along in the same character class for free. Every other normalization,
    and every shape a pattern cannot express — a fullwidth ``＠`` that NFKC
    turns into a delimiter, a malformed authority ``urlsplit`` refuses — is
    the authority pass's job.

    VALUES keep their encoding rights: the name segment is bounded by the
    FIRST ``=`` of its pair, so ``?typename=ns%3Aroads`` and ``?q=a+b`` both
    still backfill. That distinction is the whole reason for the ``[^=&#]*``
    classes rather than a bare character test.

    Case is handled exactly rather than conservatively: the alternation runs
    case-insensitively (``!~*``), so ``?TOKEN=`` matches without refusing the
    ordinary uppercase parameters real OGC services use.
    """
    from app.core.url_redaction import SENSITIVE_QUERY_PARAMS

    # Every name is [a-z0-9_-], so no regex metacharacter needs escaping.
    alternation = "|".join(sorted(SENSITIVE_QUERY_PARAMS))
    return f"""(
        {expr} ~* '^https?://'
        AND {expr} !~ '^[a-zA-Z][a-zA-Z0-9+.-]*://[^/?#]*@'
        AND {expr} !~* '[?&]({alternation})='
        AND {expr} !~ '[?&][^=&#]*[%+[:space:]][^=&#]*='
    )"""


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
#
# THE INVARIANT (fix #1218 review r4): `origin_ref.url` is the service BASE for
# every service_type, `layer_id` is the service-native layer identifier, and
# the url NEVER embeds the layer.
#
# `datasets.source_url` cannot supply that base directly. The probe puts the
# layer NAME in layer_id for WFS and OGC API (sources/probe.py:73), and ingest
# persists `<base>/<layer_id>` onto the dataset (tasks_vector.py:997-999), so
# the stored column is enriched and reading it would have produced
# url=<base>/topp:roads beside layer_id=topp:roads. The runtime write site is
# already correct — it stores the un-enriched ingest argument
# (tasks_vector.py:1037) — so this was a backfill-only divergence and the two
# now agree.
#
# The base is therefore RECOVERED from the ingest job's own source_url, which
# is the normalized value the operator submitted (sources/router.py:548), not
# reconstructed by string surgery. ArcGIS keeps a derivation as fallback
# because its suffix is provably numeric. For WFS/OGC API with no surviving
# job the base is NOT derivable: stripping needs the layer name, which is the
# thing that went missing. Those rows get NEITHER url nor layer_id rather than
# a wrong base, which would violate the invariant above. `origin_uri` still
# holds the full enriched URL, so an operator can re-identify the layer from
# it by hand.

# The latest complete ingest job for this dataset. Both columns below are read
# from THIS row, with an id tiebreaker so two separate scalar subqueries can
# never resolve to different jobs on identical created_at values.
_LATEST_JOB = """
    FROM catalog.ingest_jobs AS j
    WHERE j.dataset_id = d.id
      AND j.status = 'complete'
    ORDER BY j.created_at DESC, j.id DESC
    LIMIT 1
"""

_SERVICE_BACKFILL = f"""
    UPDATE catalog.datasets AS d
    SET origin_uri = d.source_url,
        origin_ref = jsonb_strip_nulls(
            jsonb_build_object(
                'kind', 'service',
                'service_type', d.source_format,
                'url', COALESCE(
                    (SELECT CASE WHEN {_url_is_safe("j.source_url")}
                                 THEN j.source_url END {_LATEST_JOB}),
                    CASE
                        WHEN d.source_format = 'arcgis_featureserver'
                             AND d.source_url ~ '/[0-9]+$'
                        THEN regexp_replace(d.source_url, '/[0-9]+$', '')
                        WHEN d.source_format = 'arcgis_featureserver'
                        THEN d.source_url
                        ELSE NULL
                    END
                ),
                'layer_id', CASE
                    WHEN d.source_format = 'arcgis_featureserver'
                         AND d.source_url ~ '/[0-9]+$'
                    THEN substring(d.source_url from '/([0-9]+)$')
                    WHEN d.source_format IN ('wfs', 'ogcapi_features')
                    THEN (SELECT j.source_layer {_LATEST_JOB})
                    ELSE NULL
                END
            )
        )
    WHERE d.source_format IN ({_quoted(_SERVICE_FORMATS)})
      AND {_url_is_safe("d.source_url")}
"""

# STAC datasets point at the referenced asset. ``stac_router`` stores the
# item's data-asset href in source_url and never captures the item's own
# href, so ``asset_href`` is what this can honestly record. It is also the
# value the duplicate-source guard keys on today, so re-keying that guard to
# origin_uri (ADR-002 Decision 6) leaves its behaviour unchanged on
# existing rows.
_STAC_BACKFILL = f"""
    UPDATE catalog.datasets AS d
    SET origin_uri = d.source_url,
        origin_ref = jsonb_build_object(
            'kind', 'stac', 'asset_href', d.source_url
        )
    WHERE d.source_format = 'stac'
      AND {_url_is_safe("d.source_url")}
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


# Keys in origin_ref whose value is a URL. Kept beside the pass that reads
# them so a new URL-bearing key in ORIGIN_REF_KEYS is one edit away from being
# checked rather than silently unchecked.
_URL_REF_KEYS = ("url", "asset_href", "item_href")


def purge_credential_bearing_pointers(bind) -> int:
    """Re-check every backfilled pointer with the REAL credential rule.

    fix(#1218 review r7): this is the authority, and the SQL predicate is a
    pre-filter in front of it. Three review rounds each reported one spelling
    of a single class (``?token=``, then ``?%74oken=``, then ``?+token+=``),
    which is the signal that enumerating spellings in SQL is the wrong shape:
    a regex mirror of ``has_url_credentials`` has to be re-proven complete
    every time ``parse_qsl`` grows a normalization, and nothing fails loudly
    when it stops being complete.

    Running the real function closes the class by construction. Anything the
    SQL misses is caught here, including shapes a regex cannot reasonably
    express: ``has_url_credentials`` returns True when ``urlsplit`` REFUSES an
    authority, so a fullwidth ``＠`` that NFKC turns into a delimiter, or a
    malformed ``https://[::1``, are both credential-bearing to Python and
    invisible to any ASCII pattern.

    Both pointer columns are cleared together on an offender. Leaving a
    half-populated ref would be the "wrong pointer is worse than none" failure
    this migration avoids everywhere else; the origin still classifies from
    ``source_format``, so only the pointer is lost.

    Row counts make this ordinary: the scan touches datasets carrying an
    origin at all, and only those with a URL-shaped field are inspected.
    Returns the number of rows cleared, so a caller (and the test) can assert
    on it rather than infer.
    """
    from app.core.url_redaction import has_url_credentials

    rows = bind.execute(
        sa.text(
            "SELECT id, origin_uri, origin_ref FROM catalog.datasets "
            "WHERE origin_uri IS NOT NULL OR origin_ref IS NOT NULL"
        )
    ).all()

    offenders = []
    for row in rows:
        candidates = []
        if isinstance(row.origin_uri, str):
            candidates.append(row.origin_uri)
        if isinstance(row.origin_ref, dict):
            candidates.extend(
                value
                for key in _URL_REF_KEYS
                if isinstance(value := row.origin_ref.get(key), str)
            )
        if any(has_url_credentials(candidate) for candidate in candidates):
            offenders.append(row.id)

    if offenders:
        bind.execute(
            sa.text(
                "UPDATE catalog.datasets "
                "SET origin_uri = NULL, origin_ref = NULL "
                "WHERE id = ANY(:ids)"
            ).bindparams(sa.bindparam("ids", value=offenders))
        )
    return len(offenders)
