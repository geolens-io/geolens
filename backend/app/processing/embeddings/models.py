import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    and_,
    func,
    or_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

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
    # fix(#1546): the vector space a row lives in is a function of the model,
    # the width it was asked for AND the endpoint that served it. `model_name`
    # names only the first, so one model behind two endpoints is two spaces
    # under one label and nothing stored tells them apart. This is the SHA-256
    # of that triple, computed by `embedding_config_fingerprint` in
    # `processing/embeddings/helpers.py`.
    #
    # NULL means "written before this column existed". Migration 0052 does not
    # backfill it: what configuration produced a pre-existing vector is not
    # recoverable, and stamping those rows with today's configuration would
    # invent provenance. `usable_by_config` below is where NULL is given its
    # meaning for every reader.
    config_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    record = relationship("Record")

    @classmethod
    def usable_by_config(
        cls, model_name: str, config_fingerprint: str | None
    ) -> ColumnElement[bool]:
        """Match rows whose vector can be compared against ``config_fingerprint``.

        fix(#1546): ONE definition of the rule, on the model, because every
        reader has to apply the same one or the inconsistency simply moves.
        Semantic search, the non-force backfill's "already covered" predicate
        and the admin coverage stats all call this; `modules/catalog/` reaches
        it through `CatalogPort.record_embedding_orm_class()`, which is why it
        lives here rather than in `helpers.py`. The admin panel's raw-SQL
        coverage query spells the same condition out by hand — the two are
        pinned together by test_embedding_config_stamp_1546.py.

        An UNSTAMPED row (NULL) matches on model name alone, exactly as before
        this column existed. That is a deliberately weaker guarantee, kept so
        that upgrading does not empty semantic search: every row already in the
        table is unstamped, and the alternative to grandfathering them is
        either a catalog-wide re-embed nobody asked to pay for or a search that
        returns nothing until one finishes.

        fix(#1580): ``config_fingerprint`` may itself be None, because
        related-items compares two STORED rows and takes the pair off the anchor
        row rather than off the live configuration (see
        ``get_anchor_embedding_row``). SQLAlchemy renders ``== None`` as ``IS
        NULL``, so an unstamped anchor selects the unstamped rows of its own
        model and nothing else. That is the same grandfathering read from the
        other side, and it keeps a legacy catalog's related-items working
        unchanged instead of emptying it.
        """
        return and_(
            cls.model_name == model_name,
            or_(
                cls.config_fingerprint.is_(None),
                cls.config_fingerprint == config_fingerprint,
            ),
        )
