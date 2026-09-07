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
    # fix(#1546): the vector space a row lives in is a function of model,
    # width, AND endpoint — `model_name` names only the first, so one
    # model behind two endpoints is two spaces under one label. This is
    # the SHA-256 of that triple, from `embedding_config_fingerprint` in
    # `processing/embeddings/helpers.py`.
    #
    # NULL means "written before this column existed" — migration 0052
    # does not backfill it, since the producing configuration isn't
    # recoverable and stamping today's would invent provenance.
    # `usable_by_config` below gives NULL its meaning for every reader.
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

        fix(#1546): ONE definition of the rule, on the model — every reader
        (semantic search, the non-force backfill's "covered" predicate, admin
        coverage stats, and `CatalogPort.record_embedding_orm_class()`) must
        apply the same one. The admin panel's raw-SQL coverage query spells
        the same condition by hand; the two are pinned together by
        test_embedding_config_stamp_1546.py.

        An UNSTAMPED row (NULL) matches on model name alone — deliberately
        weaker, so upgrading doesn't empty semantic search: every existing
        row is unstamped, and the alternative is a catalog-wide re-embed or a
        search returning nothing until one finishes.

        This is for a FRESH vector vs stored rows (a resolved configuration,
        never None). A reader comparing two STORED rows uses
        ``usable_by_stored_anchor`` below instead.
        """
        return and_(
            cls.model_name == model_name,
            or_(
                cls.config_fingerprint.is_(None),
                cls.config_fingerprint == config_fingerprint,
            ),
        )

    @classmethod
    def usable_by_stored_anchor(
        cls, model_name: str, config_fingerprint: str | None
    ) -> ColumnElement[bool]:
        """Match rows comparable against ANOTHER STORED row's configuration.

        fix(#1580): related items compares two STORED rows, so the pair, not
        the live configuration, decides comparability. Rule: an unstamped
        side is comparable to every space of its model, whichever side it is
        on — a NULL anchor matches every row of its model, a stamped anchor
        matches its own fingerprint OR NULL. This agrees with what #1546
        decided a NULL row means for search, so the two readers can't
        disagree about the same pair.

        SYMMETRY is load-bearing: comparability is a property of the PAIR, so
        whether A and B may be compared cannot depend on which one you start
        from. The prior form let a stamped anchor see NULL rows while a NULL
        anchor rendered both sides ``IS NULL`` and could not see back — real
        on an ordinary catalog, where one post-upgrade edit stamps ONE record
        and that record vanishes from every legacy record's list while still
        listing them.
        """
        if config_fingerprint is None:
            return cls.model_name == model_name
        return and_(
            cls.model_name == model_name,
            or_(
                cls.config_fingerprint.is_(None),
                cls.config_fingerprint == config_fingerprint,
            ),
        )
