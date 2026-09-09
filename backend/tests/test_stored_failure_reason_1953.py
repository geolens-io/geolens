"""ADR-002 Decision 3's raw-exception clause, at the sinks (#1953).

The clause was two-thirds enforced: credentials and length were handled, a
raw exception was not. #1947 stored a `DBAPIError` rendering carrying a
statement and its bound parameters into both a run row and the ingest job
the re-upload dialog renders.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.failure_reason import (
    INTERNAL_FAILURE_REASON,
    MAX_REASON_CHARS,
    coded_failure_reason,
    is_composed_exception,
    redact_failure_reason,
)
from app.processing.ingest.ogr import IngestionError

_APP = Path(__file__).resolve().parents[1] / "app"
_STATEMENT = "SELECT id FROM catalog.datasets WHERE id = %(dataset_id)s FOR UPDATE"


def _driver_error() -> DBAPIError:
    """The #1947 shape: SQLAlchemy renders the statement and the parameters."""

    class _QueryCanceled(Exception):
        pass

    return DBAPIError.instance(
        _STATEMENT,
        {"dataset_id": "b0a1f2e3-0000-4000-8000-000000000000"},
        _QueryCanceled("canceling statement due to statement timeout"),
        Exception,
    )


class TestTheHelperRefusesWhatDecision3Forbids:
    def test_a_library_exception_becomes_a_code(self) -> None:
        exc = _driver_error()
        assert _STATEMENT in str(exc), "precondition: the payload is in the rendering"

        reason = redact_failure_reason(exc)

        assert reason == INTERNAL_FAILURE_REASON
        assert "SELECT" not in reason
        assert "parameters" not in reason

    def test_flattened_exception_text_loses_its_payload(self) -> None:
        """The door a caller reaches with ``str(exc)`` already applied."""
        reason = redact_failure_reason(str(_driver_error()))

        assert reason.endswith("canceling statement due to statement timeout")
        assert "[SQL:" not in reason
        assert "[parameters:" not in reason
        assert "sqlalche.me" not in reason

    def test_a_message_this_codebase_composed_survives(self) -> None:
        """The refusal half needs its admission, or a redactor that eats
        everything passes every assertion above."""
        message = "Layer 'parcels' has no geometry column"
        assert redact_failure_reason(IngestionError(message)) == message
        assert redact_failure_reason(message) == message

    def test_gdal_stderr_keeps_only_its_summary_line(self) -> None:
        exc = IngestionError(
            "ogr2ogr failed (exit 1): ERROR 1: Cannot open datasource\n"
            "ogr2ogr -f PostgreSQL PG:dbname=geolens /app/staging/abc_roads.gpkg"
        )
        reason = redact_failure_reason(exc)

        assert reason.endswith("Cannot open datasource")
        assert "/app/staging" not in reason

    def test_credentials_are_still_stripped(self) -> None:
        assert "hunter2" not in redact_failure_reason(
            IngestionError(
                "ogr2ogr failed on https://svc.example/FeatureServer/0?token=hunter2"
            )
        )
        assert "s3cret" not in redact_failure_reason(
            "GDAL error: https://bob:s3cret@svc.example/wfs"
        )

    def test_the_reason_is_capped(self) -> None:
        assert len(redact_failure_reason("x" * 10_000)) == MAX_REASON_CHARS

    def test_provenance_is_the_test_not_the_shape(self) -> None:
        assert is_composed_exception(IngestionError("composed here"))
        assert not is_composed_exception(_driver_error())
        assert not is_composed_exception(ValueError("composed by nobody in particular"))

    def test_a_coded_reason_names_the_class_and_not_the_message(self) -> None:
        reason = coded_failure_reason("Failed to queue refresh task", _driver_error())

        assert reason == "Failed to queue refresh task (DBAPIError)"
        assert _STATEMENT not in reason


def _function(module_path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(module_path.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(found) == 1, f"{name} not found once in {module_path}"
    return found[0]


def _call_names(node: ast.AST) -> set[str]:
    return {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


class TestEverySinkGoesThroughTheOneDoor:
    """Structural, because the failure mode is a NEW caller, not this one.

    Each assertion carries its own positive control: a refactor that moves
    the write out of the function named here fails the lookup rather than
    passing vacuously.
    """

    def test_the_ingest_job_sink_passes_the_exception_not_its_text(self) -> None:
        fn = _function(
            _APP / "processing" / "ingest" / "tasks_common.py",
            "_cleanup_staging_on_failure",
        )
        assigned = [
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "error_message"
                for t in node.targets
            )
        ]
        assert len(assigned) == 1, (
            "the terminal write's reason is composed elsewhere now"
        )
        value = assigned[0].value
        assert isinstance(value, ast.Call)
        assert isinstance(value.func, ast.Name)
        assert value.func.id == "redact_failure_reason"
        assert [a.id for a in value.args if isinstance(a, ast.Name)] == ["exc"]

    def test_every_run_row_reason_goes_through_redact_run_error(self) -> None:
        source = (_APP / "platform" / "refresh" / "service.py").read_text()
        tree = ast.parse(source)
        values = [
            item
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for key, item in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == "error_message"
        ]
        assert len(values) == 3, "the run row's error_message writers moved"
        for value in values:
            if isinstance(value, ast.Name):
                # The sweep's own constant: composed here, nothing to redact.
                assert value.id.endswith("_ERROR_MESSAGE")
                continue
            assert isinstance(value, ast.Call)
            assert isinstance(value.func, ast.Name)
            assert value.func.id == "redact_run_error"

    def test_the_dispatch_rollback_no_longer_interpolates_the_exception(self) -> None:
        fn = _function(
            _APP / "platform" / "refresh" / "service.py",
            "make_refresh_run_failed_rollback",
        )
        assert "coded_failure_reason" in _call_names(fn)
        assert not [node for node in ast.walk(fn) if isinstance(node, ast.JoinedStr)], (
            "an f-string here is how #1947's payload reached the run row"
        )

    def test_the_defer_guard_rollbacks_name_the_type_only(self) -> None:
        source = (_APP / "platform" / "jobs" / "defer_guard.py").read_text()
        tree = ast.parse(source)
        writes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Attribute) and t.attr == "error_message"
                for t in node.targets
            )
        ]
        assert len(writes) == 3, "the job/generation reason writers moved"
        for write in writes:
            assert isinstance(write.value, (ast.Name, ast.Call))
            if isinstance(write.value, ast.Call):
                assert isinstance(write.value.func, ast.Name)
                assert write.value.func.id == "coded_failure_reason"


@pytest.mark.anyio
class TestTheRunRowStoresTheCodeRatherThanTheStatement:
    async def test_a_driver_failure_stores_no_sql(self, test_db_session) -> None:
        from app.platform.jobs.models import IngestJob
        from app.platform.refresh.service import (
            create_pending_run,
            record_refresh_failure,
        )
        from tests.factories import create_dataset, get_user_id

        user_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=user_id,
            name=f"reason-{uuid.uuid4().hex[:8]}",
        )
        job = IngestJob(
            dataset_id=dataset.id,
            status="running",
            source_filename="parcels.gpkg",
            created_by=user_id,
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="postgis",
            trigger="manual",
            triggered_by=user_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await test_db_session.commit()

        assert (
            await record_refresh_failure(
                test_db_session,
                ingest_job_id=job.id,
                error_code="postgis_refresh_failed",
                error_message=_driver_error(),
                contacted_origin=False,
            )
            == run.id
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)

        assert run.status == "failed"
        assert run.error_message == INTERNAL_FAILURE_REASON
        assert "SELECT" not in (run.error_message or "")
