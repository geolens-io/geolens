import asyncio
import os
import time
import uuid
import tempfile
import warnings
from contextlib import asynccontextmanager

import asyncpg.exceptions
import pytest
import sqlalchemy
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError, InvalidRequestError
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.platform.cache import init_cache
from app.core.config import settings

# Captured at module load (and refreshed in pytest_configure) so any test that
# reads it does not race the fixture body's mutation. Defaults to "master" when
# pytest-xdist is not active (sequential `pytest` or `pytest -x` runs).
_WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER", "master")


def _derive_test_pool_sizing() -> tuple[int, int]:
    """Return (pool_size, max_overflow) sized to live within Postgres max_connections.

    Sequential mode (worker_id == "master") keeps the historical (5, 2) pool that
    the suite was built against. Under pytest-xdist, returns (1, 0) as a signal
    value; see _is_xdist_worker() below. The actual engine uses NullPool in xdist
    mode (no persistent idle connections).

    The (5, 2) sequential default is preserved because request handlers in some
    tests (e.g., reupload, IDOR) need >1 concurrent conn within a single test.
    The v1018 sequential baseline (3025/0/38 in 539s) is the regression floor.

    See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for measured numbers + rationale.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker_id == "master":
        return (5, 2)
    # Under xdist: use (1, 0) as a sentinel; the engine creation switches to
    # NullPool which has no persistent idle connections. Connections are only
    # open during active DB operations, minimising the concurrent-connection
    # fan-out across 16 workers against max_connections=30.
    return (1, 0)


def _make_test_async_engine(test_database_url: str):
    """Create the async test engine for this worker.

    xdist workers (PYTEST_XDIST_WORKER != 'master') use NullPool — no idle
    connections persist between tests, keeping concurrent connection count within
    max_connections=30 when 16 workers run simultaneously.

    Sequential mode uses the historical (5, 2) QueuePool so request handlers that
    need multiple concurrent DB connections within a single test still work.

    This helper is extracted for direct testability (see test_conftest_pool_sizing.py
    test_xdist_engine_uses_nullpool / test_sequential_engine_uses_queuepool).
    """
    is_xdist = os.environ.get("PYTEST_XDIST_WORKER", "master") != "master"
    if is_xdist:
        # Plan 1093-02 / TEST-01: wrap NullPool engine in _RetryingAsyncEngine
        # so direct engine.connect() / engine.dispose() calls retry on
        # transient contention. See class docstring above.
        return _RetryingAsyncEngine(
            create_async_engine(test_database_url, poolclass=NullPool, echo=False)
        )
    pool_size, max_overflow = _derive_test_pool_sizing()
    # Plan 1093-02 / TEST-01: same wrap for QueuePool sequential branch —
    # symmetric coverage across both pool types.
    return _RetryingAsyncEngine(
        create_async_engine(
            test_database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=30,
            echo=False,
        )
    )


# Per-worker setup stagger — spreads the startup connection spike across time.
#
# Root-cause: when N workers run _test_db_lifecycle simultaneously, each opens
# a sync SQLAlchemy connection to the main DB (dev_engine) PLUS connections to
# their test DB (test_engine_sync, alembic, _saml_bridge_engine). With
# N=16 workers and max_connections=30 (db/postgresql.conf:11), and the running
# API/worker services already holding 8 persistent idle connections, the
# concurrent setup fan-out saturates Postgres before any test runs.
#
# Fix: stagger each worker's startup by SETUP_STAGGER_SECONDS × worker_num.
# Alembic migration (22 steps) takes ≈ 3-5s per worker. With a 5.0s stagger:
#   - Worker 0 starts immediately (no delay)
#   - Worker 1 starts after 5.0s (worker 0 is already past migration)
#   - Worker k starts after k × 5.0s
# Peak concurrent main-DB connections during stagger window: ~1-2.
# Safe under max_connections=30.
#
# This approach is O(STAGGER_SECONDS × worker_num) total overhead vs. O(N × setup_time)
# for a hard serialiser — wall-clock impact is bounded by the LAST worker's stagger
# (15 × 5.0s = 75s), not the sum.
#
# See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for measured numbers + rationale.
# Combined with NullPool for async engines (no idle connections post-setup),
# the fix addresses both the setup-phase spike and the test-phase connection budget.
# Setup phase per worker: dev_engine + test_engine_sync + alembic (22 steps) +
# _saml_bridge_engine ≈ 3-5 seconds total. Stagger must be ≥ setup time so at
# most 1 worker is in the migration phase at any time. Use 5s with some headroom.
# Impact: last worker (gw15) delays 15 × 5 = 75s. Total parallel wall clock:
#   75s (stagger overhead) + ~80s (test execution) ≈ 155s vs sequential 539s.
_SETUP_STAGGER_SECONDS = 5.0


def _get_setup_stagger_delay() -> float:
    """Return the number of seconds this worker should sleep before running setup.

    Sequential mode (master) or unrecognised worker ID returns 0.0 — no stagger needed.
    xdist worker gw0 returns 0.0, gw1 returns 5.0, gw15 returns 75.0.

    Note: if xdist changes its worker ID format (currently 'gwN'), unrecognised
    IDs silently return 0.0, defeating the stagger for those workers.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if not worker_id.startswith("gw"):
        return 0.0
    try:
        worker_num = int(worker_id[2:])
    except ValueError:
        warnings.warn(
            f"Unexpected PYTEST_XDIST_WORKER format: {worker_id!r}; stagger disabled",
            stacklevel=2,
        )
        return 0.0
    return worker_num * _SETUP_STAGGER_SECONDS


def pytest_configure(config):
    """Re-capture the pytest-xdist worker id under config-time hooks.

    pytest-xdist injects ``config.workerinput['workerid']`` (e.g. ``"gw0"``)
    when running parallel workers. Mirror it back into the module-level
    ``_WORKER_ID`` constant + ``PYTEST_XDIST_WORKER`` env var so the
    test-DB naming helper sees a stable value regardless of whether the
    plugin set the env var itself.
    """
    global _WORKER_ID
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        worker_id = workerinput.get("workerid", "master")
        _WORKER_ID = worker_id
        # Mirror into env so any subprocess (or late import) also sees it.
        os.environ["PYTEST_XDIST_WORKER"] = worker_id

# Shared test geometries
EMPTY_FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [],
}

POINT_GEOJSON = {
    "type": "Point",
    "coordinates": [-73.9857, 40.7484],
}

POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]
    ],
}


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def community_edition(monkeypatch):
    from app.core.edition import init_edition

    monkeypatch.delenv("GEOLENS_EDITION", raising=False)
    init_edition([])
    yield
    init_edition([])


@pytest.fixture
def enterprise_edition(monkeypatch):
    from app.core.edition import init_edition

    monkeypatch.delenv("GEOLENS_EDITION", raising=False)
    init_edition(["enterprise"])
    yield
    init_edition([])


def _quote_database_identifier(db_name: str) -> str:
    return '"' + db_name.replace('"', '""') + '"'


def _worker_test_database_name(base_name: str) -> str:
    """Compose a per-worker, per-session test DB name within PG's 63-char limit.

    Layout: ``{safe_base}_{worker_id}_{8-hex-uuid}``

    The worker_id is read fresh from the ``PYTEST_XDIST_WORKER`` env var so
    callers (e.g. the regression test) can manipulate the value via
    ``monkeypatch`` without relying on module-load-time capture. When the
    env var is unset (sequential pytest, ``-x``, IDE runners), the worker_id
    defaults to ``"master"`` — this gives the legacy single-session DB its
    own non-empty namespace token, preventing collisions with concurrent
    xdist runs against the same Postgres server.
    """
    suffix = uuid.uuid4().hex[:8]
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    # Reserve space for `_{worker_id}_{suffix}` in the 63-char identifier budget.
    overhead = len(worker_id) + len(suffix) + 2  # two underscores
    max_base_len = 63 - overhead
    safe_base = (base_name or "geolens_test")[:max_base_len].rstrip("_")
    return f"{safe_base or 'geolens'}_{worker_id}_{suffix}"


def _drop_test_database_if_exists(db_name: str) -> None:
    teardown_engine = sqlalchemy.create_engine(
        settings.database_url_sync, isolation_level="AUTOCOMMIT"
    )
    try:
        with teardown_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db_name AND pid <> pg_backend_pid()"
                ),
                {"db_name": db_name},
            )
            conn.execute(
                text(f"DROP DATABASE IF EXISTS {_quote_database_identifier(db_name)}")
            )
    except Exception:
        pass
    finally:
        teardown_engine.dispose()


