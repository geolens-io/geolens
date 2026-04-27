"""Core-owned ORM models.

Place here only models the open-core layer owns directly (e.g., DB-backed
configuration). Domain-specific models stay in their domain package
(`app.modules.<domain>.<...>`).

Never import from `app.modules.*` in this module — `core/` must not depend on
`modules/`. The `tests/test_layering.py` architecture guard enforces this rule
(introduced in Phase 212, plan 03).
"""

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": "catalog"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
