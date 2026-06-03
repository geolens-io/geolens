import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EmbedToken(Base):
    __tablename__ = "embed_tokens"
    __table_args__ = (
        Index(
            "uq_embed_tokens_one_active_per_map",
            "map_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        # DBM-02: partial index for the hot
        # `WHERE is_active = true AND expires_at > now()` filter combo.
        # Migration 0013 is the source of truth for the actual DDL.
        Index(
            "ix_embed_tokens_active_expires",
            "expires_at",
            postgresql_where=text("is_active = true"),
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    token_hint: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoped_dataset_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    allowed_origins: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
