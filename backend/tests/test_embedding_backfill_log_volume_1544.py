"""A failing backfill must not cost more than a succeeding one (#1544).

`_retry_batch_per_record` logged `exc_info=True` once per failed record. The
exception it renders is the insert that just failed, so the rendering carries
the statement and its bound parameters — one of which is the generated vector —
and a full traceback through asyncpg, greenlet and the ORM flush. Measured, one
such rendering costs 964 ms and 60.6 KiB of output under the dev console
renderer and 3.1 ms and 12.7 KiB under the JSON renderer production uses. Once
per record, on a path reached whenever a batch insert fails (#1533) and
therefore usually failing every record in the batch, that is the slowest part of
the whole run, and it buries the one thing an operator went to the logs for.

What these tests hold:

  - the run's log volume grows by a small constant per failed record, not by a
    traceback (the property; measured through the app's own JSON renderer);
  - one traceback per distinct exception type per run, shared between the batch
    handler and the per-record handler;
  - the per-record line still names the record, the exception type and what went
    wrong, and carries neither the statement nor the vector.

Unit tests using mocks — no running database required.
"""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from sqlalchemy.exc import DBAPIError

from tests._logging_state import configured_logging

# A vector wide enough to be recognisable in a rendered SQL parameter list, and
# narrow enough to keep the fixture readable. The real one is 1536 floats.
_VECTOR_LITERAL = "[" + ",".join(f"{0.001 * i:.6f}" for i in range(256)) + "]"

_DRIVER_MESSAGE = (
    "<class 'asyncpg.exceptions.DataError'>: expected 1536 dimensions, not 768"
)


class _DriverError(Exception):
    """Stands in for the asyncpg error SQLAlchemy wraps."""


def _dimension_mismatch() -> DBAPIError:
    """The exception the #1533 failure raises out of the per-record insert.

    Built rather than provoked so the test needs no database, but built with the
    real class and the real shape: driver error, statement, bound parameters with
    the vector among them. `str()` of it is what the old code handed the log
    formatter.
    """
    return DBAPIError(
        "INSERT INTO catalog.record_embeddings (record_id, embedding, "
        "model_name, content_hash) VALUES ($1::UUID, $2, $3::VARCHAR, "
        "$4::VARCHAR) RETURNING catalog.record_embeddings.id",
        (uuid.uuid4(), _VECTOR_LITERAL, "text-embedding-3-small", "0" * 64),
        _DriverError(_DRIVER_MESSAGE),
    )


