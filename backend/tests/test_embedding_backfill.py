"""Tests for embedding backfill: backfill_embeddings processes records without
embeddings, handles errors gracefully, and returns progress counts.

Unit tests using mocks -- no running database required.
"""

import uuid
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


class TestBackfillEmbeddings:
    @pytest.mark.asyncio
    async def test_processes_records_without_embeddings(self):
        """Records without embeddings should be processed via generate_and_store_embedding."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Dataset A")
        r2 = _make_record(title="Dataset B")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1, r2]))

        with patch(
            "app.processing.embeddings.backfill.generate_and_store_embedding",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = True
            result = await backfill_embeddings(session)

        assert mock_gen.call_count == 2
        assert result["processed"] == 2
        assert result["created"] == 2
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_individual_errors_do_not_stop_backfill(self):
        """If one record fails, the backfill should continue to the next."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Fails")
        r2 = _make_record(title="Succeeds")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1, r2]))

        with patch(
            "app.processing.embeddings.backfill.generate_and_store_embedding",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = [RuntimeError("API error"), True]
            result = await backfill_embeddings(session)

        assert result["processed"] == 2
        assert result["created"] == 1
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self):
        """Progress dict has processed, created, skipped, errors keys."""
        from app.processing.embeddings.backfill import backfill_embeddings

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([]))

        with patch(
            "app.processing.embeddings.backfill.generate_and_store_embedding",
            new_callable=AsyncMock,
        ):
            result = await backfill_embeddings(session)

        assert result == {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_skips_when_generate_returns_false(self):
        """When generate_and_store_embedding returns False, record counts as skipped."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="Skipped")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1]))

        with patch(
            "app.processing.embeddings.backfill.generate_and_store_embedding",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = False
            result = await backfill_embeddings(session)

        assert result["processed"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_extracts_keyword_strings(self):
        """Keywords should be extracted as strings from RecordKeyword objects."""
        from app.processing.embeddings.backfill import backfill_embeddings

        r1 = _make_record(title="With Keywords", keywords=["water", "hydrology"])

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_query_result([r1]))

        with patch(
            "app.processing.embeddings.backfill.generate_and_store_embedding",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = True
            await backfill_embeddings(session)

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["keywords"] == ["water", "hydrology"]
