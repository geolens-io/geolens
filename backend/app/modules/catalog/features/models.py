"""ORM models owned by the feature-editing domain."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FeatureCreateKey(Base):
    """The feature one ``Idempotency-Key`` created, per user and dataset.

    Written in the transaction that inserts the feature, so a key row exists
    exactly when its feature was committed. ``gid`` has no foreign key: the
    feature lives in a per-dataset data table, and a deleted feature is an
    answer (409) rather than a cascade. ``table_oid`` names the physical data
    table at creation: a reupload swap or a registered-table overwrite drops and
    recreates it, after which ``gid`` means whatever row the new table gave that
    number. ``attempt`` is the highest attempt number whose body has been
    applied to the feature, and ``row_xmin`` is the feature row's ``xmin`` as
    that apply left it: any other writer changes it, which tells a later
    attempt that its body would overwrite someone else's edit.
    """

    __tablename__ = "feature_create_keys"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "user_id", "key", name="uq_feature_create_keys_key"
        ),
        # The unique index leads with dataset_id; this one serves user deletes.
        Index("ix_feature_create_keys_user_id", "user_id"),
        Index("ix_feature_create_keys_created_at", "created_at"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    gid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_oid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    row_xmin: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
