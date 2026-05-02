"""AI token usage tracking: model and persistence helper.

Stores per-request token counts for cost analysis and budget monitoring.
"""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

logger = structlog.stdlib.get_logger(__name__)


class AITokenUsage(Base):
    __tablename__ = "ai_token_usage"
    __table_args__ = (
        Index("ix_ai_token_usage_subsystem_created", "subsystem", "created_at"),
        Index("ix_ai_token_usage_user_created", "user_id", "created_at"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    subsystem: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 'map_generation', 'chat', 'sql', 'metadata'
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def record_token_usage(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    subsystem: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Persist a token usage record. Best-effort — errors are logged, not raised.

    Uses a savepoint so a failure (e.g., missing table) doesn't poison
    the caller's outer transaction.
    """
    try:
        async with db.begin_nested():
            usage = AITokenUsage(
                user_id=user_id,
                subsystem=subsystem,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            db.add(usage)
    except Exception:
        logger.debug("Failed to record token usage", exc_info=True)
