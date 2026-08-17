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

        This is the predicate for a reader comparing a FRESH vector against
        stored rows: semantic search, the backfill's coverage question, the
        admin panel. It always receives a resolved configuration, never None.

        A reader comparing two STORED rows uses ``usable_by_stored_anchor``
        below. The two expressions agree today; they are separate because the
        questions are, and because fix(#1580 review r2) had to argue out what a
        NULL row means from the anchor side. That argument belongs next to the
        reader it governs, not folded into this one.
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

        fix(#1580 review r2). Related items compares two stored rows, so the
        pair — not the live configuration — decides comparability, and the
        anchor's fingerprint may itself be NULL. That raises a question search
        never has to answer: what may a NULL side be compared against?

        **The rule: an unstamped side is comparable to every space of its
        model, whichever side it is on.** A NULL anchor matches every row of its
        model; a stamped anchor matches its own fingerprint OR NULL.

        The alternative was strict — a stamped anchor matching its exact
        fingerprint and nothing else — and the argument for it is real: a
        stamped anchor is evidence the catalog is past upgrade morning, a NULL
        candidate's space is unknown, and after an endpoint change plus a
        partial re-embed the rows still carrying NULL are probably the old
        space, so lenient produces some meaningless pairs.

        Lenient won on three counts.

        A stamped anchor is evidence the catalog is past upgrade morning; it is
        NOT evidence the configuration changed. On the common path — every
        deployment upgrading with the same model and endpoint — every NULL row
        IS the same space as every stamped one, and strict makes both partitions
        sparse for nothing: legacy records see only legacy, stamped see only
        stamped.

        Neither partition heals. Generate Missing treats a NULL row as covered,
        so nothing goes back to stamp the rest, and the split persists for as
        long as the instance runs rather than until the next backfill.

        And search and related items have to agree about what a NULL row means.
        #1546 already decided: comparable to any live space of its model. Strict
        would have search return B for A while related items omitted it, on the
        same two rows.

        The rare path keeps its cost — some meaningless pairs after an endpoint
        change — which is the acceptance #1546 already made for search, with
        Regenerate All as the remedy.

        SYMMETRY is the part that is not a judgement call. Comparability is a
        property of the PAIR: whether A and B may be compared cannot depend on
        which one you start from. Before this, ``usable_by_config(m, F)`` let a
        stamped anchor see NULL rows while ``usable_by_config(m, None)``
        rendered both arms as ``IS NULL`` (SQLAlchemy's reading of ``== None``)
        so the NULL side could not see back — and the ordinary catalog produces
        it, because one edit after an upgrade stamps ONE record and that record
        then vanishes from every legacy record's list while still listing them.
        Both candidate rules are symmetric; only the shipped one is also
        consistent with what #1546 decided a NULL row means.
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
