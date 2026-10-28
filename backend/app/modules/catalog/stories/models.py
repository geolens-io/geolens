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