# Retry budget for transient "too many clients already" contention during
# per-worker test-DB CREATE. See `_create_test_db_with_retry` and audit
# Section 4.1 (`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`).
_CREATE_DB_RETRY_BACKOFFS = (1.0, 2.0, 4.0)


def _create_test_db_with_retry(
    make_engine_fn,
    quoted_db_name: str,
    sleep_fn=time.sleep,
    backoffs=_CREATE_DB_RETRY_BACKOFFS,
) -> None:
    """DROP + CREATE the per-worker test DB, with retry on transient contention.

    Args:
        make_engine_fn: Zero-arg callable returning a fresh sync SQLAlchemy
            engine bound to the main DB at AUTOCOMMIT. The caller is
            responsible for the engine's lifecycle on the first attempt; this
            helper disposes and recreates the engine on retries so each
            attempt opens a fresh connection (avoids reusing a connection
            that was rejected by Postgres).
        quoted_db_name: Already-quoted-and-escaped identifier (the output of
            `_quote_database_identifier(db_name)`). Pre-quoting keeps this
            helper SQL-injection-safe at the call site.
        sleep_fn: Injected for testability. Production passes `time.sleep`;
            the regression pin patches this to a no-op so retries do not
            actually wait.
        backoffs: Tuple of per-attempt sleep durations (seconds) between
            failed attempts. Length determines retry budget. Total wait
            budget under contention with the default ``(1.0, 2.0, 4.0)`` is
            7s, bounded below the staggered-startup window's 75s ceiling.

    Raises:
        OperationalError: If every attempt raises an OperationalError whose
            message contains ``"too many clients already"``. Re-raised so
            the caller surfaces the contention loudly as a fixture error
            (NOT swallowed silently — that was the v1019 defect at audit
            Section 4.1, 407/648 failures, 62.8% of total).
        OperationalError: Re-raised immediately for any other OperationalError
            (DNS failure, refused connection, authentication, etc.) — the
            caller decides whether to translate that into a `pytest.skip` or
            propagate it.

    The helper opens a context-managed connection per attempt and disposes
    the engine before retrying so the connection pool does not hold any
    rejected connection past the failure point.
    """
    last_exc: OperationalError | None = None
    # Budget = 1 initial attempt + len(backoffs) retries.
    attempt_budget = 1 + len(backoffs)
    for attempt in range(attempt_budget):
        engine = make_engine_fn()
        try:
            with engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_db_name}"))
                conn.execute(text(f"CREATE DATABASE {quoted_db_name}"))
            return
        except OperationalError as e:
            last_exc = e
            # Only retry transient connection-contention errors. Other
            # OperationalError shapes (unreachable host, auth, etc.) propagate
            # immediately so the caller can route them to pytest.skip().
            if "too many clients already" not in str(e).lower():
                raise
            # Exhausted budget — re-raise to fail loudly, NOT silent-swallow.
            if attempt == attempt_budget - 1:
                raise
            sleep_fn(backoffs[attempt])
        finally:
            engine.dispose()
    # Unreachable — the loop either returns or raises. Defensive raise.
    if last_exc is not None:  # pragma: no cover
        raise last_exc


# Retry budget for transient "too many clients already" contention during
# per-fixture async-session setup (e.g., `_ensure_roles_and_admin`). Same
# shape as `_CREATE_DB_RETRY_BACKOFFS` above — bounded below the staggered-
# startup window's 75s ceiling. See Plan 1088-03 and audit Section 4.2
# (`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`).
_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)


# Exception classes that signal transient connection contention worth
# retrying. The async session-factory path can surface the contention as
# EITHER:
#   - `sqlalchemy.exc.OperationalError` (when SQLAlchemy wraps the DBAPI
#     error via its async dialect translation layer), OR
#   - the raw `asyncpg.exceptions.TooManyConnectionsError` /
#     `CannotConnectNowError` (when the asyncpg connection error escapes
#     through the greenlet boundary before SQLAlchemy translates it —
#     observed in 188 setup-phase failures at audit Section 4.2 even with
#     SQLAlchemy 2.x's async dialect).
# Catching BOTH the SQLAlchemy wrapper AND the raw asyncpg classes is
# required for the retry path to actually fire in practice — initial
# Plan 1088-03 measurement showed retry coverage of only ~42% (188 → 109)
# when only `OperationalError` was caught, because the majority of
# contention failures surface as raw asyncpg exceptions through the
# `bind.connect()` → `greenlet_spawn` → asyncpg connection_class path.
_TRANSIENT_CONTENTION_EXCEPTIONS = (
    OperationalError,
    asyncpg.exceptions.TooManyConnectionsError,
    asyncpg.exceptions.CannotConnectNowError,
)


async def _run_with_too_many_clients_retry(
    coro_fn,
    sleep_fn=asyncio.sleep,
    backoffs=_SETUP_PHASE_RETRY_BACKOFFS,
):
    """Run an async fixture-setup callable with retry on transient contention.

    Plan 1088-03 / audit Section 4.2: After Plan 1088-01's silent-swallow
    fix closed the dominant per-worker DB lifecycle race (category 4.1,
    407/648 failures), the residual setup-phase contention category 4.2
    remained at 188 failures (re-measure at
    `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md`). The failure
    shape is identical across all 188 occurrences:

        "failed on setup with 'asyncpg.exceptions.TooManyConnectionsError:
         sorry, too many clients already'"

    Root cause: the `client` fixture's first async-session connection
    acquisition (inside `_ensure_roles_and_admin` at conftest.py:644-691)
    races the connection ceiling. With max_connections=30 and 16 xdist
    workers staggered at 5.0s intervals, the cascade window briefly opens
    when several workers complete the staggered-startup gate simultaneously
    and concurrently request session-factory connections.

    This helper mirrors the shape of `_create_test_db_with_retry` (Plan
    1088-01) but for async callables: it invokes ``coro_fn`` (a zero-arg
    async callable that performs the DB operation), retries on the
    transient contention exception family (`OperationalError`,
    `asyncpg.TooManyConnectionsError`, `asyncpg.CannotConnectNowError`),
    and re-raises after the budget is exhausted — NOT silently swallowed.

    IMPORTANT — exception-family scope (see ``_TRANSIENT_CONTENTION_EXCEPTIONS``
    above the helper): the helper must catch BOTH the SQLAlchemy-wrapped
    OperationalError shape AND the raw asyncpg exception classes. During
    initial Plan 1088-03 measurement, catching only ``OperationalError``
    yielded a retry-coverage rate of ~42% (188 → 109) because the
    majority of contention errors surface as raw
    ``asyncpg.exceptions.TooManyConnectionsError`` through the
    ``bind.connect()`` → ``greenlet_spawn`` path. Widening the catch to
    include the asyncpg classes is what actually closes the 4.2 cascade.

    Args:
        coro_fn: Zero-arg async callable that performs the DB-touching
            setup work (e.g., ``lambda: _ensure_roles_and_admin(factory)``).
            Called fresh on each attempt so the underlying asyncpg
            connection is re-acquired rather than reusing a rejected
            connection.
        sleep_fn: Async sleep injected for testability. Production passes
            ``asyncio.sleep``; the regression pin patches this to a no-op
            so retries do not actually wait.
        backoffs: Tuple of per-attempt sleep durations (seconds) between
            failed attempts. Length determines retry budget. Total wait
            budget under contention with the default ``(1.0, 2.0, 4.0)``
            is 7s, bounded below the staggered-startup window's 75s
            ceiling.

    Raises:
        Exception: If every attempt raises one of
            ``_TRANSIENT_CONTENTION_EXCEPTIONS`` whose message contains
            ``"too many clients already"``, the last exception is re-raised
            so the caller surfaces the contention loudly as a fixture
            error (NOT swallowed silently).
        Exception: Re-raised immediately for any
            ``OperationalError`` whose message does NOT contain
            ``"too many clients already"`` (DNS failure, refused
            connection, authentication, etc.) — non-contention shapes
            propagate so the caller can route them appropriately.
        Exception: Any other exception (non-contention, non-OperationalError)
            propagates immediately on the first attempt.

    The helper is async-native (awaits ``coro_fn()`` and ``sleep_fn(...)``)
    so it integrates cleanly with the existing async `client` fixture
    body. The signature mirrors `_create_test_db_with_retry` so future
    callers (or test pins) have a consistent retry-wrapper API for both
    sync setup work (DDL CREATE/DROP) and async setup work (session
    factories / asyncpg).
    """
    last_exc: BaseException | None = None
    attempt_budget = 1 + len(backoffs)
    for attempt in range(attempt_budget):
        try:
            return await coro_fn()
        except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
            last_exc = e
            # `OperationalError` may carry shapes OTHER than connection
            # contention (e.g., DNS failure, refused connection, auth).
            # Those propagate immediately. The asyncpg-native classes in
            # the tuple (`TooManyConnectionsError`,
            # `CannotConnectNowError`) are unambiguously contention by
            # construction, so the substring check is a no-op for them
            # (asyncpg's own exception name + message both contain the
            # canonical "too many clients already" substring or the
            # equivalent connect-now phrasing).
            if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
                raise
            # Exhausted budget — re-raise loudly, NOT silent-swallow.
            if attempt == attempt_budget - 1:
                raise
            await sleep_fn(backoffs[attempt])
    # Defensive — the loop either returns or raises.
    if last_exc is not None:  # pragma: no cover
        raise last_exc


