import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RecordEmbedding(Base):
    __tablename__ = "record_embeddings"
    __table_args__ = (
        UniqueConstraint("record_id", "model_name", name="uq_record_embedding_model"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.records.id", ondelete="CASCADE"), nullable=False
    )
    embedding = mapped_column(Vector(), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    record = relationship("Record")
