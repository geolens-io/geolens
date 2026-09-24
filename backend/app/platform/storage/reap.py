"""Delete everything under a managed storage prefix without listing it whole."""

from __future__ import annotations

import asyncio

from app.platform.storage import provider as storage_provider
from app.platform.storage.titiler_url import resolve_storage_key

# Enough deletes at once to overlap object-store round trips while staying
# under boto3's pool of 10 connections per client. Each delete also holds a
# thread from the default executor, which every other to_thread call shares.
MAX_DELETES_IN_FLIGHT = 8


class PrefixDeleteError(RuntimeError):
    """Some objects under a prefix could not be deleted; the rest were."""


async def delete_prefix(prefix: str, *, tenant_id: str | None) -> int:
    """Delete every object under ``prefix`` and return how many were deleted.

    Walks the prefix one provider page at a time and finishes a page's
    deletes before reading the next, with at most ``MAX_DELETES_IN_FLIGHT``
    running. A failed delete doesn't stop the walk; once the walk ends, one
    ``PrefixDeleteError`` says how many failed. A failure to list raises at
    once. The provider is looked up at call time, so tests can replace it.
    """
    storage = storage_provider.get_storage()
    physical_prefix = resolve_storage_key(prefix, tenant_id=tenant_id)
    gate = asyncio.Semaphore(MAX_DELETES_IN_FLIGHT)

    async def delete(key: str) -> None:
        async with gate:
            await storage.delete(key)

    deleted = failed = 0
    first_failure: BaseException | None = None
    async for page in storage.iter_object_pages(physical_prefix):
        results = await asyncio.gather(
            *(delete(entry.key) for entry in page), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                failed += 1
                first_failure = first_failure or result
            else:
                deleted += 1

    if failed:
        raise PrefixDeleteError(
            f"{failed} of {deleted + failed} deletes under {prefix} failed"
        ) from first_failure
    return deleted