# Retry budget for transient "too many clients already" contention during
# in-test session-factory acquisition (per-request `override_get_db` ->
# `test_session_factory()`). Distinct from `_SETUP_PHASE_RETRY_BACKOFFS`:
#
# - Setup phase budget (1.0 + 2.0 + 4.0 = 7s): fires ONCE per worker at the
#   `_ensure_roles_and_admin` call; bounded below the 75s staggered-startup
#   window's ceiling.
# - In-test phase budget (0.5 + 1.0 = 1.5s): fires per-request inside a
#   test body; a single test may issue several sequential `TestClient.post`
#   calls, each opening a new connection. The budget MUST be tight or
#   stalls compound across requests within one test. 1.5s is the smallest
#   window that empirically clears the connection-saturation peak (see
#   Plan 1088-04 and audit Section 4.3).
#
# See Plan 1088-04 and audit Section 4.3
# (`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md:1109-1135` +
# Section 5 suggestion at lines 1296-1299).
_IN_TEST_RETRY_BACKOFFS = (0.5, 1.0)


@asynccontextmanager
async def _acquire_test_session_with_retry(
    session_factory,
    sleep_fn=asyncio.sleep,
    backoffs=_IN_TEST_RETRY_BACKOFFS,
):
    """Async-context-manager wrapper for retrying ``test_session_factory()``
    acquisition during in-test request handling.

    Plan 1088-04 / audit Section 4.3: After Plan 1088-03's wrap of
    ``_ensure_roles_and_admin`` closed setup-phase contention (category 4.2,
    188 -> 47, below 50 threshold), residual category 4.3 (in-test
    connection contention, 87 pre-fix -> 172 post-1088-01 -> 137 post-1088-03)
    remained above the 30 threshold. The failure shape: tests internally
    open multiple DB connections within their body (multiple
    ``TestClient.post(...)`` calls), each triggering a fresh
    ``override_get_db`` -> ``test_session_factory()`` connection acquisition
    that races the ``max_connections=30`` ceiling.

    IMPORTANT — lazy-connection contract (see Plan 1088-04 iter-1
    measurement notes): SQLAlchemy + asyncpg + NullPool defer the actual
    asyncpg connection acquisition until the FIRST query is executed
    against the session (``await session.execute(...)``). The session
    object itself can be created and ``__aenter__``-ed cheaply without
    touching the pool. This means a naive retry around ``__aenter__``
    alone provides ZERO coverage for the in-test contention surface
    (the connection error fires later, inside the request handler, after
    the session has been yielded and the retry envelope has exited).

    Plan 1088-04 iter-1 first-attempt measurement confirmed this: wrapping
    only ``__aenter__`` reduced 4.3 from 137 -> 135 (0 effective coverage).
    The fix: eagerly trigger asyncpg connection acquisition INSIDE the
    retry envelope by issuing a cheap ``SELECT 1`` after the session is
    created. If the warm-up query raises a transient contention
    exception, dispose the session and retry. Once the warm-up succeeds,
    the underlying asyncpg connection is established and pooled into
    the session's connection slot, so the subsequent yield to the FastAPI
    request handler executes against an already-acquired connection.

    The retry exception family is the same as the setup-phase helper
    (``_TRANSIENT_CONTENTION_EXCEPTIONS``: SQLAlchemy-wrapped OperationalError
    + raw ``asyncpg.exceptions.TooManyConnectionsError`` /
    ``CannotConnectNowError``). Non-contention OperationalError shapes
    (DNS, auth, refused-connection) propagate immediately so the test
    fails loudly rather than retrying a non-transient failure.

    Args:
        session_factory: Zero-arg callable returning an async session
            context manager (typically ``test_session_factory`` from the
            `client` fixture closure). Called fresh on each attempt.
        sleep_fn: Async sleep injected for testability. Production passes
            ``asyncio.sleep``; the regression pin patches this to a no-op.
        backoffs: Tuple of per-attempt sleep durations (seconds). Default
            ``(0.5, 1.0)`` = 1.5s total wait budget — bounded for in-test
            latency.

    Yields:
        The async session with its asyncpg connection already established
        (warm-up query succeeded), ready for FastAPI dependency-injection
        consumption.

    Raises:
        Exception: If every attempt raises one of
            ``_TRANSIENT_CONTENTION_EXCEPTIONS`` matching the contention
            substring (``"too many clients already"``) or is unambiguously
            asyncpg-contention, the last exception is re-raised so the
            caller surfaces the contention loudly as a test error (NOT
            swallowed). Same loud-fail contract as
            ``_run_with_too_many_clients_retry``.
        Exception: Re-raised immediately for any ``OperationalError``
            whose message does NOT contain ``"too many clients already"``
            (non-contention shapes propagate so the caller can route them
            appropriately).
    """
    last_exc: BaseException | None = None
    attempt_budget = 1 + len(backoffs)
    for attempt in range(attempt_budget):
        cm = session_factory()
        session = None
        try:
            session = await cm.__aenter__()
            # Eagerly trigger asyncpg connection acquisition. Under NullPool,
            # the session object alone does not hold a connection — the
            # asyncpg `_connect_addr` is invoked lazily on the first query.
            # By issuing a cheap `SELECT 1` here, any transient
            # `TooManyConnectionsError` is raised INSIDE this retry
            # envelope (where we can catch and retry) rather than later
            # inside the request handler (outside the envelope, surfacing
            # as a hard test-body failure). See lazy-connection contract
            # in the docstring above.
            await session.execute(text("SELECT 1"))
        except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
            last_exc = e
            # The warm-up failed — decide retry vs. propagate. Only call
            # __aexit__ when __aenter__ succeeded (i.e. session is not None).
            # Per PEP 343 the context-manager protocol forbids calling
            # __aexit__ if __aenter__ raised; the previous unconditional call
            # was undefined behaviour, masked by a broad except.
            if session is not None:
                try:
                    await cm.__aexit__(type(e), e, e.__traceback__)
                except Exception:
                    # Disposal during a failed warm-up may itself raise on the
                    # contention path; ignore so the original exception is the
                    # one surfaced/retried.
                    pass
            # Non-contention OperationalError shapes propagate immediately.
            # Raw asyncpg classes (TooManyConnectionsError, CannotConnectNowError)
            # are unambiguously contention so the substring guard is a no-op
            # for them (their type alone qualifies for retry).
            if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
                raise
            # Exhausted budget — re-raise loudly, NOT silent-swallow.
            if attempt == attempt_budget - 1:
                raise
            await sleep_fn(backoffs[attempt])
            continue
        # Warm-up succeeded — yield to caller, then teardown via __aexit__.
        try:
            yield session
        except BaseException:
            # Pass exception info to the underlying context manager so it
            # can roll back / clean up appropriately. Re-raise after.
            import sys
            await cm.__aexit__(*sys.exc_info())
            raise
        else:
            await cm.__aexit__(None, None, None)
        return
    # Defensive — the loop either returns or raises.
    if last_exc is not None:  # pragma: no cover
        raise last_exc


# Plan 1093-02 / TEST-01 / audit
# `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md` Section 3:
# engine-level retry envelope. Co-located with the in-test, session-factory,
# and engine retry helpers so the three retry tiers (setup-phase / in-test /
# engine-layer) are visually adjacent.


