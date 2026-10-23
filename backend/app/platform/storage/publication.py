"""A ledger of stored objects whose catalog rows have not committed yet."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog

logger = structlog.stdlib.get_logger(__name__)


class AssetPublication:
    """The objects written for a row that has not committed yet.

    Settling ends tracking at commit. Later failures must not delete an object
    already referenced by the committed row.
    """

    def __init__(self) -> None:
        self._pending: list[str] = []
        self._outcome_known = True

    def record(self, physical_key: str) -> None:
        """Note an object that exists but is not named by a committed row yet.

        Physical, not logical: writers resolve keys differently (tenant prefix
        vs deliberately-global sprite icons), and rollback deletes what it's
        given rather than resolving anything.

        Call before awaiting the write: a PUT can land and still fail the
        client, which would orphan an object per retry. Recording first is
        free, since rollback either deletes what this request wrote or no-ops
        on an unwritten key. For map assets,
        ``test_every_object_write_records_before_putting_1778`` enforces this.
        """
        self._pending.append(physical_key)

    def committing(self) -> None:
        """A commit is about to be awaited, so its outcome stops being knowable.

        A lost connection between Postgres committing and the ack arriving
        raises out of the await for a transaction that did commit. From this
        mark until ``settled``, an exception says nothing about whether the
        row landed, so nothing is deleted.

        This leaves one object behind on the rare true failure; verifying from
        an independent session, on a connection that just proved unreliable,
        costs more. Same trade as the post-commit liveness read that map asset
        cleanup makes.

        Call immediately before the commit. For map assets,
        ``test_every_publication_marks_before_committing_1778`` enforces this.
        """
        self._outcome_known = False

    def settled(self) -> None:
        """The row naming every recorded object is committed. Stop tracking.

        Call this as the next statement after the commit, and as the last
        statement of the block. For map assets,
        ``test_every_publication_settles_at_the_commit`` enforces this.
        """
        self._pending.clear()
        self._outcome_known = True

    @property
    def pending(self) -> tuple[str, ...]:
        return tuple(self._pending)

    @property
    def outcome_unknown(self) -> bool:
        """True between ``committing`` and ``settled``: nothing may be deleted."""
        return not self._outcome_known


@asynccontextmanager
async def asset_publication() -> AsyncIterator[AssetPublication]:
    """Track object writes and clean up those whose catalog rows never commit.

    Cleanup preserves the original exception and logs its own failures. Settled
    publications need no rollback; an indeterminate commit outcome also skips
    cleanup because the object may already be referenced by a committed row.
    """
    from app.platform.storage.provider import get_storage

    publication = AssetPublication()
    try:
        yield publication
    except BaseException:
        if publication.outcome_unknown:
            # The exception arrived while a commit was in flight, so it does
            # not say whether the row landed, and deleting is irreversible.
            logger.warning(
                "map_asset_publication_rollback_skipped_indeterminate_commit",
                storage_keys=list(publication.pending),
            )
            raise
        for physical_key in publication.pending:
            try:
                await get_storage().delete(physical_key)
            except Exception:  # broad: storage backends raise varied errors
                logger.warning(
                    "map_asset_publication_rollback_failed",
                    storage_key=physical_key,
                    exc_info=True,
                )
        raise
