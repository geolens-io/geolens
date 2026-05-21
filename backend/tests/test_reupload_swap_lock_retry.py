"""Regression test for ING-06 / P2-08: ``_apply_reupload_swap`` must retry once on lock_timeout failure.

Background — see ``.planning/audits/INGEST-AUDIT-2026-05-21.md`` P2-08:
``_apply_reupload_swap`` ran ``SET LOCAL lock_timeout = '5s'`` before three
``ALTER TABLE ... RENAME TO`` statements. Under autovacuum contention on
large tables the AccessExclusiveLock acquire failed at the 5s mark, AFTER
staging had been loaded — surfacing a late, user-visible failure.

Fix: on ``LockNotAvailableError`` (SQLSTATE 55P03), retry exactly ONCE
with ``SET LOCAL lock_timeout = '15s'`` plus a 200ms sleep. Log a WARNING
event on contention + an INFO event on retry success.
"""

import types
import uuid
from unittest.mock import patch

import pytest
import structlog
from asyncpg.exceptions import LockNotAvailableError
from sqlalchemy import text

from app.processing.ingest.tasks_common import (
    _apply_reupload_swap,
    _is_lock_timeout_error,
)


class TestIsLockTimeoutError:
    """Pure helper unit tests — no DB needed."""

    def test_detects_direct_asyncpg_exception(self) -> None:
        """Direct ``LockNotAvailableError`` instances are detected."""
        exc = LockNotAvailableError("locked")
        assert _is_lock_timeout_error(exc) is True

    def test_detects_sqlalchemy_wrapped(self) -> None:
        """A SQLAlchemy-style wrapper exposing ``.orig.sqlstate == '55P03'`` is detected."""
        wrapped = types.SimpleNamespace(
            orig=types.SimpleNamespace(sqlstate="55P03"),
        )
        # Cast to ``BaseException`` shape via a real exception with the orig attribute
        exc = RuntimeError("wrapped")
        exc.orig = wrapped.orig  # type: ignore[attr-defined]
        assert _is_lock_timeout_error(exc) is True

    def test_returns_false_for_unrelated(self) -> None:
        """Random exceptions and other SQLSTATE codes do not trigger retry."""
        assert _is_lock_timeout_error(ValueError("nope")) is False

        # Different sqlstate — e.g., unique violation
        exc = RuntimeError("other")
        exc.orig = types.SimpleNamespace(sqlstate="23505")  # type: ignore[attr-defined]
        assert _is_lock_timeout_error(exc) is False

        # Wrapper with no ``.orig`` attribute at all
        assert _is_lock_timeout_error(RuntimeError("bare")) is False


# ---------------------------------------------------------------------------
# DB-touching tests for the retry path itself.
# ---------------------------------------------------------------------------


def _make_dataset_stub(table_name: str):
    """Build a minimal dataset object satisfying the attributes ``_apply_reupload_swap`` reads."""
    record = types.SimpleNamespace(
        spatial_extent=None,
        updated_by=None,
    )
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        record=record,
        record_id=uuid.uuid4(),
        table_name=table_name,
        current_version=1,
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        column_info=[{"name": "name", "type": "character varying"}],
        sample_values={},
        source_format="csv",
        source_filename="orig.csv",
        original_srid=4326,
        source_url=None,
        quality_detail=None,
    )


def _minimal_metadata():
    return {
        "srid": 4326,
        "geometry_type": "Point",
        "feature_count": 1,
        "extent_wkt": None,
        "column_info": [{"name": "name", "type": "character varying"}],
    }