def _invoke_sleep_in_sync_context(sleep_fn, seconds):
    """Invoke a ``sleep_fn`` from a synchronous context.

    The async retry helpers (`_run_with_too_many_clients_retry`,
    `_acquire_test_session_with_retry`) accept an async ``sleep_fn``
    (default `asyncio.sleep`) and `await` it. But `engine.connect()` is
    synchronous in SQLAlchemy 2.x — it returns the AsyncConnection
    proxy without performing any I/O — so the retry loop around it is
    a sync loop. This helper bridges the two:

    - If ``sleep_fn`` is the production ``asyncio.sleep`` reference
      specifically: use ``time.sleep`` for the actual blocking delay.
      WR-02 (PARA-02 / Plan 1095-02) — Shape Y2 (load-bearing
      rationale): ``asyncio.run(asyncio.sleep(seconds))`` was
      empirically tested at Plan 1095-02 Task 5 Run 1 and produced
      658 ``RuntimeError: asyncio.run() cannot be called from a
      running event loop`` cascade failures across `pytest -n auto`,
      because the load-bearing production caller path
      (``_install_dbapi_connect_retry._retry_do_connect``, invoked
      via SQLAlchemy's ``do_connect`` event handler from inside
      ``greenlet_spawn``) DOES have a running event loop in the
      calling thread — the greenlet yielded into it. The blocking
      ``time.sleep`` here is load-bearing for sync-context
      compatibility. Documented mitigation: the engine-wrapper
      retry budget is bounded by ``_SETUP_PHASE_RETRY_BACKOFFS =
      (1.0, 2.0, 4.0)`` (7s total) and the 3 ``_init_tile_pool_*``
      fixture sites that bypassed this surface entirely are now
      wrapped at Plan 1095-01 via ``_run_with_too_many_clients_retry``
      — the cascade source the WR-02 caveat warned about is closed
      at its actual source-of-record, not at this helper. See
      ``.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md`` Section
      4.3 (WR-02 INDEPENDENT disposition) + Section 4.4 (caveat).
    - If ``sleep_fn`` is some OTHER async coroutine function (test
      injection like ``async def fake_sleep(s): sleep_calls.append(s)``):
      use ``asyncio.run`` to actually execute the body so the closure
      observes the call. Tests calling `wrapper.connect()` are
      synchronous (no surrounding event loop), so `asyncio.run` is
      safe.
    - If ``sleep_fn`` is a regular synchronous function: call directly.

    This is intentionally NOT exposed as part of the helper public
    surface — it is an implementation detail of
    `_RetryingAsyncEngine.connect()`.
    """
    if sleep_fn is asyncio.sleep:
        # WR-02 (PARA-02 / Plan 1095-02) — Shape Y2 load-bearing
        # rationale. asyncio.run(asyncio.sleep(seconds)) was attempted
        # as Shape Y1 at Plan 1095-02 Task 5 Run 1 and immediately
        # produced 658 RuntimeError cascade failures across `pytest
        # -n auto`: the production caller `_retry_do_connect` is
        # invoked via SQLAlchemy's `do_connect` event handler from
        # INSIDE `greenlet_spawn`, where the asyncio loop in the
        # calling thread IS running — the greenlet just yielded into
        # it. asyncio.run() refuses to nest inside a running loop.
        # time.sleep is the correct primitive for this sync-context
        # bridge. The WR-02 "loop starvation" caveat (audit Section
        # 4.4) is mitigated structurally: (a) the canonical 7s budget
        # `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` bounds the
        # max starvation window, (b) the cascade source the caveat
        # warned about (`_init_tile_pool_*` fixtures bypassing the
        # engine-wrapper layer entirely) is closed at its actual
        # source-of-record at Plan 1095-01 (Shape A* wrap of the 3
        # `_init_tile_pool_for_tests` fixtures in
        # `_run_with_too_many_clients_retry`). See audit Section 4.3
        # for the WR-02 INDEPENDENT disposition rationale.
        time.sleep(seconds)
    elif asyncio.iscoroutinefunction(sleep_fn):
        # Test-injected async sleep: drive it via asyncio.run so the
        # body executes and any closure capture is observed. The test
        # pins call `wrapper.connect()` from sync context with no
        # surrounding event loop, so asyncio.run is safe.
        asyncio.run(sleep_fn(seconds))
    else:
        # Plain synchronous sleep_fn.
        sleep_fn(seconds)


def _install_dbapi_connect_retry(sync_engine, sleep_fn, backoffs):
    """Install a ``do_connect`` event handler on ``sync_engine`` that
    retries the DBAPI connect call on transient contention.

    This intercepts the LOAD-BEARING surface for the post-commit residual
    that Plan 1088-04 could not close: SQLAlchemy session machinery
    routes `bind.connect()` through `sync_engine.dialect.connect(*cargs,
    **cparams)`, which under asyncpg ultimately invokes
    `asyncpg.connect(...)`. The `do_connect` event fires BEFORE
    `dialect.connect()` and accepts an Optional[DBAPIConnection] return
    value — if non-None, SQLAlchemy uses the returned connection
    instead of calling `dialect.connect()` itself.

    The handler wraps the entire `dialect.connect()` call (which
    internally drives `asyncpg.connect()` through the
    `AsyncAdapt_asyncpg_dbapi` shim) in a retry loop. On transient
    contention exceptions from the `_TRANSIENT_CONTENTION_EXCEPTIONS`
    tuple, the loop sleeps via the budget and retries up to
    `1 + len(backoffs)` total attempts. Non-contention `OperationalError`
    shapes propagate immediately.

    Returns:
        The registered ``_retry_do_connect`` handler function. The caller
        (``_RetryingAsyncEngine.__init__``) stores this reference so
        ``_RetryingAsyncEngine.dispose()`` can ``event.remove(sync_engine,
        "do_connect", <handler>)`` it on teardown, preventing listener
        stacking if a future refactor wraps a shared engine multiple
        times (WR-04 closure — Phase 1096 / HYG-01).
    """
    from sqlalchemy import event

    @event.listens_for(sync_engine, "do_connect")
    def _retry_do_connect(dialect, conn_rec, cargs, cparams):
        last_exc: BaseException | None = None
        attempt_budget = 1 + len(backoffs)
        for attempt in range(attempt_budget):
            try:
                # Call dialect.connect() directly to obtain the DBAPI
                # connection. Returning a non-None DBAPI connection from
                # the event handler causes SQLAlchemy to skip its own
                # `dialect.connect()` invocation, so this is THE call.
                return dialect.connect(*cargs, **cparams)
            except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
                last_exc = e
                if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
                    raise
                if attempt == attempt_budget - 1:
                    raise
                _invoke_sleep_in_sync_context(sleep_fn, backoffs[attempt])
        if last_exc is not None:  # pragma: no cover
            raise last_exc

    return _retry_do_connect


