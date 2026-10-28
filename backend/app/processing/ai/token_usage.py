"""AI token usage tracking: model and persistence helper.

Stores per-request token counts for cost analysis and budget monitoring.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
    *,
    user_id: uuid.UUID | None,
    subsystem: str,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Persist a token usage record durably, best-effort (errors logged, not raised).

    Writes in an INDEPENDENT, self-committing session, not the caller's.

    ``MAX_AI_TOKENS_PER_USER_PER_DAY`` reads this table, but gated AI paths
    commit inconsistently (``get_db()`` doesn't commit on success, streaming
    and chat never commit, only the non-stream map handler does), so a write
    in the caller's session would be dropped on the rest and under-count the
    cap. Tokens already spent must survive even a later rollback.
    """
    # Late-bound so the test fixture's rebinding of app.core.db.async_session
    # is honored; a module-scope import snapshots the dev-DB factory.
    from app.core.db import async_session

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


async def record_token_usage_from_error(
    _db: AsyncSession,
    exc: BaseException,
    *,
    user_id: uuid.UUID | None,
    subsystem: str,
    model: str | None,
) -> None:
    """Persist what a failed tool loop had already spent.

    Reads the counts ``attach_token_usage`` stamped onto the exception (or
    its cause: ``asyncio.wait_for`` raises ``TimeoutError`` ``from`` the
    ``CancelledError`` the coroutine saw, so the stamp arrives one hop
    down). Does nothing when absent or zero, so a failure that never
    reached the provider writes no row.

    The reader is imported lazily to avoid an import cycle with llm_loop.
    """
    from app.processing.ai.llm_loop import token_usage_from_error

    input_tokens, output_tokens = token_usage_from_error(exc)
    if not input_tokens and not output_tokens:
        return
    logger.info(
        "Recording token usage from a failed LLM tool loop",
        subsystem=subsystem,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    # Shielded: this runs in a handler about to re-raise, and when that
    # exception IS the cancellation, a plain await would be cancelled before
    # the row lands.
    await _await_write_even_if_cancelled(
        record_token_usage(
            user_id=user_id,
            subsystem=subsystem,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )


# Strong references to in-flight writes. A task held only by the event loop can
# be garbage collected mid-flight; this set is the documented way to keep one
# alive, and the done callback keeps it from growing.
_PENDING_USAGE_WRITES: set[asyncio.Task] = set()
# Writes normally finish within a request; this many pending means the
# database is stalling.
_PENDING_USAGE_WRITES_WARN_AT = 100


@asynccontextmanager
async def usage_accounting(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    subsystem: str,
    model: str | None,
) -> AsyncIterator[None]:
    """Bill a provider tool loop for what it spent, however it ends.

    An ``except Exception`` per caller would miss cancellation, so an SSE
    client disconnecting after a completed round would leave tokens
    unrecorded. A structural test pins that every provider ``complete()``
    sits inside one of these.

    ``BaseException``, not ``Exception``: ``CancelledError`` derives from
    it, and that's exactly the shape a disconnect takes.
    """
    try:
        yield
    except BaseException as exc:
        await record_token_usage_from_error(
            db, exc, user_id=user_id, subsystem=subsystem, model=model
        )
        raise


async def _await_write_even_if_cancelled(coro) -> None:  # type: ignore[no-untyped-def]
    """Await a usage write that must survive the cancellation that triggered it.

    Under cancellation every ``await`` here raises ``CancelledError``
    immediately, so awaiting the write directly would drop the row the
    cancellation makes valuable. The write runs as its own shielded task:
    this coroutine stops waiting when cancelled, the task doesn't, and
    ``record_token_usage`` commits on an independent session.
    """
    task = asyncio.ensure_future(coro)
    _PENDING_USAGE_WRITES.add(task)
    task.add_done_callback(_PENDING_USAGE_WRITES.discard)
    pending = len(_PENDING_USAGE_WRITES)
    if pending % _PENDING_USAGE_WRITES_WARN_AT == 0:
        logger.warning("AI token usage writes are piling up", pending=pending)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # We are being cancelled, not the write. Let the caller re-raise the
        # original; the shielded task carries on to its own commit.
        pass
