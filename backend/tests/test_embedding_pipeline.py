"""Tests for the embedding pipeline: build_content_text, compute_content_hash,
generate_and_store_embedding.

These are unit tests using mocks -- they do not require a running database.
The RecordEmbedding import is deferred to avoid triggering DB engine creation
at module import time.
"""

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# build_content_text
# ---------------------------------------------------------------------------


class TestBuildContentText:
    def test_all_fields(self):
        from app.processing.embeddings.service import build_content_text

        result = build_content_text(
            title="My Dataset",
            summary="A summary of the dataset",
            keywords=["water", "hydrology"],
            lineage="Derived from national data",
        )
        assert "My Dataset" in result
        assert "A summary of the dataset" in result
        assert "water, hydrology" in result
        assert "Derived from national data" in result
        assert "\n" in result

    def test_all_none(self):
        from app.processing.embeddings.service import build_content_text

        result = build_content_text(
            title=None, summary=None, keywords=None, lineage=None
        )
        assert result == ""

    def test_partial_fields(self):
        from app.processing.embeddings.service import build_content_text

        result = build_content_text(
            title="Title Only", summary=None, keywords=None, lineage=None
        )
        assert result == "Title Only"

    def test_empty_keywords_list(self):
        from app.processing.embeddings.service import build_content_text

        result = build_content_text(
            title="Title", summary=None, keywords=[], lineage=None
        )
        assert result == "Title"

    def test_keywords_joined_with_comma(self):
        from app.processing.embeddings.service import build_content_text

        result = build_content_text(
            title=None, summary=None, keywords=["a", "b", "c"], lineage=None
        )
        assert result == "a, b, c"


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_returns_sha256(self):
        from app.processing.embeddings.service import compute_content_hash

        text = "hello world"
        expected = hashlib.sha256(text.encode()).hexdigest()
        assert compute_content_hash(text) == expected

    def test_deterministic(self):
        from app.processing.embeddings.service import compute_content_hash

        assert compute_content_hash("test") == compute_content_hash("test")

    def test_different_inputs(self):
        from app.processing.embeddings.service import compute_content_hash

        assert compute_content_hash("a") != compute_content_hash("b")


# ---------------------------------------------------------------------------
# generate_and_store_embedding
# ---------------------------------------------------------------------------


class TestGenerateAndStoreEmbedding:
    @pytest.mark.asyncio
    async def test_skips_when_ai_disabled(self):
        from app.processing.embeddings.service import generate_and_store_embedding

        session = AsyncMock(spec=AsyncSession)

        with patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai:
            mock_ai.get = AsyncMock(return_value=False)
            result = await generate_and_store_embedding(
                session=session,
                record_id=uuid.uuid4(),
                title="Test",
                summary=None,
                keywords=None,
                lineage=None,
            )
            assert result is False
            session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_content_empty(self):
        from app.processing.embeddings.service import generate_and_store_embedding

        session = AsyncMock(spec=AsyncSession)

        with patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai:
            mock_ai.get = AsyncMock(return_value=True)
            result = await generate_and_store_embedding(
                session=session,
                record_id=uuid.uuid4(),
                title=None,
                summary=None,
                keywords=None,
                lineage=None,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_skips_when_hash_matches(self):
        from app.processing.embeddings.service import generate_and_store_embedding

        record_id = uuid.uuid4()
        content_text = "Test Title"
        expected_hash = hashlib.sha256(content_text.encode()).hexdigest()

        mock_existing = MagicMock()
        mock_existing.content_hash = expected_hash

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_existing

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai,
            patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
        ):
            mock_ai.get = AsyncMock(return_value=True)
            mock_model.get = AsyncMock(return_value="text-embedding-3-small")

            result = await generate_and_store_embedding(
                session=session,
                record_id=record_id,
                title="Test Title",
                summary=None,
                keywords=None,
                lineage=None,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_upserts_on_success(self):
        from app.processing.embeddings.models import RecordEmbedding
        from app.processing.embeddings.service import generate_and_store_embedding

        record_id = uuid.uuid4()
        fake_vector = [0.1] * 1536

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai,
            patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
            patch(
                "app.processing.embeddings.service.generate_embedding",
                new_callable=AsyncMock,
            ) as mock_gen,
        ):
            mock_ai.get = AsyncMock(return_value=True)
            mock_model.get = AsyncMock(return_value="text-embedding-3-small")
            mock_gen.return_value = fake_vector

            await generate_and_store_embedding(
                session=session,
                record_id=record_id,
                title="New Dataset",
                summary="A summary",
                keywords=None,
                lineage=None,
            )
            mock_gen.assert_called_once()
            session.add.assert_called_once()
            added_obj = session.add.call_args[0][0]
            assert isinstance(added_obj, RecordEmbedding)
            assert added_obj.record_id == record_id
            assert added_obj.model_name == "text-embedding-3-small"
            session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_on_hash_change(self):
        from app.processing.embeddings.service import generate_and_store_embedding

        record_id = uuid.uuid4()
        fake_vector = [0.2] * 1536

        mock_existing = MagicMock()
        mock_existing.content_hash = "old_hash_value"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_existing

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai,
            patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
            patch(
                "app.processing.embeddings.service.generate_embedding",
                new_callable=AsyncMock,
            ) as mock_gen,
        ):
            mock_ai.get = AsyncMock(return_value=True)
            mock_model.get = AsyncMock(return_value="text-embedding-3-small")
            mock_gen.return_value = fake_vector

            await generate_and_store_embedding(
                session=session,
                record_id=record_id,
                title="Updated Title",
                summary=None,
                keywords=None,
                lineage=None,
            )
            session.add.assert_not_called()
            assert mock_existing.embedding == fake_vector
            session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_catches_embedding_unavailable_error(self):
        from app.processing.embeddings.service import (
            EmbeddingUnavailableError,
            generate_and_store_embedding,
        )

        record_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai,
            patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
            patch(
                "app.processing.embeddings.service.generate_embedding",
                new_callable=AsyncMock,
            ) as mock_gen,
        ):
            mock_ai.get = AsyncMock(return_value=True)
            mock_model.get = AsyncMock(return_value="text-embedding-3-small")
            mock_gen.side_effect = EmbeddingUnavailableError("No API key")

            result = await generate_and_store_embedding(
                session=session,
                record_id=record_id,
                title="Test",
                summary=None,
                keywords=None,
                lineage=None,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_catches_generic_exception(self):
        from app.processing.embeddings.service import generate_and_store_embedding

        record_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.processing.embeddings.service.AI_ENABLED") as mock_ai,
            patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
            patch(
                "app.processing.embeddings.service.generate_embedding",
                new_callable=AsyncMock,
            ) as mock_gen,
        ):
            mock_ai.get = AsyncMock(return_value=True)
            mock_model.get = AsyncMock(return_value="text-embedding-3-small")
            mock_gen.side_effect = RuntimeError("Connection timeout")

            result = await generate_and_store_embedding(
                session=session,
                record_id=record_id,
                title="Test",
                summary=None,
                keywords=None,
                lineage=None,
            )
            assert result is False