def _make_record(title="Test Dataset"):
    """A minimal Record double with content that builds a non-empty text."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.title = title
    record.summary = "A geospatial dataset with several feature classes."
    record.lineage_summary = None
    record.keywords = []
    return record


def _make_query_result(records):
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = records
    return result


def _patch_backfill_gates(stack: ExitStack) -> None:
    """Patch the run-level PersistentConfig gates, as the sibling suite does."""
    from app.core.persistent_config import EMBEDDING_MODEL
    from app.processing.embeddings import backfill as backfill_module

    stack.enter_context(
        patch.object(backfill_module.AI_ENABLED, "get", AsyncMock(return_value=True))
    )
    stack.enter_context(
        patch.object(EMBEDDING_MODEL, "get", AsyncMock(return_value="test-model"))
    )
    stack.enter_context(
        patch.object(
            backfill_module.EMBEDDING_DIMS, "get", AsyncMock(return_value=1536)
        )
    )


async def _run_with_failing_commit(n_records: int, commit_error_factory):
    """Drive a full run of `n_records` where every insert fails on commit.

    The provider answers normally; the batch commit raises, so the run falls into
    the per-record retry, where each record's commit raises in turn. That is the
    #1533 shape and the one that made this expensive.
    """
    from app.processing.embeddings.backfill import backfill_embeddings

    records = [_make_record(title=f"Dataset {i}") for i in range(n_records)]

    def _fail(*_args, **_kwargs):
        # `side_effect` raises only what it IS, not what it returns, so the
        # factory's exception has to be raised here. Returning it instead makes
        # every commit succeed and every assertion below pass vacuously.
        raise commit_error_factory()

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_query_result(records))
    session.commit = AsyncMock(side_effect=_fail)

    with ExitStack() as stack:
        _patch_backfill_gates(stack)
        mock_batch = stack.enter_context(
            patch(
                "app.processing.embeddings.backfill.generate_embeddings_batch",
                new_callable=AsyncMock,
            )
        )
        mock_batch.side_effect = lambda texts, *a, **kw: [[0.1] * 1536] * len(texts)
        return await backfill_embeddings(session)


@pytest.mark.asyncio
async def test_log_volume_per_failed_record_stays_small():
    """The property: a run's log output grows by a line per failure, not a traceback.

    Measured against the app's own JSON renderer — the production posture, and
    the one #1544 said had never been sized — by running the same failure at two
    record counts and taking the slope. A traceback per record puts that slope
    around 12 KiB; a compact line puts it under a few hundred bytes.

    The slope is what is asserted rather than the total, because the total also
    contains the run's fixed lines (start, progress, complete) and the single
    traceback the run is still allowed to spend. Those are constants and cancel.

    Only the backfill module's own lines are counted. The mocked session hands
    `PersistentConfig` a `MagicMock` where a settings row would be, so each drift
    check logs a validation failure that a real database never produces; leaving
    those in would measure the test double.
    """
    import io
    import json
    import logging

    def _backfill_bytes(rendered: str) -> int:
        total = 0
        for line in rendered.splitlines():
            event = json.loads(line)
            if event.get("logger") == "app.processing.embeddings.backfill":
                total += len(line)
        return total

    sizes = {}
    for n_records in (4, 24):
        with configured_logging(json_logs=True, log_level="INFO"):
            sink = io.StringIO()
            logging.getLogger().handlers[0].setStream(sink)
            await _run_with_failing_commit(n_records, _dimension_mismatch)
            sizes[n_records] = _backfill_bytes(sink.getvalue())

    per_record = (sizes[24] - sizes[4]) / 20
    assert per_record < 1024, (
        f"each additional failed record adds {per_record:.0f} bytes of log output "
        f"(4 records -> {sizes[4]} bytes, 24 -> {sizes[24]}); a traceback per record "
        "costs about 2.9 KiB with this test's shallow stack and about 12 KiB with "
        "the real one, against roughly 350 bytes for a compact line"
    )


@pytest.mark.asyncio
async def test_one_traceback_for_a_run_of_identical_failures():
    """Twelve failures of one type spend one traceback between all of them."""
    with structlog.testing.capture_logs() as captured:
        result = await _run_with_failing_commit(12, _dimension_mismatch)

    assert result["errors"] == 12, result

    per_record = [
        event
        for event in captured
        if event["event"] == "Backfill: error processing record"
    ]
    assert len(per_record) == 12, "one line per failed record"

    with_traceback = [event for event in captured if event.get("exc_info")]
    assert len(with_traceback) == 1, (
        "expected exactly one traceback for the run, got "
        f"{[event['event'] for event in with_traceback]}"
    )
    # It is the batch handler that sees the type first, so it is the one that
    # spends it; every per-record line after that is compact.
    assert (
        with_traceback[0]["event"]
        == "Backfill: batch failed, retrying records individually"
    )
    assert all(event["exc_info"] is False for event in per_record)


@pytest.mark.asyncio
async def test_a_second_failure_mode_gets_its_own_traceback():
    """The counterfactual for the test above: suppression is per type, not blanket.

    A budget of one traceback per RUN would hide the second failure mode
    entirely. Two types among the same records must produce two tracebacks, and
    no more.
    """
    errors = [_dimension_mismatch() for _ in range(6)]
    errors[3] = RuntimeError("provider refused the input")
    errors[4] = RuntimeError("provider refused the input")
    # +1 for the batch commit that opens the retry path.
    sequence = iter([_dimension_mismatch(), *errors])

    with structlog.testing.capture_logs() as captured:
        await _run_with_failing_commit(6, lambda: next(sequence))

    with_traceback = [event for event in captured if event.get("exc_info")]
    assert len(with_traceback) == 2, [event["error_type"] for event in with_traceback]
    assert {event["error_type"] for event in with_traceback} == {
        "sqlalchemy.exc.DBAPIError",
        "builtins.RuntimeError",
    }


@pytest.mark.asyncio
async def test_per_record_line_names_the_failure_without_the_vector():
    """The compact line has to stay useful: what failed, on which record, why."""
    records_seen = []

    with structlog.testing.capture_logs() as captured:
        await _run_with_failing_commit(3, _dimension_mismatch)

    per_record = [
        event
        for event in captured
        if event["event"] == "Backfill: error processing record"
    ]
    assert len(per_record) == 3

    for event in per_record:
        records_seen.append(event["record_id"])
        assert event["error_type"] == "sqlalchemy.exc.DBAPIError"
        assert "expected 1536 dimensions, not 768" in event["error"]
        assert "[SQL:" not in event["error"]
        assert "0.001000,0.002000" not in event["error"]
        assert len(event["error"]) <= 200

    assert len(set(records_seen)) == 3, "each line names its own record"

    # Counterfactual: those assertions are only worth something because the
    # rendering the old code handed the formatter really does carry both.
    rendered = str(_dimension_mismatch())
    assert "[SQL:" in rendered
    assert "0.001000,0.002000" in rendered


def test_compact_error_redacts_a_credential_in_an_endpoint():
    """A provider error names its endpoint, and an endpoint can carry a key."""
    from app.processing.embeddings.backfill import _compact_error

    exc = RuntimeError(
        "embedding request failed: POST "
        "https://embeddings.example.com/v1/embeddings?api_key=hunter2 returned 401"
    )
    compact = _compact_error(exc)

    assert "hunter2" not in compact
    assert "embeddings.example.com" in compact, "the endpoint itself is still useful"
    # Counterfactual: the secret is genuinely in the message being logged.
    assert "hunter2" in str(exc)


def test_compact_error_truncates_a_long_message():
    """Whatever the exception, one log line stays one log line."""
    from app.processing.embeddings.backfill import _compact_error

    compact = _compact_error(RuntimeError("x" * 5000))

    assert len(compact) == 200
    assert compact.endswith("...")
