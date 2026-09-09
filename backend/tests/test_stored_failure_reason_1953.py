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

    def test_a_wrapper_around_gdal_stderr_loses_the_libpq_password(self) -> None:
        """Being defined under ``app.`` does not make the text ours: ogr.py
        builds ``IngestionError`` from stderr, and GDAL echoes the ``PG:``
        destination it was handed on a connection failure."""
        for rendered in ("password=hunter2", "password='hunt er2'"):
            reason = redact_failure_reason(
                IngestionError(
                    "ogr2ogr failed (exit 1): ERROR 1: Unable to connect: "
                    f"PG:host=db port=5432 dbname=geolens user=gl {rendered} "
                    "sslmode=require"
                )
            )
            assert "hunter2" not in reason
            assert "hunt er2" not in reason
            assert "password=<redacted>" in reason
            assert "geolens" not in reason, "the topology goes with the secret"

    def test_a_one_line_gdal_echo_keeps_no_path_and_no_topology(self) -> None:
        """The whole leak fits on one line, so the summary cut removes none of
        it. Being defined under ``app.`` says who raised the exception, never
        that its message is free of the subprocess output it was built from."""
        reason = redact_failure_reason(
            IngestionError(
                "ogr2ogr -f PostgreSQL PG:host=db port=5432 dbname=geolens "
                "user=gl password=hunter2 /app/staging/9f2_roads.gpkg"
            )
        )

        assert "hunter2" not in reason
        for keyword in ("host", "port", "dbname", "user", "password"):
            assert f"{keyword}=<redacted>" in reason
        assert "geolens" not in reason
        assert "/app/staging" not in reason
        assert "9f2_roads.gpkg" not in reason

    def test_a_vsi_handle_is_a_path_too(self) -> None:
        reason = redact_failure_reason(
            IngestionError("ERROR 1: Cannot open /vsis3/geolens-data/r/abc.tif")
        )

        assert reason == "ERROR 1: Cannot open <redacted>"

    def test_a_url_in_a_composed_message_keeps_its_path(self) -> None:
        """The path masking's negative control: a manifest download names its
        source, and a URL's slashes follow a host rather than a space."""
        assert redact_failure_reason(
            "Failed to download manifest source: https://example.com/a/b.gpkg timed out"
        ) == (
            "Failed to download manifest source: https://example.com/a/b.gpkg timed out"
        )

    def test_a_credential_broken_across_a_line_is_still_masked(self) -> None:
        """Choosing the summary line first would hand the scrubbers a URL cut
        in half, and half a URL keeps its password."""
        assert "hunter2" not in redact_failure_reason("https://user:hunter2\n@[::1")
        assert "hunt er2" not in redact_failure_reason(
            "ERROR 1: PG:host=db password='hunt\ner2' dbname=x"
        )

    def test_a_tab_in_the_summary_is_not_read_as_a_straddling_credential(
        self,
    ) -> None:
        """The cross-check's negative control. ``urlsplit`` deletes tabs as
        well as line breaks, so comparing raw text would refuse this line."""
        assert redact_failure_reason("ERROR 1:\tCannot open\n[SQL: SELECT 1]") == (
            "ERROR 1:Cannot open"
        )

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
        # The upload size refusal, which reaches the user through the dialog.
        assert is_composed_exception(ValueError("File size (9.0 MB) exceeds"))
        assert not is_composed_exception(_driver_error())
        assert not is_composed_exception(RuntimeError("osgeo raises these"))

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


_SANCTIONED_REDACTORS = frozenset(
    {
        "redact_failure_reason",
        "redact_run_error",
        "coded_failure_reason",
        # analysis/tasks.py's SQLSTATE-to-sentence mapper, the same argument
        # made for the PostGIS strategy in ADR-002 Decision 3.
        "_user_error_message",
    }
)


# The sinks that redact what they are handed, and where each keeps its
# message. A caller may pass the exception, never a rendering of it: once it
# has been interpolated the sink can no longer tell whose text it is.
_REDACTING_SINKS: dict[str, str | int] = {
    "record_refresh_failure": "error_message",
    "release_manifest_reservation": 2,
}


def _sink_message(node: ast.Call, where: str | int) -> ast.expr | None:
    if isinstance(where, int):
        return node.args[where] if len(node.args) > where else None
    return next((kw.value for kw in node.keywords if kw.arg == where), None)


def _reason_values(tree: ast.AST) -> list[tuple[ast.expr, str | None]]:
    """Every expression that becomes an ``error_message``, with its callee."""
    values: list[tuple[ast.expr, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func.id if isinstance(node.func, ast.Name) else None
            values += [
                (kw.value, callee) for kw in node.keywords if kw.arg == "error_message"
            ]
            where = _REDACTING_SINKS.get(callee or "")
            if where is not None and where != "error_message":
                message = _sink_message(node, where)
                if message is not None:
                    values.append((message, callee))
        elif isinstance(node, ast.Dict):
            values += [
                (value, None)
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and key.value == "error_message"
            ]
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                named = isinstance(target, ast.Name) and target.id == "error_message"
                attr = (
                    isinstance(target, ast.Attribute) and target.attr == "error_message"
                )
                if named or attr:
                    values.append((node.value, None))
    return values


def _redacted_locals(tree: ast.AST) -> set[str]:
    """Names a module binds from a sanctioned redactor."""
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and _call_names(node.value) & _SANCTIONED_REDACTORS
        for target in node.targets
        if isinstance(target, ast.Name)
    }


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

    def test_no_writer_anywhere_puts_an_exception_into_a_reason(self) -> None:
        """The gate codex round 1 asked for: enumerate, do not list.

        Every `error_message` value in `backend/app/` must reach a sanctioned
        redactor, be a name this module already redacted, or be a fixed
        constant. Round 2 removed the bare-name exemption: the manifest
        reservation was handed one composed from an exception.
        """
        offenders: list[str] = []
        for module in sorted(_APP.rglob("*.py")):
            tree = ast.parse(module.read_text())
            caught = {
                handler.name
                for handler in ast.walk(tree)
                if isinstance(handler, ast.ExceptHandler) and handler.name
            }
            safe_locals = _redacted_locals(tree)
            for value, callee in _reason_values(tree):
                if _call_names(value) & _SANCTIONED_REDACTORS:
                    continue
                if isinstance(value, ast.Name):
                    if (
                        callee in _REDACTING_SINKS
                        or value.id in safe_locals
                        or value.id.isupper()
                    ):
                        continue
                elif (
                    not {
                        node.id
                        for node in ast.walk(value)
                        if isinstance(node, ast.Name)
                    }
                    & caught
                ):
                    continue
                offenders.append(
                    f"{module.relative_to(_APP)}:{value.lineno} "
                    f"{ast.unparse(value)[:60]}"
                )
        assert not offenders, offenders

    def test_the_gate_above_can_see_a_violation(self) -> None:
        """Its positive control: the shape it hunts, parsed the same way."""
        tree = ast.parse(
            "try:\n    pass\n"
            "except Exception as exc:\n"
            "    job.error_message = str(exc)\n"
        )
        caught = {
            handler.name
            for handler in ast.walk(tree)
            if isinstance(handler, ast.ExceptHandler) and handler.name
        }
        values = _reason_values(tree)
        assert len(values) == 1
        value, callee = values[0]
        assert callee not in _REDACTING_SINKS
        assert {n.id for n in ast.walk(value) if isinstance(n, ast.Name)} & caught
        assert not _call_names(value) & _SANCTIONED_REDACTORS
        assert not _redacted_locals(tree)

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
