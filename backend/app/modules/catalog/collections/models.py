import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CollectionDataset(Base):
    __tablename__ = "collection_datasets"
    __table_args__ = {"schema": "catalog"}

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.collections.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),
        # DBM-10 covering index added in migration 0014.
        Index("ix_dataset_versions_dataset_id", "dataset_id"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    srid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geometry_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
