"""Core-owned ORM models.

Place here only models the core runtime owns directly (e.g., DB-backed
configuration). Domain-specific models stay in their domain package
(`app.modules.<domain>.<...>`).

Never import from `app.modules.*` in this module — `core/` must not depend on
`modules/`. The `tests/test_layering.py` architecture guard enforces this rule
(introduced in Phase 212, plan 03).
"""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Text, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": "catalog"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SecurityRevocationGeneration(Base):
    """One row, one number: the cluster-global revocation generation.

    fix(#1778 codex r3/r4). Declared here rather than in a domain package
    because no domain owns it: it is the counter every worker consults to decide
    whether a cached AUTHORIZATION decision predates the latest revocation, and
    ``app/platform/cache/revocation.py`` (which may not import from
    ``app.modules.*``) is what reads and advances it.

    The model exists so ``alembic check`` can see the table migration 0057
    creates; the reads and writes themselves are raw SQL in that module, because
    a single-row counter wants an ``UPDATE ... RETURNING`` rather than an ORM
    round-trip.

    ``id`` is a boolean pinned TRUE by a CHECK plus the primary key, so a second
    row cannot be inserted and no reader has to say which row it means.
    """

    __tablename__ = "security_revocation_generation"
    __table_args__ = (
        CheckConstraint("id IS TRUE", name="ck_security_revocation_generation_one"),
        {"schema": "catalog"},
    )

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, server_default=true())
    generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
