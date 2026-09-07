import uuid
from datetime import date, datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('public', 'private', 'internal', 'restricted')",
            name="chk_records_visibility",
        ),
        CheckConstraint(
            "update_frequency IS NULL OR update_frequency IN ("
            "'continual', 'daily', 'weekly', 'monthly', 'quarterly', "
            "'biannually', 'annually', 'asNeeded', 'irregular', 'notPlanned', 'unknown')",
            name="chk_records_update_frequency",
        ),
        CheckConstraint(
            "sensitivity_classification IS NULL OR sensitivity_classification IN ("
            "'public', 'internal', 'confidential', 'restricted')",
            name="chk_records_sensitivity",
        ),
        CheckConstraint(
            "record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', 'map', 'service', 'collection', 'table')",
            name="chk_records_record_type",
        ),
        CheckConstraint(
            "language IS NULL OR language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="chk_records_language_tag",
        ),
        CheckConstraint(
            "temporal_start IS NULL OR temporal_end IS NULL OR temporal_start <= temporal_end",
            name="chk_temporal_ordering",
        ),
        # fix(#892): typmod widened from POLYGON to generic Geometry so a
        # seam-crossing extent can be a two-ring MULTIPOLYGON; this constraint
        # keeps the type guard, deliberately narrow (caught a real POINT 500).
        CheckConstraint(
            "spatial_extent IS NULL OR "
            "GeometryType(spatial_extent) IN ('POLYGON', 'MULTIPOLYGON')",
            name="chk_records_spatial_extent_type",
        ),
        # fix(#892): known ceiling -- a seam-crossing MULTIPOLYGON's GiST bbox
        # is -180..180, degrading this index to a full scan for those rows
        # only; make_bbox_filter()'s ST_Intersects recheck keeps results right.
        Index(
            "idx_records_spatial_extent",
            "spatial_extent",
            postgresql_using="gist",
        ),
        Index("idx_records_created_at_desc", "created_at", postgresql_using="btree"),
        Index(
            "idx_records_source_organization",
            "source_organization",
            postgresql_where="source_organization IS NOT NULL",
        ),
        Index(
            "idx_records_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "idx_records_visibility_status_creator",
            "visibility",
            "record_status",
            "created_by",
        ),
        Index(
            "ix_records_created_by",
            "created_by",
            postgresql_where=text("created_by IS NOT NULL"),
        ),
        Index(
            "ix_records_updated_by",
            "updated_by",
            postgresql_where=text("updated_by IS NOT NULL"),
        ),
        # Migration 0010 (H-07) is the DDL source of truth; declared here so
        # alembic check sees them. postgresql_ops keeps the operator class
        # outside the expression so alembic's index compare can match it.
        Index(
            "ix_records_title_trgm",
            text("lower(catalog.immutable_unaccent(title))"),
            postgresql_using="gin",
            postgresql_ops={"lower(catalog.immutable_unaccent(title))": "gin_trgm_ops"},
        ),
        Index(
            "ix_records_summary_trgm",
            text("lower(catalog.immutable_unaccent(coalesce(summary, '')))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(catalog.immutable_unaccent(coalesce(summary, '')))": "gin_trgm_ops"
            },
        ),
        # D-1: functional GIN on the simple-regconfig tsvector for non-English
        # search; migration 0001_baseline is the DDL source of truth,
        # declared here so alembic check doesn't propose dropping it.
        #
        # The text() must byte-match what SQLAlchemy *reflects* for this
        # index (what autogenerate compares) -- NOT pg_get_indexdef output
        # and NOT the migration's raw SQL; they differ in canonicalization.
        # To regenerate: run `alembic check` and copy the expression from the
        # diff error. No postgresql_ops -- this index has no operator class.
        Index(
            "ix_records_simple_search_vector",
            text(
                "to_tsvector('simple'::regconfig, (((((COALESCE(title, ''::text) || ' '::text) || COALESCE(summary, ''::text)) || ' '::text) || COALESCE(lineage_summary, ''::text)) || ' '::text) || COALESCE(catalog.immutable_text_array_join(theme_category, ' '::text), ''::text))"
            ),
            postgresql_using="gin",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(Text, nullable=True)
    # feat(#1472): credit line a source's terms require at render time.
    # Distinct from license (the terms) and source_organization (a facet).
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Entity that published/provided the data (used in facets/search).
    source_organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Entity that owns the data (governance/provenance; not searched).
    owner_org: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    record_status: Mapped[str] = mapped_column(String(20), default="draft")
    record_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="vector_dataset"
    )
    language: Mapped[str | None] = mapped_column(
        String(35), default="en", server_default="en"
    )
    spatial_extent: Mapped[str | None] = mapped_column(
        # spatial_index=False: declared explicitly below as
        # idx_records_spatial_extent, else GeoAlchemy2 auto-creates a
        # duplicate (breaks create_all()).
        #
        # fix(#892): plain Geometry (not POLYGON) so a seam-crossing extent
        # can be a two-ring MULTIPOLYGON per RFC 7946 §5.2;
        # chk_records_spatial_extent_type below still rejects a point/line.
        Geometry(srid=4326, spatial_index=False),
        nullable=True,
    )
    temporal_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ISO governance fields
    lineage_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    usage_constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    sensitivity_classification: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    theme_category: Mapped[list | None] = mapped_column(
        MutableList.as_mutable(ARRAY(Text)), nullable=True
    )

    # Search
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english'::regconfig, coalesce(summary, '')), 'B') || "
            "setweight(to_tsvector('english'::regconfig, coalesce(lineage_summary, '')), 'C') || "
            "setweight(to_tsvector('english'::regconfig, coalesce(catalog.immutable_array_camel_to_spaced(theme_category, ' '), '')), 'B')",
            persisted=True,
        ),
        nullable=True,
    )

    # feat(#765): provenance for a record produced FROM another record --
    # {dataset_id, operation, params, created_at}. Deliberately not an FK:
    # the reference must survive the source dataset being deleted.
    derived_from: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # TSEAM-01 (Phase 1207): dormant tenant_id — nullable, no FK enforcement.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    dataset: Mapped["Dataset | None"] = relationship(
        "Dataset",
        back_populates="record",
        uselist=False,
        lazy="select",
        passive_deletes=True,
    )
    contacts: Mapped[list["RecordContact"]] = relationship(
        "RecordContact",
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
        order_by="RecordContact.sort_order",
    )
    keywords: Mapped[list["RecordKeyword"]] = relationship(
        "RecordKeyword",
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    distributions: Mapped[list["RecordDistribution"]] = relationship(
        "RecordDistribution",
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    translations: Mapped[list["RecordTranslation"]] = relationship(
        "RecordTranslation",
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="RecordTranslation.language",
    )


class RecordTranslation(Base):
    """Localized title/summary variants for a catalog record.

    Primary title/summary/language stay on ``Record``; this table holds
    alternate representations selected during language negotiation.
    """

    __tablename__ = "record_translations"
    __table_args__ = (
        CheckConstraint(
            "language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="chk_record_translations_language_tag",
        ),
        Index(
            "uq_record_translations_record_language_ci",
            "record_id",
            text("lower(language)"),
            unique=True,
        ),
        Index(
            "ix_record_translations_simple_search_vector",
            text(
                "to_tsvector('simple'::regconfig, (COALESCE(title, ''::text) || ' '::text) || COALESCE(summary, ''::text))"
            ),
            postgresql_using="gin",
        ),
        Index(
            "ix_record_translations_title_trgm",
            text("lower(catalog.immutable_unaccent(title))"),
            postgresql_using="gin",
            postgresql_ops={"lower(catalog.immutable_unaccent(title))": "gin_trgm_ops"},
        ),
        Index(
            "ix_record_translations_summary_trgm",
            text("lower(catalog.immutable_unaccent(coalesce(summary, '')))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(catalog.immutable_unaccent(coalesce(summary, '')))": "gin_trgm_ops"
            },
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    record: Mapped["Record"] = relationship("Record", back_populates="translations")


def _stamp_published_at(mapper, connection, target: "Record") -> None:
    """fix(#430): stamp published_at when a record is INSERTED as published.

    No ingest path wrote published_at, so uploads showed published with
    published_at=NULL. This hook covers every creation site centrally; the
    draft->published transition path (_apply_record_status_change) already
    stamps it, so no before_update hook is needed.
    """
    if target.record_status == "published" and target.published_at is None:
        target.published_at = datetime.now(timezone.utc)


event.listen(Record, "before_insert", _stamp_published_at)


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            # fix(#430): 'GEOMETRY' = generic mixed-geometry sentinel stored
            # by create_empty_dataset. Migration 0011 is the source of truth.
            "geometry_type IS NULL OR UPPER(geometry_type) IN ("
            "'POINT', 'LINESTRING', 'POLYGON', "
            "'MULTIPOINT', 'MULTILINESTRING', 'MULTIPOLYGON', "
            "'GEOMETRYCOLLECTION', 'GEOMETRY')",
            name="chk_datasets_geometry_type",
        ),
        CheckConstraint(
            # fix(#541): allow-list of accepted source formats; a .kmz
            # normalizes to 'kml', a zipped .gdb to 'fgdb' (see
            # ingest/source_format.py). Migration 0053 is the source of truth.
            "source_format IS NULL OR source_format IN ("
            "'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml', "
            "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff', "
            "'ogcapi_features', 'stac', 'parquet', 'json', 'xlsx', 'xls', "
            "'fgb')",
            name="chk_datasets_source_format",
        ),
        CheckConstraint(
            "srid IS NULL OR srid > 0",
            name="chk_datasets_srid_positive",
        ),
        CheckConstraint(
            "original_srid IS NULL OR original_srid > 0",
            name="chk_datasets_original_srid_positive",
        ),
        # feat(#1218): NULL is the only spelling of "never determined" --
        # 'unknown' is deliberately out of both value sets; the API projects
        # NULL to "unknown" at the response boundary. Migration 0036 is truth.
        CheckConstraint(
            "source_health IS NULL OR source_health IN "
            "('healthy', 'missing', 'inaccessible')",
            name="chk_datasets_source_health",
        ),
        CheckConstraint(
            "schema_drift_status IS NULL OR schema_drift_status IN ('none', 'drifted')",
            name="chk_datasets_schema_drift_status",
        ),
        # feat(#1218): backs the duplicate-source guard (ADR-002 Decision 6,
        # re-keyed from source_url to origin_uri). Partial: most rows NULL.
        Index(
            "ix_datasets_origin_uri",
            "origin_uri",
            postgresql_where=text("origin_uri IS NOT NULL"),
        ),
        # perf(#1324): backs origin_ref-keyed duplicate-source guards in
        # sources/router.py and stac_router.py. Migration 0040 is the DDL
        # source of truth.
        #
        # IS NOT NULL on the indexed expression, not source_format, keeps
        # the partial predicate provable under a generic query plan.
        #
        # ::text casts and inner parens are what postgres reflects for a
        # ->>' expression index -- see ix_records_title_trgm for the trap.
        #
        # USING hash, which cannot be composite (and a btree's ~2704-byte tuple
        # ceiling couldn't hold url plus layer_id anyway), so layer_id stays a
        # residual Filter, not indexed.
        Index(
            "ix_datasets_origin_ref_url",
            text("(origin_ref ->> 'url'::text)"),
            postgresql_using="hash",
            postgresql_where=text("(origin_ref ->> 'url'::text) IS NOT NULL"),
        ),
        Index(
            "ix_datasets_origin_ref_asset_href",
            text("(origin_ref ->> 'asset_href'::text)"),
            postgresql_using="hash",
            postgresql_where=text("(origin_ref ->> 'asset_href'::text) IS NOT NULL"),
        ),
        # perf(#1324): required for the two indexes above to be used at all
        # -- both guards query `(origin_ref match) OR (origin_ref incomplete
        # AND source_url = ...)`, and postgres only bitmap-scans an OR when
        # every disjunct has an index path. See migration 0040 for EXPLAIN.
        Index(
            "ix_datasets_source_url",
            "source_url",
            postgresql_using="hash",
            postgresql_where=text("source_url IS NOT NULL"),
        ),
        Index(
            "uq_datasets_table_name_global",
            "table_name",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_datasets_table_name_tenant",
            "tenant_id",
            "table_name",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        {"schema": "catalog"},
    )

    # Identity
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Auto-extracted metadata
    srid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geometry_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    feature_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_info: Mapped[list | None] = mapped_column(
        MutableList.as_mutable(JSONB), nullable=True
    )
    sample_values: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    quality_detail: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    quality_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_3d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    n_dims: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    z_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    quicklook_256_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source info
    source_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_srid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Source origin & refresh state (ADR-002, #1218). System-managed: none
    # is in _DATASET_FIELD_MAP, so metadata PATCH can't reach them.
    # source_url stays user-editable prose beside origin_uri (machine
    # pointer). origin_ref writes go through the key allowlist in
    # app/platform/dataset_origin.py, keeping credentials/PostGIS out of v1.
    origin_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    origin_ref: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    # last_refreshed_at = last committed successful swap, NOT last attempt.
    # last_checked_at = "we contacted the origin at all" (success or
    # failure). Deliberately no last_verified_at (ADR-002 Decision 3).
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Vocabulary reused from the VRT member probe (router_vrt.py) so one legend
    # renders across VRT members and standalone origins.
    source_health: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Short, redacted reason. Never a raw exception, a URL carrying
    # query-string credentials, or a GDAL command line.
    source_health_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Persisted rather than derived — unlike origin classification and
    # staleness — because the pre-refresh schema is gone once the swap
    # commits, so drift has no live inputs to recompute from.
    schema_drift_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # TSEAM-01 (Phase 1207): dormant tenant_id — nullable, no FK enforcement.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Version tracking
    current_version: Mapped[int] = mapped_column(Integer, server_default="1", default=1)

    # fix(#525): URL-keyed tile cache-buster. current_version only bumps on
    # reupload, so non-versioning content mutations (feature edits, column
    # DDL) bump this instead, rolling CDN/browser caches the Valkey purge
    # can't reach.
    tile_cache_version: Mapped[int] = mapped_column(
        Integer, server_default="1", default=1
    )

    # Per-dataset tile cache TTL override (null = use global settings.tile_cache_ttl)
    tile_cache_ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Per-dataset tile column allowlist.
    # NULL  -> per-zoom defaults (no attrs z<10, all attrs z>=10).
    # []    -> no attribute columns at any zoom (geometry-only tiles).
    # [...] -> admin-curated allowlist; only these columns flow into MVT.
    tile_columns: Mapped[list[str] | None] = mapped_column(
        ARRAY(String()), nullable=True
    )

    # Relationships
    record: Mapped["Record"] = relationship(
        "Record", back_populates="dataset", lazy="joined"
    )
    attributes: Mapped[list["AttributeMetadata"]] = relationship(
        "AttributeMetadata",
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    def bump_tile_cache_version(self) -> None:
        """Roll the `_v=` tile-URL cache-buster after a tile-content mutation.

        Call in the same transaction as the change; the post-commit Valkey
        purge cannot reach CDN/browser caches keyed on the tile URL.

        Writes an ABSOLUTE value off this instance -- correct only if the
        caller still holds the lock it loaded this row under. A request
        handler that loads before it waits must use
        ``bump_tile_cache_version_on`` (platform/catalog_locks) instead.
        """
        self.tile_cache_version = (self.tile_cache_version or 1) + 1


class RecordContact(Base):
    __tablename__ = "record_contacts"
    __table_args__ = (
        CheckConstraint(
            "role IN ('resourceProvider', 'custodian', 'owner', 'user', 'distributor', "
            "'originator', 'pointOfContact', 'principalInvestigator', 'processor', "
            "'publisher', 'author', 'sponsor', 'coAuthor', 'collaborator', 'editor', "
            "'mediator', 'rightsHolder', 'contributor', 'funder', 'stakeholder')",
            name="chk_contact_role",
        ),
        # Functional GIN over (name, organization) tsvector for FTS; mirrors
        # the literal CREATE INDEX in the baseline migration.
        Index(
            "ix_record_contacts_fts",
            text(
                "to_tsvector('english'::regconfig, "
                "(COALESCE(name, ''::text) || ' '::text) || "
                "COALESCE(organization, ''::text))"
            ),
            postgresql_using="gin",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0)

    record: Mapped["Record"] = relationship("Record", back_populates="contacts")


class RecordKeyword(Base):
    __tablename__ = "record_keywords"
    __table_args__ = (
        CheckConstraint(
            "keyword_type IN ('discipline', 'place', 'stratum', 'temporal', 'theme', "
            "'dataCentre', 'featureType', 'instrument', 'platform', 'process', "
            "'product', 'project', 'service', 'subTopicCategory', 'taxon')",
            name="chk_keyword_type",
        ),
        # Functional GIN for keyword full-text lookup
        Index(
            "ix_record_keywords_fts",
            text("to_tsvector('english'::regconfig, keyword)"),
            postgresql_using="gin",
        ),
        # Trigram GIN added in migration 0010 (H-07) — declared on the model
        # so alembic check sees it; the migration is the source of truth.
        Index(
            "ix_record_keywords_keyword_trgm",
            text("lower(catalog.immutable_unaccent(keyword))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(catalog.immutable_unaccent(keyword))": "gin_trgm_ops"
            },
        ),
        # Functional UNIQUE: NULL vocabulary_uri treated as empty string so
        # NULL rows still collide (a plain UniqueConstraint wouldn't catch it).
        Index(
            "uq_record_keyword",
            "record_id",
            "keyword",
            "keyword_type",
            text("COALESCE(vocabulary_uri, ''::text)"),
            unique=True,
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
    )
    # record_id is covered by the composite uq_record_keyword index above,
    # so a separate single-column FK index would be redundant.
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    vocabulary_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="theme", default="theme"
    )

    record: Mapped["Record"] = relationship("Record", back_populates="keywords")


class RecordDistribution(Base):
    __tablename__ = "record_distributions"
    __table_args__ = (
        UniqueConstraint(
            "record_id",
            "distribution_type",
            "format",
            "url",
            name="uq_record_distribution",
        ),
        CheckConstraint(
            "distribution_type IN ('download', 'api', 'ogcService', 'ogc_features', "
            "'webApp', 'offlineAccess', 'vector_tiles')",
            name="chk_distribution_type",
        ),
        # fix(#1383): at most one primary distribution per record. Write
        # paths demote the incumbent, but the API isn't the only writer and
        # `is_primary` is read as "THE primary" downstream. Partial index.
        Index(
            "uq_record_distribution_primary",
            "record_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distribution_type: Mapped[str] = mapped_column(String(30), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    auto_generated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    record: Mapped["Record"] = relationship("Record", back_populates="distributions")


class AttributeMetadata(Base):
    __tablename__ = "attribute_metadata"
    __table_args__ = (
        UniqueConstraint("dataset_id", "field_name", name="uq_attribute_metadata"),
        CheckConstraint(
            "semantic_role IS NULL OR semantic_role IN ("
            "'geometry', 'identifier', 'measure', 'temporal', "
            "'categorical', 'category', 'label', 'foreign_key', 'other')",
            name="chk_semantic_role",
        ),
        CheckConstraint(
            "domain_type IS NULL OR domain_type IN ("
            "'continuous', 'discrete', 'categorical', 'coded', 'codedValue', "
            "'boolean', 'text', 'date', 'temporal', 'geometry', 'range')",
            name="chk_domain_type",
        ),
        Index(
            "idx_attribute_metadata_dataset_current",
            "dataset_id",
            "is_current",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    units: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    semantic_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    example_values: Mapped[list | None] = mapped_column(
        MutableList.as_mutable(JSONB), nullable=True
    )
    ordinal_position: Mapped[int | None] = mapped_column(nullable=True)
    is_nullable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    user_modified_fields: Mapped[list] = mapped_column(
        MutableList.as_mutable(ARRAY(Text)),
        nullable=False,
        default=list,
        server_default="{}",
    )

    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="attributes")


class DatasetGrant(Base):
    __tablename__ = "dataset_grants"
    __table_args__ = (
        # T-3: trailing composite-PK FK; covering index added in migration 0001_baseline.
        Index("ix_dataset_grants_role_id", "role_id"),
        {"schema": "catalog"},
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.roles.id", ondelete="CASCADE"), primary_key=True
    )


class DatasetRelationship(Base):
    __tablename__ = "dataset_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_dataset_id",
            "target_dataset_id",
            "source_column",
            name="uq_dataset_relationship",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    # FK targets records.id, not datasets.id: relationships are defined at
    # the record level, and dataset.record_id == record.id (1:1 FK).
    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
    )
    target_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_column: Mapped[str] = mapped_column(String(100), nullable=False)
    target_column: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="gid"
    )
    relationship_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="foreign_key"
    )
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RetiredTableName(Base):
    """A physical table name that must never be handed out again.

    fix(#1443): ``generate_table_name`` collides only against live rows, so
    deleting a dataset used to hand its table name to the next dataset with
    that title. The tile router caches table_name -> dataset metadata and
    authorizes off that snapshot, so a stale cache entry could then leak the
    successor's rows under the deleted dataset's visibility. Retiring the
    name removes the precondition.

    Rows are kept forever -- an expiry would reopen the window on exactly
    the names still likely to be cached.
    """

    __tablename__ = "retired_table_names"
    __table_args__ = (
        Index("ix_retired_table_names_table_name", "table_name"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # TSEAM-01 (Phase 1207): dormant tenant_id — nullable, no FK enforcement.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Diagnostic breadcrumb, not a foreign key — the dataset it names is
    # deleted in the transaction that writes this row.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # fix(#1456): relation identity + owner id, captured inside the delete
    # transaction since both sources die in it. Nothing reads them yet --
    # they exist for a later ownership-aware re-registration.
    #
    # BIGINT: pg_class oid is unsigned 32-bit and identifies the relation
    # only within one cluster lifetime (pg_dump/restore doesn't preserve
    # oids). previous_owner_id is the durable half.
    relation_oid: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Not a foreign key: retain-forever means a CASCADE FK would erase
    # tombstones on user deletion and re-arm GH-1443 for their freed names.
    previous_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    retired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DetachedRelation(Base):
    """A relation GeoLens released its claim on while it was still standing.

    fix(#1456): :class:`RetiredTableName` only covers deletes that FREE a
    name. A detach leaves the table standing and writes no tombstone, so if
    the operator later drops it, the name goes free unrecorded. Separate
    table rather than a flag on retired_table_names, because that table's
    API is set membership (a name in it is never handed out again) and a
    still-standing relation is not a prohibition. Nothing reads this yet.
    """

    __tablename__ = "detached_relations"
    __table_args__ = (
        Index("ix_detached_relations_table_name", "table_name"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # TSEAM-01 (Phase 1207): dormant tenant_id — nullable, no FK enforcement.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Neither id is a foreign key: the dataset is deleted in the transaction
    # that writes this row, and an FK to users would let a retain-forever
    # row block a user deletion.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Nullable although the only write site reaches it with a non-null oid: a
    # NOT NULL here could turn a surprise into a failed DELETE.
    relation_oid: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    detached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
