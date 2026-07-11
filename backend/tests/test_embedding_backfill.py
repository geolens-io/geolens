"""Tests for embedding backfill: backfill_embeddings processes records without
embeddings in provider batches (fix #448), handles errors gracefully, and
returns progress counts.

Unit tests using mocks -- no running database required.
"""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_record(
    record_id=None, title="Test Dataset", summary=None, lineage=None, keywords=None
):
    """Create a mock Record with optional keywords."""
    record = MagicMock()
    record.id = record_id or uuid.uuid4()
    record.title = title
    record.summary = summary
    record.lineage_summary = lineage
    kw_objs = []
    for kw_str in keywords or []:
        kw = MagicMock()
        kw.keyword = kw_str
        kw_objs.append(kw)
    record.keywords = kw_objs
    return record


def _make_query_result(records):
    """Create a mock query result that returns records via unique().scalars().all()."""
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = records
    return result


def _patch_backfill_gates(stack: ExitStack, *, ai_enabled=True):
    """Patch the run-level PersistentConfig gates the backfill reads once."""
    from app.processing.embeddings import backfill as backfill_module

    stack.enter_context(
        patch.object(
            backfill_module.AI_ENABLED, "get", AsyncMock(return_value=ai_enabled)
        )
    )
    stack.enter_context(
        patch.object(
            backfill_module.EMBEDDING_MODEL,
            "get",
            AsyncMock(return_value="test-model"),
        )
    )


class TestBackfillEmbeddings:
    @pytest.mark.asyncio
    async def test_processes_records_in_one_batch(self):
        """Records without embeddings are embedded in a single provider call."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Dataset A")
        r2 = _make_record(title="Dataset B")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1, r2]))

        with ExitStack() as stack:
            _patch_backfill_gates(stack)
            mock_batch = stack.enter_context(
                patch(
                    "app.processing.embeddings.backfill.generate_embeddings_batch",
                    new_callable=AsyncMock,
                )
            )
            mock_batch.return_value = [[0.1] * 3, [0.2] * 3]
            result = await backfill_embeddings(session)

        # fix(#448): both records ride ONE provider call, not one call each.
        assert mock_batch.call_count == 1
        assert result["processed"] == 2
        assert result["created"] == 2
        assert result["errors"] == 0
        assert session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_errors_do_not_stop_backfill(self):
        """If one batch fails, the backfill should continue to the next."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Fails")
        r2 = _make_record(title="Succeeds")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1, r2]))

        with ExitStack() as stack:
            _patch_backfill_gates(stack)
            # Force one record per batch so the two records land in two batches.
            stack.enter_context(
                patch("app.processing.embeddings.backfill._BATCH_SIZE", 1)
            )
            mock_batch = stack.enter_context(
                patch(
                    "app.processing.embeddings.backfill.generate_embeddings_batch",
                    new_callable=AsyncMock,
                )
            )
            # fix(#449): a failed batch is retried per record, so the failing
            # single-record batch consumes TWO calls (batch, then retry).
            mock_batch.side_effect = [
                RuntimeError("API error"),
                RuntimeError("API error"),
                [[0.1] * 3],
            ]
            result = await backfill_embeddings(session)

        assert result["processed"] == 2
        assert result["created"] == 1
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_failed_batch_retries_per_record(self):
        """fix(#449, codex P2): one rejected input must not sink its batchmates —
        the failed batch is retried per record and only the bad one errors."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Good")
        r2 = _make_record(title="Too long for the model")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1, r2]))

        with ExitStack() as stack:
            _patch_backfill_gates(stack)
            mock_batch = stack.enter_context(
                patch(
                    "app.processing.embeddings.backfill.generate_embeddings_batch",
                    new_callable=AsyncMock,
                )
            )
            # Batch call rejects; per-record retry succeeds for r1, fails for r2.
            mock_batch.side_effect = [
                RuntimeError("one input over the token limit"),
                [[0.1] * 3],
                RuntimeError("input over the token limit"),
            ]
            result = await backfill_embeddings(session)

        assert mock_batch.call_count == 3
        assert result["processed"] == 2
        assert result["created"] == 1
        assert result["errors"] == 1
        assert session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self):
        """Progress dict has processed, created, skipped, errors keys."""
        from app.processing.embeddings.backfill import backfill_embeddings

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([]))

        result = await backfill_embeddings(session)

        assert result == {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_skips_records_with_empty_content(self):
        """Records whose metadata builds no content text count as skipped."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title=None)

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1]))

        with ExitStack() as stack:
            _patch_backfill_gates(stack)
            mock_batch = stack.enter_context(
                patch(
                    "app.processing.embeddings.backfill.generate_embeddings_batch",
                    new_callable=AsyncMock,
                )
            )
            result = await backfill_embeddings(session)

        assert mock_batch.call_count == 0
        assert result["processed"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_all_when_ai_disabled(self):
        """AI_ENABLED=false short-circuits the run with everything skipped."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Dataset A")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1]))

        with ExitStack() as stack:
            _patch_backfill_gates(stack, ai_enabled=False)
            mock_batch = stack.enter_context(
                patch(
                    "app.processing.embeddings.backfill.generate_embeddings_batch",
                    new_callable=AsyncMock,
                )
            )
            result = await backfill_embeddings(session)

        assert mock_batch.call_count == 0
        assert result == {"processed": 0, "created": 0, "skipped": 1, "errors": 0}

    @pytest.mark.asyncio
    async def test_extracts_keyword_strings(self):
        """Keywords should be extracted as strings into the embedded content."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="With Keywords", keywords=["water", "hydrology"])

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1]))

        with ExitStack() as stack:
            _patch_backfill_gates(stack)
            mock_batch = stack.enter_context(
                patch(
                    "app.processing.embeddings.backfill.generate_embeddings_batch",
                    new_callable=AsyncMock,
                )
            )
            mock_batch.return_value = [[0.1] * 3]
            await backfill_embeddings(session)

        texts = mock_batch.call_args[0][0]
        assert len(texts) == 1
        assert "water, hydrology" in texts[0]