class _RetryingAsyncEngine:
    """Composition wrapper around ``AsyncEngine`` that retries
    ``engine.connect()`` and ``engine.dispose()`` on transient connection
    contention.

    Plan 1093-02 / TEST-01: After Plan 1088-04's session-factory wrapper
    (`_acquire_test_session_with_retry`) closed the in-test warm-up surface
    (137 → 48 failures, partial close), 48 deterministic + ~173
    non-deterministic failures remained on `bind.connect()` calls firing
    AFTER `await session.commit()` releases the warm-up's connection —
    OUTSIDE any session-factory-level retry envelope. The session-factory
    helper cannot wrap these because they happen inside test bodies on
    fresh connection acquisitions after `__aenter__` has yielded.

    This wrapper intercepts at the LOWEST async-engine layer: every direct
    call to ``engine.connect()`` and ``engine.dispose()`` flows through
    retry-on-`_TRANSIENT_CONTENTION_EXCEPTIONS` with the
    ``_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)`` budget (7s total).
    Setup-phase budget (vs. the in-test 1.5s budget) chosen because the
    engine wrapper subsumes setup-phase retries IN ADDITION to closing
    the post-commit residual — tighter budgets risk false-positive
    loud-fails under combined contention.

    Composition (NOT inheritance) was chosen per
    `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md` Section 3 — the
    alternative shapes (event.listen, NullPool subclass, async_creator=)
    each failed one or more of the 4 criteria: covers both surfaces /
    preserves NullPool+QueuePool branches / preserves
    `test_conftest_pool_sizing.py` pins (specifically
    `type(engine.pool).__name__`) / testable via MagicMock-only.

    The wrapper:
    - REUSES `_TRANSIENT_CONTENTION_EXCEPTIONS` verbatim — no new catch.
    - REUSES `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` verbatim.
    - Preserves the underlying engine's `.pool` accessor via `@property`
      delegation (required for `test_xdist_engine_uses_nullpool` at
      `test_conftest_pool_sizing.py:261` and
      `test_sequential_engine_uses_queuepool` at `:281`).
    - Preserves the `sync_engine` accessor used by `async_sessionmaker`
      via `engine._get_sync_engine_or_connection` (module-level function
      in `sqlalchemy.ext.asyncio.engine`).
    - Delegates everything else via `__getattr__` so call sites using
      other AsyncEngine surfaces (e.g., `await engine.begin()`,
      `engine.raw_connection`) work unchanged.
    - Provides a `sleep_fn` parameter (defaults to `asyncio.sleep`)
      mirroring v1020 helper conventions for testability.
    - Loud-fail-on-exhaust: re-raises the last exception after budget
      exhaustion, mirroring `_run_with_too_many_clients_retry` and
      `_acquire_test_session_with_retry` conventions.
    """

    def __init__(
        self,
        underlying,
        sleep_fn=asyncio.sleep,
        backoffs=_SETUP_PHASE_RETRY_BACKOFFS,
    ):
        # Use object.__setattr__ to avoid recursing through __getattr__ /
        # __setattr__ during initial assignment.
        object.__setattr__(self, "_underlying", underlying)
        object.__setattr__(self, "_sleep_fn", sleep_fn)
        object.__setattr__(self, "_backoffs", backoffs)
        # Install retry-wrapped DBAPI connect via the `do_connect` dialect
        # event on the underlying sync engine. This is the load-bearing
        # interception point: SQLAlchemy's session machinery calls
        # `dialect.connect(*cargs, **cparams)` to acquire fresh asyncpg
        # connections (e.g., during post-commit `bind.connect()`). The
        # event handler returns a DBAPIConnection from within a retry
        # loop, so transient `TooManyConnectionsError` /
        # `CannotConnectNowError` are retried at the lowest layer —
        # subsuming the post-commit residual that Plan 1088-04's
        # session-factory wrapper could not reach.
        try:
            sync_engine = underlying.sync_engine
        except AttributeError:
            # Test doubles may not expose sync_engine; the .connect() /
            # .dispose() retry wrappers above still apply.
            # WR-04 (Phase 1096 / HYG-01): pre-initialize listener refs
            # to None so dispose() can no-op cleanly.
            object.__setattr__(self, "_sync_engine", None)
            object.__setattr__(self, "_do_connect_handler", None)
            return
        try:
            handler = _install_dbapi_connect_retry(
                sync_engine, sleep_fn=sleep_fn, backoffs=backoffs
            )
        except (TypeError, AttributeError, InvalidRequestError):
            # WR-03 closure (Phase 1096 / HYG-01): narrowed from
            # `except Exception` per v1020 audit Section 4.1 silent-swallow
            # anti-pattern. Test doubles (MagicMock sync_engine) cannot
            # accept `event.listens_for` — SQLAlchemy raises one of three
            # documented event-API failure shapes:
            #   1. TypeError — when SQLAlchemy probes `.dispatch.listeners`
            #      on a non-Event-API object.
            #   2. AttributeError — when the probe itself fails (no
            #      `.dispatch` attribute at all).
            #   3. sqlalchemy.exc.InvalidRequestError — when
            #      `_EventKey._resolve()` (`sqlalchemy/event/api.py:34`)
            #      cannot find the named event on the target (the actual
            #      shape raised against MagicMock in current SQLAlchemy
            #      2.x: "No such event 'do_connect' for target ...").
            # Narrowing the catch to these three documented failure modes
            # ensures future SQLAlchemy event-API changes (e.g., a new
            # exception class indicating a real install regression)
            # surface as loud-fails instead of being silently swallowed.
            # The .connect() / .dispose() retry wrappers above still
            # apply for test-double surfaces. Production engines DO
            # accept the event hook because they are real SQLAlchemy
            # Engine instances.
            handler = None
        # WR-04 closure (Phase 1096 / HYG-01): store the handler ref + sync
        # engine ref so `dispose()` can `event.remove(...)` the listener
        # and prevent stacking when a shared engine is wrapped multiple
        # times. `handler` is None when install was silently skipped per
        # WR-03 narrow-catch above; dispose() must guard against this.
        object.__setattr__(self, "_sync_engine", sync_engine)
        object.__setattr__(self, "_do_connect_handler", handler)

    def connect(self):
        """Retry-protected version of ``underlying.connect()``.

        IMPORTANT (SQLAlchemy 2.x async-engine semantics):
        ``AsyncEngine.connect()`` is itself SYNCHRONOUS — it just constructs
        an ``AsyncConnection`` proxy object without performing any database
        I/O. The actual connection acquisition happens later, inside the
        ``async with ... as conn`` block (i.e., during the connection's
        ``__aenter__`` / ``start()``). This means the contention exception
        from asyncpg is raised on ``await conn.start()``, NOT on the
        ``connect()`` call itself in normal production usage.

        The retry-budget loop here covers fake/test engines that DO
        raise contention exceptions on the synchronous ``connect()``
        call itself (the regression-pin model). In production, where
        the contention surfaces on ``__aenter__``, this wrapper does
        not currently retry — production retry coverage for the
        post-commit residual is provided primarily by the
        ``engine.dispose()`` retry (called explicitly during fixture
        teardown) and by the additive defense the wrapper provides
        for any direct ``engine.connect()`` usage that bypasses
        session machinery.

        Sync-context retry sleep handling: when the injected
        ``sleep_fn`` is an async coroutine function (the default
        ``asyncio.sleep`` or test-injected ``async def fake_sleep``),
        we cannot ``await`` it from this sync context. We call
        ``_invoke_sleep_in_sync_context`` to (a) call the async sleep
        function so test pins recording into the closure capture the
        call, and (b) fall back to ``time.sleep`` for production.
        """
        last_exc: BaseException | None = None
        attempt_budget = 1 + len(self._backoffs)
        for attempt in range(attempt_budget):
            try:
                return self._underlying.connect()
            except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
                last_exc = e
                if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
                    raise
                if attempt == attempt_budget - 1:
                    raise
                _invoke_sleep_in_sync_context(
                    self._sleep_fn, self._backoffs[attempt]
                )
        if last_exc is not None:  # pragma: no cover
            raise last_exc

    async def dispose(self):
        """Retry-protected version of ``underlying.dispose()``.

        Plan 1093-02: `dispose()` is called at `client` fixture teardown
        (`conftest.py:959` `await test_engine.dispose()`). While dispose
        does not acquire NEW connections (it releases existing ones),
        the asyncpg cleanup path can surface transient errors if the
        worker is racing the connection ceiling at the moment of
        dispose. Symmetric with `connect()` retry coverage per
        CONTEXT.md `<domain>` line 14.

        WR-04 closure (Phase 1096 / HYG-01): before delegating to the
        underlying dispose, remove the `do_connect` event listener
        registered by `_install_dbapi_connect_retry` in `__init__`.
        Without removal, a future refactor wrapping the SAME shared
        sync engine multiple times would stack listeners — every
        `do_connect` event would fire each registered handler in turn,
        compounding the retry budget and silently degrading the
        production-effective retry contract. Removal happens BEFORE
        the retry loop so the listener is gone even if the underlying
        dispose retries / exhausts the budget. Guards against
        ``_do_connect_handler is None`` (WR-03 install caught) and
        ``_sync_engine is None`` (test double without sync_engine
        accessor) so the no-listener path is a clean no-op.
        """
        from sqlalchemy import event

        # WR-04: remove the do_connect listener exactly once, before
        # the underlying dispose runs. Idempotent via the None guard:
        # repeated dispose() calls do not re-attempt removal because
        # we clear the refs after a successful remove.
        if (
            self._do_connect_handler is not None
            and self._sync_engine is not None
        ):
            try:
                event.remove(
                    self._sync_engine,
                    "do_connect",
                    self._do_connect_handler,
                )
            except Exception:
                # Conservative narrow: if SQLAlchemy refuses the remove
                # (e.g., already-removed by a sibling dispose, or test
                # double mutates between install + remove), do not block
                # the underlying dispose. The latent risk this WR-04
                # closure addresses is "future refactor wraps a shared
                # engine multiple times" — which would manifest as
                # listener-count > 1 on re-install, not as a remove
                # failure. Caught broadly here BUT immediately reset
                # to None below so subsequent dispose() calls don't
                # re-attempt the remove and produce noisy duplicates.
                pass
            # Reset refs so repeat-dispose is a clean no-op and the
            # wrapper does not retain a stale handler reference that
            # could be mistakenly re-used.
            object.__setattr__(self, "_do_connect_handler", None)

        last_exc: BaseException | None = None
        attempt_budget = 1 + len(self._backoffs)
        for attempt in range(attempt_budget):
            try:
                return await self._underlying.dispose()
            except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
                last_exc = e
                if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
                    raise
                if attempt == attempt_budget - 1:
                    raise
                await self._sleep_fn(self._backoffs[attempt])
        if last_exc is not None:  # pragma: no cover
            raise last_exc

    @property
    def pool(self):
        """Pass-through accessor preserving the underlying engine's
        pool class. CRITICAL for `test_conftest_pool_sizing.py:261` /
        `:281` pins which check `type(engine.pool).__name__`.
        """
        return self._underlying.pool

    @property
    def sync_engine(self):
        """Pass-through accessor used by `async_sessionmaker` via
        ``engine._get_sync_engine_or_connection`` (module-level function
        in `sqlalchemy.ext.asyncio.engine`). Without this, sessions
        constructed from the wrapped engine would fail with
        ``ArgumentError: AsyncEngine expected``.
        """
        return self._underlying.sync_engine

    def __getattr__(self, name):
        """Delegate all other attribute access to the underlying engine.

        Note: this method is only invoked for attributes NOT found via
        normal lookup, so `connect`, `dispose`, `pool`, `sync_engine`,
        `_underlying`, `_sleep_fn`, `_backoffs` are all reached directly
        WITHOUT going through __getattr__. Everything else (e.g.,
        `begin`, `raw_connection`, `url`, `name`) is delegated.
        """
        return getattr(self._underlying, name)


