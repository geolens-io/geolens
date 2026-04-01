import uuid
from datetime import date, datetime

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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('public', 'private', 'internal', 'restricted')",
            name="chk_records_visibility",
        ),
        CheckConstraint(
            "record_status IN ('draft', 'ready', 'internal', 'published')",
            name="chk_records_record_status",
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
            "temporal_start IS NULL OR temporal_end IS NULL OR temporal_start <= temporal_end",
            name="chk_temporal_ordering",
        ),
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
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(Text, nullable=True)
    # source_organization: the entity that published or provided the data (used in facets/search)
    source_organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    # owner_org: the entity that owns the data (governance/provenance, not used in search)
    owner_org: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    record_status: Mapped[str] = mapped_column(String(20), default="draft")
    record_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="vector_dataset"
    )
    language: Mapped[str | None] = mapped_column(String(10), default="en")
    spatial_extent: Mapped[str | None] = mapped_column(
        Geometry("POLYGON", srid=4326), nullable=True
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


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            "quality_score_numeric IS NULL OR "
            "(quality_score_numeric >= 0 AND quality_score_numeric <= 1)",
            name="chk_quality_score_range",
        ),
        CheckConstraint(
            "geometry_type IS NULL OR UPPER(geometry_type) IN ("
            "'POINT', 'LINESTRING', 'POLYGON', "
            "'MULTIPOINT', 'MULTILINESTRING', 'MULTIPOLYGON', "
            "'GEOMETRYCOLLECTION')",
            name="chk_datasets_geometry_type",
        ),
        CheckConstraint(
            "source_format IS NULL OR source_format IN ("
            "'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml', "
            "'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff')",
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
    table_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

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
    quality_score_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    quicklook_256_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source info
    source_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_srid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Version tracking
    current_version: Mapped[int] = mapped_column(Integer, server_default="1", default=1)

    # Per-dataset tile cache TTL override (null = use global settings.tile_cache_ttl)
    tile_cache_ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
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
        # NOTE: uniqueness enforced by functional unique index in migration:
        # CREATE UNIQUE INDEX uq_record_keyword ON ... (record_id, keyword, keyword_type, COALESCE(vocabulary_uri, ''))
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
    )
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
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
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
    __table_args__ = {"schema": "catalog"}

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
    # FK targets records.id (not datasets.id) because relationships are defined at the
    # catalog record level. Dataset and record share a 1:1 FK, so record.id == dataset.record_id.
    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
    )
    target_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
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
