"""Draw a vector dataset's quicklook after publication and swing its pointer."""

import asyncio
import uuid

import structlog

from app.platform.storage import get_storage
from app.processing.ingest.tasks_common import _current_tenant_schema

# Draws in a row before a quicklook stops chasing a table that keeps changing.
_QUICKLOOK_DRAWS = 3


async def _generate_quicklook(session, dataset_id: uuid.UUID, table_name: str) -> bool:
    """Draw ``table_name``'s quicklook and point the dataset at it (non-fatal).

    Runs after the commit that published the table, so a connection-killing
    query (OOM, timeout on complex geometry) cannot roll back the dataset.
    Separate try/except blocks around generate+upload, the URI write and
    the commit let operators tell which phase failed from the logs.

    The caller must pass a fresh session, not the one that published the
    table. The generation timeout can cancel the inner geom query mid-flight
    and poison the asyncpg cursor; the defensive ``rollback()`` then expires
    every ORM attribute (``expire_on_rollback=True``). On the publishing
    session that trips ``MissingGreenlet`` on ``dataset.record``'s next lazy
    access.

    Every draw writes an object of its own and swings the dataset's pointer to
    it only while the tile version is still the one the draw read, so an older
    draw can neither overwrite a newer image nor take the pointer back. Each
    change to the data rolls the tile version, so a draw that sees the version
    move while it ran draws again. A new key per draw also gives the image a
    new identity for caches and for the reconcile sweep's probe.
    The draw holds only the caller's session, one pooled connection.

    The caller's view of ``quicklook_256_uri`` is stale after this returns.
    Returns whether the last draw landed, or True when the dataset is gone.
    """
    from sqlalchemy import select

    from app.platform.extensions import get_processing_port

    Dataset = get_processing_port().get_dataset_orm_class()
    content_version = select(Dataset.tile_cache_version).where(Dataset.id == dataset_id)
    landed = False
    try:
        for _ in range(_QUICKLOOK_DRAWS):
            drawn = await session.scalar(content_version)
            landed = await _draw_quicklook(session, dataset_id, table_name, drawn)
            # A draw that failed can leave its transaction aborted.
            await session.rollback()
            if await session.scalar(content_version) == drawn:
                return landed
    except Exception as exc:  # broad: the dataset is already published
        structlog.get_logger().warning(
            "quicklook_failed", phase="version", table=table_name, error=str(exc)
        )
        return False
    return landed


async def _draw_quicklook(
    session, dataset_id: uuid.UUID, table_name: str, drawn_version: int | None
) -> bool:
    """Draw, upload and record the quicklook once.

    ``drawn_version`` is the tile version the draw started from; the pointer
    only moves while the dataset still has it. Returns whether the image
    landed or the dataset is gone.
    """
    import io as _io

    from sqlalchemy import select, update

    from app.core.db.tenant_session import current_tenant_var
    from app.platform.extensions import get_processing_port
    from app.platform.storage.titiler_url import resolve_storage_key

    _ql_log = structlog.get_logger()
    ql_storage = get_storage()
    ql_key = f"vectors/{dataset_id}/quicklook_256_{uuid.uuid4().hex[:12]}.png"
    stored_key = resolve_storage_key(ql_key, tenant_id=current_tenant_var.get())
    try:
        from app.processing.vector.quicklook import (
            generate_vector_quicklook_with_timeout as generate_vector_quicklook,
        )

        ql_bytes = await generate_vector_quicklook(
            session,
            table_name,
            "",
            256,
            schema=_current_tenant_schema(),
        )
        # Ends the read before the upload, since its transaction holds the
        # table against a later replacement's rename. Also recovers a cursor
        # a wait_for cancel poisoned.
        await session.rollback()
        await ql_storage.put(stored_key, _io.BytesIO(ql_bytes))
    except asyncio.CancelledError:
        # Providers drain the write before re-raising, so the object exists.
        await asyncio.shield(_reap_quicklook(ql_storage, stored_key, table_name))
        raise
    except Exception as _ql_exc:  # broad: quicklook generation is non-fatal; geometry rendering can OOM/timeout
        _ql_log.warning(
            "quicklook_failed",
            phase="generate",
            table=table_name,
            error=str(_ql_exc),
        )
        # An upload can complete remotely and still raise, so the key is reaped.
        await _reap_quicklook(ql_storage, stored_key, table_name)
        return False

    # The write is IO that can raise on a dead connection, and the dataset is
    # already published, so its failure is only logged.
    Dataset = get_processing_port().get_dataset_orm_class()
    previous_uri: str | None = None
    try:
        previous_uri = await session.scalar(
            select(Dataset.quicklook_256_uri)
            .where(Dataset.id == dataset_id)
            .with_for_update(key_share=True)
        )
        written = await session.execute(
            update(Dataset)
            .where(
                Dataset.id == dataset_id,
                Dataset.tile_cache_version.is_not_distinct_from(drawn_version),
            )
            .values(quicklook_256_uri=ql_key)
            .execution_options(synchronize_session=False)
        )
        swung = bool(written.rowcount)
        gone = not swung and (
            await session.scalar(select(Dataset.id).where(Dataset.id == dataset_id))
            is None
        )
    except asyncio.CancelledError:
        # Nothing was committed, so the unreferenced upload is reaped.
        await asyncio.shield(session.rollback())
        await asyncio.shield(_reap_quicklook(ql_storage, stored_key, table_name))
        raise
    except Exception as _ql_recovery_exc:  # broad: non-fatal contract — connection drop between upload and recovery must not propagate
        try:
            await session.rollback()
        except Exception:  # broad: best-effort cleanup; connection may be irrecoverable
            pass
        await _reap_quicklook(ql_storage, stored_key, table_name)
        _ql_log.warning(
            "quicklook_failed",
            phase="recovery",
            table=table_name,
            error=str(_ql_recovery_exc)[:500],
        )
        return False

    if gone or not swung:
        # A delete that reaped vectors/{id}/ before this upload left it unowned,
        # and a draw the data outran must not leave its image behind.
        await session.rollback()
        await _reap_quicklook(ql_storage, stored_key, table_name)
        return gone

    try:
        await session.commit()
    except asyncio.CancelledError:
        # The commit may or may not have landed; only an unreferenced image goes.
        await asyncio.shield(session.rollback())
        landed = await asyncio.shield(
            session.scalar(
                select(Dataset.quicklook_256_uri).where(Dataset.id == dataset_id)
            )
        )
        if landed != ql_key:
            await asyncio.shield(_reap_quicklook(ql_storage, stored_key, table_name))
        raise
    except (
        Exception
    ) as _ql_commit_exc:  # broad: transient commit failure after successful generation
        await session.rollback()
        # The commit may have landed, so the image stays; reaping a live one would 404.
        _ql_log.warning(
            "quicklook_failed",
            phase="commit",
            table=table_name,
            error=str(_ql_commit_exc),
        )
        return False
    if previous_uri and previous_uri != ql_key:
        await _reap_quicklook(
            ql_storage,
            resolve_storage_key(previous_uri, tenant_id=current_tenant_var.get()),
            table_name,
        )
    return True


async def _reap_quicklook(storage, stored_key: str, table_name: str) -> None:
    """Delete an image nothing points at; a leftover only costs storage."""
    try:
        await storage.delete(stored_key)
    except Exception as exc:  # broad: an orphaned image only costs storage
        structlog.get_logger().warning(
            "quicklook_reap_failed", table=table_name, error=str(exc)
        )
