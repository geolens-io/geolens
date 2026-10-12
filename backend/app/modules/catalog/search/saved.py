"""SavedSearch model and CRUD service functions."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


MAX_SAVED_SEARCHES_PER_USER = 100


class SavedSearchLimitError(Exception):
    """The user already has ``MAX_SAVED_SEARCHES_PER_USER`` saved searches."""


async def create_saved_search(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    params: dict,
) -> SavedSearch:
    """Create a saved search, or update params/updated_at if (user_id, name) exists.

    Raises SavedSearchLimitError when a new name would exceed the per-user cap.
    """
    # Serializes one user's creates so concurrent new names can't each pass
    # the count below; held until the caller's transaction ends.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"saved_searches:{user_id}"},
    )
    existing = await session.scalar(
        select(SavedSearch.id).where(
            SavedSearch.user_id == user_id, SavedSearch.name == name
        )
    )
    if existing is None:
        count = await session.scalar(
            select(func.count())
            .select_from(SavedSearch)
            .where(SavedSearch.user_id == user_id)
        )
        if count >= MAX_SAVED_SEARCHES_PER_USER:
            raise SavedSearchLimitError(
                f"You can keep at most {MAX_SAVED_SEARCHES_PER_USER} saved "
                "searches; delete one to save another"
            )
    stmt = (
        pg_insert(SavedSearch)
        .values(user_id=user_id, name=name, params=params)
        .on_conflict_do_update(
            constraint="uq_saved_searches_user_name",
            set_={"params": params, "updated_at": func.now()},
        )
        .returning(SavedSearch)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def list_saved_searches(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[SavedSearch], int]:
    """List saved searches for a user, ordered by most recently updated."""
    base = select(SavedSearch).where(SavedSearch.user_id == user_id)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    stmt = base.order_by(SavedSearch.updated_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_saved_search(
    session: AsyncSession,
    search_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SavedSearch | None:
    """Get a single saved search by ID, filtered by user ownership."""
    stmt = select(SavedSearch).where(
        SavedSearch.id == search_id,
        SavedSearch.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_saved_search(
    session: AsyncSession,
    search_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Delete a saved search if owned by user. Returns True if deleted."""
    saved = await get_saved_search(session, search_id, user_id)
    if saved is None:
        return False
    await session.delete(saved)
    await session.flush()
    return True