class TestApplyReuploadSwapRetry:
    """Exercise the swap retry behavior on a real test DB session."""

    @pytest.fixture(autouse=True)
    async def setup_tables(self, test_db_session):
        """Create a unique live + staging table pair for each test."""
        self.session = test_db_session
        suffix = uuid.uuid4().hex[:8]
        self.live = f"swap_live_{suffix}"
        self.staging = f"swap_staging_{suffix}"

        for tn in (self.live, self.staging, f"{self.live}_old"):
            await self.session.execute(
                text(f'DROP TABLE IF EXISTS data."{tn}" CASCADE')
            )
        await self.session.commit()

        # Build matching schemas; staging row is the post-swap winner.
        await self.session.execute(
            text(
                f'CREATE TABLE data."{self.live}" '
                "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await self.session.execute(
            text(
                f"INSERT INTO data.\"{self.live}\" (name) VALUES ('original')"
            )
        )
        await self.session.execute(
            text(
                f'CREATE TABLE data."{self.staging}" '
                "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await self.session.execute(
            text(
                f"INSERT INTO data.\"{self.staging}\" (name) VALUES ('new_data')"
            )
        )
        await self.session.commit()

        yield

        for tn in (self.live, self.staging, f"{self.live}_old"):
            await self.session.execute(
                text(f'DROP TABLE IF EXISTS data."{tn}" CASCADE')
            )
        await self.session.commit()

    async def test_happy_path_no_retry(self, monkeypatch) -> None:
        """No contention → swap completes silently; neither retry log fires."""
        dataset = _make_dataset_stub(self.live)

        # Bypass downstream metadata writes that need real ORM objects.
        async def _noop_refresh(*args, **kwargs):
            return None

        async def _noop_quality(*args, **kwargs):
            return {"score": 0.0, "issues": []}

        async def _noop_audit(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "app.processing.ingest.metadata.refresh_attribute_metadata",
            _noop_refresh,
        )
        monkeypatch.setattr(
            "app.processing.ingest.metadata.compute_quality_score",
            _noop_quality,
        )
        monkeypatch.setattr(
            "app.modules.audit.service.audit_emit",
            _noop_audit,
        )

        # Stub the DatasetVersion ORM so `session.add(...)` is a no-op.
        class _Port:
            @staticmethod
            def get_dataset_version_orm_class():
                return lambda **kwargs: types.SimpleNamespace(**kwargs)

        monkeypatch.setattr(
            "app.platform.extensions.get_processing_port",
            lambda: _Port,
        )
        # ``session.add`` rejects unknown types; swap to a recording shim.
        monkeypatch.setattr(self.session, "add", lambda *a, **kw: None)

        with structlog.testing.capture_logs() as captured:
            await _apply_reupload_swap(
                self.session,
                dataset=dataset,
                staging_table=self.staging,
                metadata=_minimal_metadata(),
                sample_values={},
                user_id=str(uuid.uuid4()),
                source_filename="x.csv",
                source_format="csv",
                original_srid=4326,
            )

        # No contention/retry events expected on the happy path.
        events = [r.get("event") for r in captured]
        assert "reupload_swap_lock_contention" not in events
        assert "reupload_swap_retry_succeeded" not in events

        # The swap completed: the live table now contains the staging row.
        row = (
            await self.session.execute(
                text(f'SELECT name FROM data."{self.live}"')
            )
        ).scalar_one()
        assert row == "new_data"

        # Staging table is gone (renamed into the live spot).
        staging_exists = (
            await self.session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='data' AND table_name=:tn)"
                ),
                {"tn": self.staging},
            )
        ).scalar()
        assert staging_exists is False

    async def test_retry_path_logs_and_succeeds(self, monkeypatch) -> None:
        """First swap raises ``LockNotAvailableError``; retry succeeds and both logs fire."""
        dataset = _make_dataset_stub(self.live)

        async def _noop_refresh(*args, **kwargs):
            return None

        async def _noop_quality(*args, **kwargs):
            return {"score": 0.0, "issues": []}

        async def _noop_audit(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "app.processing.ingest.metadata.refresh_attribute_metadata",
            _noop_refresh,
        )
        monkeypatch.setattr(
            "app.processing.ingest.metadata.compute_quality_score",
            _noop_quality,
        )
        monkeypatch.setattr(
            "app.modules.audit.service.audit_emit",
            _noop_audit,
        )

        class _Port:
            @staticmethod
            def get_dataset_version_orm_class():
                return lambda **kwargs: types.SimpleNamespace(**kwargs)

        monkeypatch.setattr(
            "app.platform.extensions.get_processing_port",
            lambda: _Port,
        )
        monkeypatch.setattr(self.session, "add", lambda *a, **kw: None)

        # Record asyncio.sleep durations so we can assert the 200ms gap.
        sleep_durations: list[float] = []

        async def _recording_sleep(seconds: float) -> None:
            sleep_durations.append(seconds)
            # Don't actually sleep — keep the test fast.
            return None

        monkeypatch.setattr(
            "app.processing.ingest.tasks_common.asyncio.sleep",
            _recording_sleep,
        )

        # Intercept ``session.execute`` so the first ``ALTER TABLE ... RENAME``
        # call inside ``_swap_with_timeout`` raises ``LockNotAvailableError``.
        original_execute = self.session.execute
        raised = {"once": False}

        async def _flaky_execute(stmt, *args, **kwargs):
            # Only intercept the live-table rename on the first pass.
            # ``_qtable`` produces ``"data"."{name}"`` so we look for the
            # full RENAME-to-_old shape rather than just the table name
            # (which would also match the SELECT EXISTS pre-check).
            sql = str(getattr(stmt, "text", stmt))
            if (
                not raised["once"]
                and f'RENAME TO "{self.live}_old"' in sql
            ):
                raised["once"] = True
                raise LockNotAvailableError("simulated autovacuum contention")
            return await original_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(self.session, "execute", _flaky_execute)

        with structlog.testing.capture_logs() as captured:
            await _apply_reupload_swap(
                self.session,
                dataset=dataset,
                staging_table=self.staging,
                metadata=_minimal_metadata(),
                sample_values={},
                user_id=str(uuid.uuid4()),
                source_filename="x.csv",
                source_format="csv",
                original_srid=4326,
            )

        # The first attempt raised; the retry must have run.
        assert raised["once"] is True, (
            "Test scaffolding bug — flaky_execute never tripped"
        )

        # Exactly one 200ms sleep between attempts.
        assert sleep_durations == [pytest.approx(0.2)], (
            f"Expected one ~0.2s sleep between attempts; got {sleep_durations!r}"
        )

        # Both structured events fire, with the documented fields.
        contention_events = [
            r for r in captured if r.get("event") == "reupload_swap_lock_contention"
        ]
        success_events = [
            r for r in captured if r.get("event") == "reupload_swap_retry_succeeded"
        ]
        assert len(contention_events) == 1, (
            f"Expected one reupload_swap_lock_contention event; got: {captured}"
        )
        assert len(success_events) == 1, (
            f"Expected one reupload_swap_retry_succeeded event; got: {captured}"
        )

        contention = contention_events[0]
        assert contention["log_level"] == "warning"
        assert contention["table_name"] == self.live
        assert contention["attempt"] == 1
        assert contention["first_timeout_seconds"] == 5
        assert contention["retry_timeout_seconds"] == 15
        assert contention["sleep_ms"] == 200
        assert "autovacuum" in contention["hint"].lower()

        success = success_events[0]
        assert success["log_level"] == "info"
        assert success["table_name"] == self.live
        assert success["attempt"] == 2
        assert success["retry_timeout_seconds"] == 15

        # And the swap really did complete: live table holds the new row.
        row = (
            await self.session.execute(
                text(f'SELECT name FROM data."{self.live}"')
            )
        ).scalar_one()
        assert row == "new_data"
