"""AI token usage tracking: model and persistence helper.

Stores per-request token counts for cost analysis and budget monitoring.
"""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, async_session

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
    _db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    subsystem: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Persist a token usage record durably, best-effort (errors logged, not raised).

    Writes in an INDEPENDENT, self-committing session rather than the caller's
    (``_db``, kept for call-site stability but intentionally unused).

    Why independent: ``MAX_AI_TOKENS_PER_USER_PER_DAY`` enforcement reads this
    table, but the gated AI paths commit inconsistently — ``get_db()`` does not
    commit on success, the streaming/chat handlers never commit, and only the
    non-stream map handler does. A prior savepoint-only write was therefore
    dropped on those paths, so the cap under-counted and was bypassable
    (codex P1 on #402). Committing the caller's session here instead would flush
    partial handler state. Its own short-lived transaction is durable regardless
    of the request lifecycle and is semantically correct — the tokens were
    already spent, so the record must survive even a later request rollback.
    """
    try:
        async with async_session() as session:
            session.add(
                AITokenUsage(
                    user_id=user_id,
                    subsystem=subsystem,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            )
            await session.commit()
    except Exception:  # broad: token-usage record is best-effort accounting; must not break LLM caller flow
        logger.debug("Failed to record token usage", exc_info=True)