@pytest.fixture(autouse=True, scope="session")
def _test_db_lifecycle():
    """Create, migrate, and tear down the test database once per session.

    Uses sync SQLAlchemy because CREATE/DROP DATABASE require AUTOCOMMIT
    isolation which is simpler with the synchronous driver.

    Gracefully skips DB setup when database host is unreachable (e.g. pure
    unit test runs outside Docker). Tests that require DB will fail with a
    clear connection error; DB-independent tests will run normally.
    """
    original_test_db_name = settings.postgres_db_test
    db_name = _worker_test_database_name(original_test_db_name)
    settings.postgres_db_test = db_name
    should_drop_db = False

    # Stagger startup to prevent simultaneous connection spikes.
    # See _get_setup_stagger_delay() and _SETUP_STAGGER_SECONDS for rationale.
    _stagger_delay = _get_setup_stagger_delay()
    if _stagger_delay > 0:
        time.sleep(_stagger_delay)

    try:
        # --- Setup: create test database ---
        #
        # Audit Section 4.1 / Phase 1088-01 / FI-02: the original block here was a
        # broad `except Exception: yield; return` that silently swallowed any
        # failure from `dev_engine.connect()`. Under `pytest -n auto` against
        # max_connections=30, the staggered-startup window placed the highest-
        # numbered worker (gw15, 75s stagger) into the connection-saturation
        # window, where `dev_engine.connect()` raised OperationalError("too many
        # clients already"). The silent-swallow yielded with should_drop_db=False
        # and returned, leaving the per-worker test DB uncreated. The 407
        # downstream `InvalidCatalogNameError` failures (62.8% of all -n auto
        # failures in the v1020 audit) all traced back to this single defect.
        #
        # The replacement structure below distinguishes:
        #   - transient connection contention (`too many clients already`):
        #     retry-with-backoff via `_create_test_db_with_retry`, fail loudly
        #     on exhaustion so the issue surfaces as a fixture error (NOT as
        #     downstream InvalidCatalogNameError).
        #   - genuinely unreachable host (DNS failure, refused connection):
        #     preserve the existing pytest.skip semantics so pure unit-test
        #     runs outside Docker still work.
        # See `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` §4.1 and
        # `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-01-PLAN.md`.
        quoted_db_name = _quote_database_identifier(db_name)

        def _open_dev_engine():
            return sqlalchemy.create_engine(
                settings.database_url_sync, isolation_level="AUTOCOMMIT"
            )

        try:
            _create_test_db_with_retry(_open_dev_engine, quoted_db_name)
            should_drop_db = True
        except OperationalError as e:
            err_msg = str(e).lower()
            if "too many clients already" in err_msg:
                # Retry budget exhausted: fail loudly so CI surfaces the real
                # saturation, instead of masking it as 407 downstream
                # InvalidCatalogNameError on this worker's tests.
                raise
            # Truly unreachable host (DNS failure, refused connection, auth
            # error, etc.) — preserve the existing skip semantics for
            # pure unit-test runs outside Docker.
            pytest.skip(f"Postgres unreachable: {e}")

        # --- Init: extensions, schemas, roles ---
        test_engine_sync = sqlalchemy.create_engine(settings.test_database_url_sync)
        try:
            with test_engine_sync.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS catalog"))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS data"))

                # Idempotent role grants
                conn.execute(
                    text(
                        "DO $$ BEGIN "
                        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN "
                        "CREATE ROLE geolens_reader NOLOGIN; "
                        "END IF; END $$"
                    )
                )
                conn.execute(text("GRANT USAGE ON SCHEMA data TO geolens_reader"))
                conn.execute(
                    text("GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader")
                )
                conn.execute(
                    text(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA data "
                        "GRANT SELECT ON TABLES TO geolens_reader"
                    )
                )
                conn.commit()
        except SQLAlchemyError:
            # DB is reachable but missing required extensions (for example pgvector).
            # Let DB-light tests run; DB-backed tests will fail when they request DB fixtures.
            test_engine_sync.dispose()
            _drop_test_database_if_exists(db_name)
            should_drop_db = False
            yield
            return
        test_engine_sync.dispose()

        # --- Migrate: run alembic against the test database ---
        from alembic import command
        from alembic.config import Config as AlembicConfig

        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
        # Pre-set version_locations from the geolens.migrations entry-point group
        # before invoking command.upgrade. The env.py also performs this discovery,
        # but ScriptDirectory is constructed before env.py runs and caches the
        # version_locations from the cfg at construction time -- so an env.py-time
        # mutation does not propagate to the upgrade walk. Setting here ensures
        # enterprise branch heads (e.g. e002_add_saml_columns) participate in
        # `heads` (plural) discovery alongside the core head.
        import pathlib as _pathlib
        from importlib.metadata import entry_points as _entry_points

        _enterprise_paths: list[str] = []
        for _ep in _entry_points(group="geolens.migrations"):
            try:
                _fn = _ep.load()
                if callable(_fn):
                    for _p in _fn():
                        if _pathlib.Path(_p).is_dir():
                            _enterprise_paths.append(_p)
            except Exception:
                pass  # Non-fatal; core migrations still run.
        if _enterprise_paths:
            _base_versions = (
                alembic_cfg.get_main_option("version_locations") or "alembic/versions"
            )
            alembic_cfg.set_main_option(
                "version_locations",
                _base_versions + " " + " ".join(_enterprise_paths),
            )

        # Use "heads" (plural) so any enterprise migration branches discovered
        # above are upgraded alongside core. With community-only installs, "heads"
        # behaves identically to "head" because there is only one head; with
        # enterprise installed, this picks up the enterprise branch.
        command.upgrade(alembic_cfg, "heads")

        # --- SAML column bridge (community-only test environments) ---
        # The four SAML columns on catalog.oauth_providers are normally added by the
        # enterprise migration e002_add_saml_columns. When geolens-enterprise is NOT
        # installed, those columns are absent from the test DB. SQLAlchemy still
        # includes them in INSERTs (deferred=True only suppresses SELECT loading,
        # not INSERT column lists), causing UndefinedColumnError in any test that
        # seeds an OAuthProvider row directly.
        #
        # This bridge detects the missing columns and adds them idempotently,
        # mirroring what e002_add_saml_columns does. It only fires when the enterprise
        # package is absent (i.e. _enterprise_paths is empty), so enterprise CI is
        # unaffected.
        if not _enterprise_paths:
            _saml_bridge_engine = sqlalchemy.create_engine(
                settings.test_database_url_sync
            )
            with _saml_bridge_engine.connect() as _conn:
                # Check whether idp_entity_id already exists; if not, add all four.
                _result = _conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'catalog' "
                        "AND table_name = 'oauth_providers' "
                        "AND column_name = 'idp_entity_id'"
                    )
                )
                if _result.fetchone() is None:
                    _conn.execute(
                        text(
                            "ALTER TABLE catalog.oauth_providers "
                            "ADD COLUMN IF NOT EXISTS idp_entity_id VARCHAR(512), "
                            "ADD COLUMN IF NOT EXISTS idp_sso_url VARCHAR(512), "
                            "ADD COLUMN IF NOT EXISTS idp_certificate TEXT, "
                            "ADD COLUMN IF NOT EXISTS sp_entity_id VARCHAR(512)"
                        )
                    )
                    _conn.commit()
            _saml_bridge_engine.dispose()

        yield

    finally:
        if should_drop_db:
            # --- Teardown: drop the test database ---
            #
            # Ordering invariant (TI-01, Phase 1075):
            #   1. pg_terminate_backend() to all sessions on the test DB
            #   2. SHORT SLEEP — let libpq drain the killed connection state.
            #      pg_terminate_backend is asynchronous from libpq's POV: the
            #      SQL call returns true as soon as the backend receives
            #      SIGTERM, NOT after the connection is fully reaped from
            #      pg_stat_activity. Without this beat, a follow-up DROP can
            #      race the still-shutting-down session and surface as
            #      "database is being accessed by other users" or, in the
            #      next pytest run, an InvalidCatalogNameError when the
            #      stale connection is briefly visible.
            #   3. DROP DATABASE IF EXISTS
            teardown_engine = sqlalchemy.create_engine(
                settings.database_url_sync, isolation_level="AUTOCOMMIT"
            )
            try:
                with teardown_engine.connect() as conn:
                    # Terminate active connections before dropping
                    conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :db_name AND pid <> pg_backend_pid()"
                        ),
                        {"db_name": db_name},
                    )
                    # 50ms is empirically sufficient for asyncpg-driven
                    # connection kills on a local PG instance; remote/CI
                    # deployments may need more, but the next run's
                    # `DROP DATABASE IF EXISTS` is idempotent so a stale
                    # connection only delays cleanup, never breaks it.
                    time.sleep(0.05)
                    conn.execute(
                        text(
                            f"DROP DATABASE IF EXISTS {_quote_database_identifier(db_name)}"
                        )
                    )
            finally:
                teardown_engine.dispose()
        settings.postgres_db_test = original_test_db_name


