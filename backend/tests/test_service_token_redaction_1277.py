"""A service token must not survive a failed refresh in any sink (#1277).

ADR-002 invariant 4 says the credential never lands in a committed row. The
credential handoff (#1220) delivered that for the paths that HANDLE the token —
task arguments, user_metadata, the run row — and left one open, because the
token does not only travel as data: for ArcGIS it is a query parameter of the
ESRIJSON source URL that ogr2ogr is invoked with. GDAL echoes the source it
failed on, `run_ogr2ogr_service` embedded that stderr verbatim in its
exception, and the failure handler fanned that exception out to four durable
places at once.

So the property under test is stated as a sweep rather than a path: after a
failed credentialed refresh, the token value appears in NONE of

    - ``ingest_jobs.error_message``           (a durable row)
    - ``dataset_refresh_runs.error_message``  (a durable row that outlives it)
    - the ingest-failed notification's reason (leaves the instance entirely)
    - the emitted log record                  (durable wherever logs ship)

and the diagnostic remainder of the message survives all four, because a
redaction that eats the error is a different bug rather than a fix.

Both doors are covered. The re-upload commit door still passes its token as a
durable task argument, so it reached the same sinks by the same route — a
pre-existing leak, closed here rather than left for the door that happens to
be newer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.url_redaction import (
    REDACTED_SECRET,
    redact_url_credentials,
    scrub_secret_from_exception,
    scrub_secret_value,
)
from app.platform.jobs.models import IngestJob
from app.platform.refresh import credentials as creds
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.tasks import reupload_service
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_ARCGIS_BASE = "https://services.example.com/arcgis/rest/services/Parcels/FeatureServer"
# Contains characters urlencode percent-encodes, so the raw and encoded forms
# differ — the whole point of the encoded-variant coverage below.
_TOKEN = "AAPK/secret+value=="

# What GDAL actually gives back: the failing source URL, token and all, wrapped
# in a message whose remainder is the only useful part.
_STDERR_ECHO = (
    "ERROR 1: HTTP error code : 400 - "
    f"ESRIJSON:{_ARCGIS_BASE}/0/query?f=json&where=1%3D1&token={_TOKEN} "
    "\nERROR 1: Unable to open datasource"
)


# ---------------------------------------------------------------------------
# The scrubbers, in isolation
# ---------------------------------------------------------------------------


class TestScrubSecretValue:
    def test_the_raw_value_is_replaced(self) -> None:
        assert scrub_secret_value(f"failed with {_TOKEN} inside", _TOKEN) == (
            f"failed with {REDACTED_SECRET} inside"
        )

    def test_the_percent_encoded_value_is_replaced(self) -> None:
        """The form the credential actually takes in the ESRIJSON URL.

        ``build_gdal_source`` composes the query with ``urlencode``, so a token
        containing ``/`` or ``+`` reaches the subprocess — and therefore GDAL's
        stderr — encoded. Scrubbing only the raw form would leave exactly those
        tokens exposed.
        """
        from urllib.parse import quote, quote_plus

        encoded = quote(_TOKEN, safe="")
        assert encoded != _TOKEN
        assert _TOKEN not in scrub_secret_value(f"url?token={encoded}", _TOKEN)
        assert REDACTED_SECRET in scrub_secret_value(f"url?token={encoded}", _TOKEN)

        plus_encoded = quote_plus(_TOKEN)
        assert _TOKEN not in scrub_secret_value(f"url?token={plus_encoded}", _TOKEN)

    def test_surrounding_text_survives(self) -> None:
        """A redaction that eats the error is a different bug, not a fix."""
        scrubbed = scrub_secret_value(_STDERR_ECHO, _TOKEN)
        assert _TOKEN not in scrubbed
        assert "HTTP error code : 400" in scrubbed
        assert "Unable to open datasource" in scrubbed

    def test_no_secret_is_a_no_op(self) -> None:
        assert scrub_secret_value("untouched", None) == "untouched"
        assert scrub_secret_value("untouched", "") == "untouched"


class TestScrubSecretFromException:
    def test_the_class_and_cause_survive_the_scrub(self) -> None:
        """The type is load-bearing — the WFS retry and the error-code map
        both dispatch on it, so a replacement exception would break them."""
        cause = ValueError("root")
        exc = IngestionError(f"ogr2ogr failed: token={_TOKEN}")
        exc.__cause__ = cause

        scrub_secret_from_exception(exc, _TOKEN)

        assert isinstance(exc, IngestionError)
        assert exc.__cause__ is cause
        assert _TOKEN not in str(exc)
        assert "ogr2ogr failed" in str(exc)

    def test_non_string_args_are_left_alone(self) -> None:
        exc = IngestionError(f"boom {_TOKEN}", 42)
        scrub_secret_from_exception(exc, _TOKEN)
        assert exc.args[1] == 42
        assert _TOKEN not in exc.args[0]


class TestOgrErrorComposition:
    def test_the_redactor_handles_the_stderr_shape(self) -> None:
        """Redacted where the text becomes an exception, not at each sink.

        Pattern-based, so it covers a token this process never held — which is
        the re-upload commit door's case, and any future caller's.
        """
        composed = redact_url_credentials(_STDERR_ECHO)
        assert _TOKEN not in composed
        assert "HTTP error code : 400" in composed
        assert "Unable to open datasource" in composed

    def test_the_failure_raise_goes_through_the_redactor(self) -> None:
        """That the redactor works says nothing about it being called.

        Structural because the behavioural version would have to stand up a
        fake ogr2ogr subprocess to reach the one branch: this asserts the
        composed message is built from the redacted stderr rather than the raw
        capture, which is the property the sink tests then rely on.
        """
        import inspect

        from app.processing.ingest import ogr

        source = inspect.getsource(ogr.run_ogr2ogr_service)
        raise_site = source[source.index("if proc.returncode != 0:") :]
        assert "redact_url_credentials(stripped.strip())" in raise_site
        assert "{stripped.strip()}" not in raise_site


# ---------------------------------------------------------------------------
# The sinks, driven through the real worker
# ---------------------------------------------------------------------------


async def _seed(session, *, source_url: str):
    user_id = await get_user_id(session, "admin")
    dataset = await _create_dataset(
        session, created_by=user_id, source_format="arcgis_featureserver"
    )
    job = IngestJob(
        dataset_id=dataset.id,
        source_filename="Parcels",
        source_url=source_url,
        source_layer="",
        created_by=user_id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset.id),
            "service_type": "ArcGIS FeatureServer",
            "layer_id": 0,
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="api",
        triggered_by=user_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
    )
    await session.commit()
    return dataset, job


async def _run_failing_refresh(job, dataset, *, token=None, credential_ref=None):
    """Drive reupload_service to failure and capture every sink.

    Returns ``(notification_reasons, log_output)``; the durable rows are read
    by the caller from its own session.
    """

    async def _explode(*args, **kwargs):
        if kwargs.get("on_spawn"):
            kwargs["on_spawn"]()
        raise IngestionError(f"ogr2ogr failed (exit 1): {_STDERR_ECHO}")

    reasons: list[str | None] = []

    async def _capture_emit(*, event_key, build):
        notification = build()
        reasons.append((notification.data or {}).get("reason"))

    with (
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service",
            side_effect=_explode,
        ),
        patch(
            "app.processing.ingest.tasks_common.run_ogr2ogr_service",
            side_effect=_explode,
            create=True,
        ),
        patch(
            "app.platform.notifications.events.emit_event_safe",
            side_effect=_capture_emit,
        ),
        patch(
            "app.modules.catalog.sources.security.validate_url_for_ssrf",
            AsyncMock(),
        ),
    ):
        with pytest.raises(Exception):
            await reupload_service(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                source_url=job.source_url,
                source_layer="",
                user_id=str(job.created_by),
                attempt_id=str(job.attempt_id),
                token=token,
                credential_ref=credential_ref,
            )
    return reasons


async def _assert_no_sink_holds_the_token(session, job, dataset, reasons) -> None:
    """The sweep. Every sink, plus the diagnostic-survival counter-check."""
    refreshed = (
        await session.execute(select(IngestJob).where(IngestJob.id == job.id))
    ).scalar_one()
    await session.refresh(refreshed)
    run = (
        await session.execute(
            select(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset.id)
        )
    ).scalar_one()
    await session.refresh(run)

    assert refreshed.error_message, "the job must still record WHY it failed"
    for sink_name, text in (
        ("ingest_jobs.error_message", refreshed.error_message),
        ("dataset_refresh_runs.error_message", run.error_message or ""),
        ("notification reason", " ".join(r or "" for r in reasons)),
    ):
        assert _TOKEN not in text, f"token leaked into {sink_name}: {text!r}"

    # ...and the message is still worth reading.
    assert "HTTP error code : 400" in refreshed.error_message
    assert reasons, "the ingest-failed notification must still be emitted"


class TestNoSinkHoldsTheToken:
    async def test_credentialed_refresh_failure_leaks_nothing(
        self, client, test_db_session, monkeypatch
    ) -> None:
        """The #1220 door: the token arrives through the single-use store."""
        dataset, job = await _seed(test_db_session, source_url=_ARCGIS_BASE)

        class _Backend:
            def __init__(self) -> None:
                self.store: dict[str, str] = {}

            async def put(self, key, value, ttl_seconds):
                self.store[key] = value

            async def take(self, key):
                return self.store.pop(key, None)

        creds.set_credential_backend(_Backend())
        try:
            ref = await creds.stash_service_credential(_TOKEN)
            reasons = await _run_failing_refresh(job, dataset, credential_ref=ref)
        finally:
            creds.set_credential_backend(None)

        await _assert_no_sink_holds_the_token(test_db_session, job, dataset, reasons)

    async def test_legacy_reupload_failure_leaks_nothing_either(
        self, client, test_db_session
    ) -> None:
        """The commit door, whose token is still a durable task argument.

        Pre-existing and closed here: its token rides the same GDAL URL and
        its failures flow through the same sinks, so leaving it would have
        fixed the newer door and left the older one leaking.
        """
        dataset, job = await _seed(test_db_session, source_url=_ARCGIS_BASE)
        reasons = await _run_failing_refresh(job, dataset, token=_TOKEN)
        await _assert_no_sink_holds_the_token(test_db_session, job, dataset, reasons)


class TestLogSinkIsRedacted:
    async def test_the_failure_log_carries_no_token(
        self, client, test_db_session, capsys
    ) -> None:
        """The log is the sink the durable-row redaction alone would miss.

        ``_cleanup_staging_on_failure`` logs with ``.exception()``, so the
        record renders the ACTIVE exception's traceback rather than the
        already-redacted ``error_message`` string. Only scrubbing the
        exception itself reaches it — which is why the exact-value pass exists
        alongside the pattern one.
        """
        from tests._logging_state import configured_logging

        dataset, job = await _seed(test_db_session, source_url=_ARCGIS_BASE)
        with configured_logging(log_level="DEBUG"):
            await _run_failing_refresh(job, dataset, token=_TOKEN)
            emitted = capsys.readouterr()

        combined = emitted.out + emitted.err
        assert _TOKEN not in combined
        assert str(job.id) in combined, "the failure must still be logged at all"
