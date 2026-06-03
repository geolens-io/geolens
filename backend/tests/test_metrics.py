"""Tests for the Prometheus metrics module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

from app.observability.metrics.instrumentator import create_instrumentator
from app.observability.metrics.jobs import (
    _refresh_job_metrics,
    jobs_active,
    jobs_completed_total,
    jobs_failed_total,
    jobs_queue_depth,
)
from app.observability.metrics.pool import (
    _refresh_pool_metrics,
    db_pool_checkedout,
    db_pool_checkedin,
    db_pool_overflow,
    db_pool_size,
)


def test_create_instrumentator_returns_instrumentator():
    """Instrumentator factory returns configured instance."""
    inst = create_instrumentator()
    assert isinstance(inst, Instrumentator)
    # excluded_handlers are compiled regex patterns
    handler_patterns = [p.pattern for p in inst.excluded_handlers]
    assert "/metrics" in handler_patterns
    assert "/health" in handler_patterns


def test_job_metrics_registered():
    """Job metrics are proper Prometheus types with correct names."""
    assert isinstance(jobs_queue_depth, Gauge)
    assert isinstance(jobs_active, Gauge)
    assert isinstance(jobs_completed_total, Counter)
    assert isinstance(jobs_failed_total, Counter)

    assert "geolens_jobs_queue_depth" in jobs_queue_depth._name
    assert "geolens_jobs_active" in jobs_active._name
    # Counter._name strips _total suffix; check the base name
    assert "geolens_jobs_completed" in jobs_completed_total._name
    assert "geolens_jobs_failed" in jobs_failed_total._name


def test_pool_metrics_registered():
    """Pool metrics are all Gauge instances."""
    assert isinstance(db_pool_checkedout, Gauge)
    assert isinstance(db_pool_checkedin, Gauge)
    assert isinstance(db_pool_overflow, Gauge)
    assert isinstance(db_pool_size, Gauge)


@pytest.mark.asyncio
async def test_refresh_job_metrics_handles_db_error():
    """Job metrics collector swallows database errors without raising."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("connection refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect = MagicMock(return_value=mock_conn)

    with patch("app.core.db.engine", mock_engine):
        # Should not raise
        await _refresh_job_metrics()


@pytest.mark.asyncio
async def test_refresh_pool_metrics_skips_non_queuepool():
    """Pool metrics collector skips when pool is not QueuePool."""
    mock_pool = MagicMock(spec=[])  # Empty spec -- not a QueuePool
    mock_engine = MagicMock()
    mock_engine.pool = mock_pool

    mock_settings = MagicMock()
    mock_settings.db_use_external_pooler = False

    with (
        patch("app.core.db.engine", mock_engine),
        patch("app.core.config.settings", mock_settings),
    ):
        await _refresh_pool_metrics()

    # Pool gauges should remain at their default (0)
    assert db_pool_checkedout._value.get() == 0.0
    assert db_pool_checkedin._value.get() == 0.0