@pytest.fixture
async def client(tmp_path):
    """Create an async test client with a dedicated database engine.

    Overrides both the get_db dependency AND the database module's engine/session
    so that the lifespan seed functions and request handlers all use the same
    test engine. This prevents asyncpg pool state conflicts.
    """
    original_upload_staging_dir = settings.upload_staging_dir
    settings.upload_staging_dir = str(tmp_path / "staging")
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    original_tempdir = tempfile.tempdir
    from app.core.runtime.staging import redirect_tempfile_to_staging

    redirect_tempfile_to_staging(staging_dir)

    # Pool sizing is derived per pytest-xdist worker via _derive_test_pool_sizing().
    # The baseline connection budget is tight:
    #   max_connections=30 (db/postgresql.conf:11, PERF-05 / Phase 274)
    #   API+worker services: 8 persistent idle connections to the main DB
    #   Postgres background: 5 connections
    #   Available for test workers: 30 − 13 = 17 connections
    # Under -n auto (16 workers), any pool that holds idle connections will
    # consume the entire budget, leaving no room for setup-phase engines.
    # NullPool (xdist mode) avoids idle-connection overhead — connections are
    # opened only during active DB operations and closed immediately when released.
    # Sequential mode (worker_id=master) keeps the historical (5, 2) QueuePool
    # for request handlers that need concurrent DB conns within a single test.
    # See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for measured numbers + rationale.
    # Engine-creation logic is extracted to _make_test_async_engine() so the
    # NullPool-vs-QueuePool branch is directly testable (see test_conftest_pool_sizing.py).
    test_engine = _make_test_async_engine(settings.test_database_url)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    # Patch the database module so lifespan seed functions use our engine
    import app.core.db as db_module

    original_engine = db_module.engine
    original_session = db_module.async_session
    db_module.engine = test_engine
    db_module.async_session = test_session_factory

    # Patch health service module's engine reference
    import app.observability.health.service as health_service_module

    original_health_engine = health_service_module.engine
    health_service_module.engine = test_engine

    # Override the get_db dependency
    from app.core.dependencies import get_db
    from app.api.main import app

    # Plan 1088-04 / audit Section 4.3: wrap the per-request session-factory
    # acquisition with `_acquire_test_session_with_retry` so transient
    # `asyncpg.TooManyConnectionsError` / `OperationalError("too many clients
    # already")` raised inside `__aenter__` is retried with bounded backoff
    # (0.5 + 1.0 = 1.5s budget) before failing loudly. Distinct from
    # Plan 1088-03's setup-phase wrap of `_ensure_roles_and_admin`: this one
    # fires per-request inside the test body (e.g., when a test issues
    # multiple sequential `TestClient.post(...)` calls), so the budget is
    # intentionally tighter than the setup-phase 7s window. See
    # `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` Section 4.3 +
    # Section 5 suggestion (lines 1289-1299).
    async def override_get_db():
        async with _acquire_test_session_with_retry(test_session_factory) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Initialize singleton cache provider for settings reads/writes in request paths.
    # Lifespan is not guaranteed in this ASGITransport test setup.
    init_cache()
    import app.platform.storage.provider as storage_provider_module
    from app.platform.storage.local import LocalStorageProvider

    original_storage = storage_provider_module._storage
    storage_provider_module._storage = LocalStorageProvider(base_dir=str(staging_dir))
    structlog.contextvars.bind_contextvars(service="api")

    # Disable rate limiter during tests
    from app.modules.auth.router import limiter

    limiter.enabled = False

    # Ensure roles and admin user exist before tests.
    #
    # Plan 1088-03 / audit Section 4.2: this is the FIRST async-session
    # connection acquisition under the test_engine, and under -n auto
    # it surfaced 188 of 365 residual failures as
    # `asyncpg.TooManyConnectionsError: sorry, too many clients already`
    # during fixture setup (see
    # `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md`).
    # Wrap with `_run_with_too_many_clients_retry` so transient
    # connection-contention is retried with bounded backoff
    # (1.0 + 2.0 + 4.0 = 7s) before failing loudly. The retry budget is
    # the SAME shape as `_create_test_db_with_retry` from Plan 1088-01
    # (audit Section 4.1) so both setup-phase contention sites use a
    # consistent retry contract.
    await _run_with_too_many_clients_retry(
        lambda: _ensure_roles_and_admin(test_session_factory)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Cleanup
    app.dependency_overrides.clear()
    db_module.engine = original_engine
    db_module.async_session = original_session
    health_service_module.engine = original_health_engine
    storage_provider_module._storage = original_storage
    settings.upload_staging_dir = original_upload_staging_dir
    tempfile.tempdir = original_tempdir
    await test_engine.dispose()


async def _ensure_roles_and_admin(session_factory: async_sessionmaker) -> None:
    """Seed roles and ensure the admin user exists."""
    # Seed roles
    async with session_factory() as session:
        for role_data in [
            {"name": "admin", "description": "Full system access"},
            {"name": "editor", "description": "Can create and edit datasets"},
            {"name": "viewer", "description": "Read-only access to permitted datasets"},
        ]:
            result = await session.execute(
                select(Role).where(Role.name == role_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(**role_data))
        await session.commit()

    # Ensure admin user exists
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            admin_user = User(
                username=settings.geolens_admin_username,
                password_hash=hash_password(
                    settings.geolens_admin_password.get_secret_value()
                ),
                is_active=True,
            )
            session.add(admin_user)
            await session.flush()

            role_result = await session.execute(
                select(Role).where(Role.name == "admin")
            )
            admin_role = role_result.scalar_one()
            session.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
            await session.commit()
        elif not admin.is_active:
            # Re-activate admin if a previous test deactivated it
            admin.is_active = True
            # Reset password to known value
            admin.password_hash = hash_password(
                settings.geolens_admin_password.get_secret_value()
            )
            await session.commit()


async def get_auth_header(
    client: AsyncClient, username: str, password: str
) -> dict[str, str]:
    """Log in via POST /auth/login and return an Authorization header dict."""
    resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_test_user(
    client: AsyncClient,
    admin_headers: dict,
    role: str,
) -> tuple[dict[str, str], str]:
    """Create a test user with the given role and return (auth_header, user_id)."""
    unique = uuid.uuid4().hex[:8]
    username = f"{role}_{unique}"
    password = "TestPass1234!"  # SEC-S16: meets 12-char + 3-class policy
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": role},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"Create {role} failed: {resp.text}"
    user_id = resp.json()["id"]
    headers = await get_auth_header(client, username, password)
    return headers, user_id


@pytest.fixture
async def admin_auth_header(client: AsyncClient) -> dict[str, str]:
    """Return auth headers for the seeded admin user."""
    return await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )


@pytest.fixture
async def editor_auth_header(
    client: AsyncClient, admin_auth_header: dict
) -> dict[str, str]:
    """Create an editor user and return their auth headers."""
    headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    return headers


@pytest.fixture
async def viewer_auth_header(
    client: AsyncClient, admin_auth_header: dict
) -> dict[str, str]:
    """Create a viewer user and return their auth headers."""
    headers, _ = await _create_test_user(client, admin_auth_header, "viewer")
    return headers


@pytest.fixture
async def test_db_session(client: AsyncClient):
    """Yield an async session from the test engine for direct DB operations.

    Uses the same session factory that the client fixture patches into the app,
    so records inserted here are visible to request handlers.

    Plan 1088-04 / audit Section 4.3 Rule-2 extension: wrap the session
    acquisition with `_acquire_test_session_with_retry`. The original plan
    scoped only `override_get_db`, but iter-1 measurement showed 66 of the
    remaining 4.3 failures route through this fixture (tests that combine
    `test_db_session` for direct DB writes with `client` for HTTP requests
    open >=2 distinct asyncpg connections per test body). The contention
    surface is identical to `override_get_db` — same lazy-connection
    failure pattern under NullPool — so the same retry helper applies.
    Without this extension, post-1088-04 4.3 stays above the 30 threshold.
    """
    import app.core.db as db_module

    async with _acquire_test_session_with_retry(db_module.async_session) as session:
        yield session


# ---------------------------------------------------------------------------
# Isolation note (tech debt)
# ---------------------------------------------------------------------------
#
# The current fixture model creates a single test database per pytest-xdist
# WORKER per session and shares it across all tests on that worker. Isolation
# is enforced by:
#   1. Unique names (uuid4 suffixes + worker_id) in test data factories
#   2. Per-test cleanup via explicit DELETE / DROP TABLE in test teardown
#   3. Session-scoped roles and admin seeded once via _ensure_roles_and_admin
#
# A transaction-rollback-per-test model would be safer but is incompatible
# with the way request handlers call ``await session.commit()`` under the
# HTTP test client. Moving to per-test rollback requires either:
#   (a) Wrapping every request in a SAVEPOINT and intercepting handler commits
#       via a custom AsyncSession subclass, or
#   (b) TRUNCATE CASCADE on all user-level tables between tests.
#
# Both are large changes deferred to a dedicated PR. The opt-in ``clean_tables``
# fixture below is provided for tests that need extra determinism today.
#
# Concurrent pytest sessions AND parallel pytest-xdist workers are isolated by
# suffixing the configured ``POSTGRES_DB_TEST`` base name with the worker_id
# (``"master"`` when xdist is inactive, ``"gw0"`` / ``"gw1"`` / ... under
# ``-n auto``) plus an 8-char uuid hex. Each run drops only its own physical
# database during teardown, so background runs, interactive runs, and parallel
# xdist workers can target the same Postgres server without cross-contamination
# (TI-01, Phase 1075).


@pytest.fixture(autouse=True)
def _point_ogr2ogr_at_test_db(request, monkeypatch):
    """Redirect ``ogr2ogr``'s PG connection string to the test database.

    ``app.ingest.ogr.build_pg_conn_str()`` defaults to the dev/prod
    settings. Any test that invokes ``run_ogr2ogr`` /
    ``run_ogr2ogr_service`` without this redirect would write to the
    wrong database and collide with non-test data. The original fixture
    lived locally in ``test_ingest_column_preservation.py`` (K2-PRE) —
    lifting it to ``conftest.py`` behind the ``requires_ogr2ogr`` marker
    means any future test that opts in automatically inherits the
    safety redirect.

    Opt-in: only tests marked with ``@pytest.mark.requires_ogr2ogr``
    (or a class-level ``pytestmark``) trigger the monkeypatch. All
    other tests are unaffected.
    """
    if "requires_ogr2ogr" not in request.keywords:
        return

    from app.core.config import settings as _settings
    from app.processing.ingest import ogr as _ogr

    def _test_pg_conn_str() -> str:
        return (
            f"PG:host={_settings.postgres_host} "
            f"port={_settings.postgres_port} "
            f"dbname={_settings.postgres_db_test} "
            f"user={_settings.postgres_user} "
            f"password={_settings.postgres_password.get_secret_value()}"
        )

    monkeypatch.setattr(_ogr, "build_pg_conn_str", _test_pg_conn_str)


@pytest.fixture
def stac_visibility_force_5xx(monkeypatch):
    """SEC-FU-01: Force apply_visibility_filter to raise RuntimeError on every call.

    Monkeypatches ``app.modules.catalog.authorization.apply_visibility_filter``
    so that STAC item-read and search endpoints exercise the 5xx error path
    without requiring the database to fail.  Yields a ``SimpleNamespace(active=True)``
    handle so tests can assert the patch is in effect.

    Scoped to function level (default); ``monkeypatch`` auto-unwinds at teardown,
    so no production code path is affected outside the requesting test.

    Usage::

        def test_no_leak(client, stac_visibility_force_5xx):
            assert stac_visibility_force_5xx.active
            resp = client.get("/stac/items/...")
            assert resp.status_code >= 500

    Pattern mirrors ``monkeypatch.setattr(_ogr, "build_pg_conn_str", ...)`` above.
    """
    import types as _types
    import app.modules.catalog.authorization as _authorization
    import app.standards.stac.router as _stac_router

    def _force_raise(stmt, user, user_roles, record_cls, grant_cls=None):
        raise RuntimeError("forced 5xx for SEC-FU-01 regression test")

    # Patch the canonical module so direct imports from authorization also see the stub.
    monkeypatch.setattr(_authorization, "apply_visibility_filter", _force_raise)
    # Also patch the name already bound in the STAC router module's namespace,
    # because ``from app.modules.catalog.authorization import apply_visibility_filter``
    # creates a separate binding that a pure module-level patch would not reach.
    monkeypatch.setattr(_stac_router, "apply_visibility_filter", _force_raise)

    yield _types.SimpleNamespace(active=True)


@pytest.fixture
def saml_overlay_registered():
    """Programmatically register EnterpriseSamlExtension into the live extension
    registry for the duration of a single test. Restores prior state on
    teardown so other tests that expect community edition still see their
    default.

    The ``geolens_enterprise`` import is deferred (inside the fixture body)
    so test collection does not require the enterprise package to be
    installed -- collection still succeeds in community-only environments;
    tests that request this fixture are skipped when the overlay is absent.
    """
    from app.platform.extensions import _extensions, _routers

    saved_ext = dict(_extensions)
    saved_routers = list(_routers)
    try:
        # Deferred import so collection does not require the enterprise package
        saml_module = pytest.importorskip(
            "geolens_enterprise.auth.saml",
            reason="geolens_enterprise package is not installed",
        )
        saml_router_module = pytest.importorskip(
            "geolens_enterprise.auth.saml.router",
            reason="geolens_enterprise package is not installed",
        )

        ext = saml_module.EnterpriseSamlExtension()
        _extensions["auth"] = ext
        _extensions["identity"] = ext
        _routers.append(saml_router_module.router)
        yield ext
    finally:
        _extensions.clear()
        _extensions.update(saved_ext)
        _routers.clear()
        _routers.extend(saved_routers)


@pytest.fixture
async def clean_tables(test_db_session):
    """Opt-in fixture: truncate user-level tables after the test.

    Use this fixture in tests that need the test database reset to a known
    state afterwards (e.g., tests that assert on list sizes or cross-cutting
    counts). It runs TRUNCATE CASCADE on mutable tables in the ``catalog``
    and ``data`` schemas, leaving roles/admin seeded by the session fixture
    intact.

    Example::

        async def test_list_all_datasets(client, admin_auth_header, clean_tables):
            ...  # after this test, tables are truncated
    """
    yield

    # Truncate mutable catalog tables in dependency order (CASCADE handles FKs)
    tables_to_truncate = [
        "catalog.datasets",
        "catalog.records",
        "catalog.collections",
        "catalog.maps",
        "catalog.map_share_tokens",
        "catalog.api_keys",
    ]
    try:
        for table in tables_to_truncate:
            await test_db_session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        await test_db_session.commit()
    except Exception:
        # Best-effort cleanup; don't mask test failures
        await test_db_session.rollback()
