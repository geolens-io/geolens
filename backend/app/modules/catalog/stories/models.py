import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Story(Base):
    """A story: chapters of text blocks, each with an optional scene on a map.

    ``draft`` is what editors save; readers get ``published``, which only
    Publish writes. Both hold a whole story document (see ``schemas``).
    """

    __tablename__ = "stories"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'public', 'internal', 'restricted')",
            name="chk_stories_visibility",
        ),
        Index("ix_stories_created_by", "created_by"),
        Index("ix_stories_cover_asset_id", "cover_asset_id"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20), default="private", server_default="private"
    )
    draft: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Bumped by every draft save, so a save from a stale copy is refused.
    draft_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    published: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Applies at once like the title, outside draft and publish.
    cover_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "catalog.story_assets.id",
            ondelete="SET NULL",
            name="fk_stories_cover_asset_id",
            use_alter=True,
        ),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    # Dormant tenant_id: nullable, no FK enforcement.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StoryMap(Base):
    """A map that a scene in the story's draft or published document uses."""

    __tablename__ = "story_maps"
    __table_args__ = (
        Index("ix_story_maps_map_id", "map_id"),
        {"schema": "catalog"},
    )

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.stories.id", ondelete="CASCADE"), primary_key=True
    )
    map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), primary_key=True
    )
    # Derived from the story by trigger, which also refuses another tenant's map.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class StoryGroupGrant(Base):
    """A sharing group whose members may read a ``restricted`` story."""

    __tablename__ = "story_group_grants"
    __table_args__ = (
        Index("ix_story_group_grants_group_id", "group_id"),
        Index(
            "ix_story_group_grants_granted_by",
            "granted_by",
            postgresql_where=text("granted_by IS NOT NULL"),
        ),
        {"schema": "catalog"},
    )

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.stories.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.groups.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    # Derived from the story by trigger, which also refuses another tenant's group.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StoryAsset(Base):
    """An image uploaded to a story, stored re-encoded as WebP.

    Its blocks and the story's cover name it by id. Its stored object is
    written once under a key no other asset uses.
    """

    __tablename__ = "story_assets"
    __table_args__ = (
        Index("ix_story_assets_story_id", "story_id"),
        Index("ix_story_assets_created_by", "created_by"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.stories.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    # Derived from the story by trigger, which refuses a mismatched tenant.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Upload time, refreshed when a change stops using the asset; cleanup
    # counts its grace period from here.
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
