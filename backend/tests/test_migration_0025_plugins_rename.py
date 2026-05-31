"""Upgrade/downgrade round-trip test for the 0025 widgets->plugins rename.

BE-RENAME-01 acceptance: an upgrade/downgrade round-trip proving the rename is
reversible and preserves existing row/config values.

Isolation model
---------------
The project's ``conftest.py`` builds a session-scoped *template* database
migrated to head and clones a fresh per-test DB from it. Running a real
``alembic downgrade`` against those shared/cloned databases would mutate schema
that other tests (and, under ``-n 4``, other workers) depend on. So this test
deliberately does NOT use those fixtures.

Instead it provisions its own throwaway Postgres database (uuid-suffixed name,
parallel-safe), runs the real ``alembic upgrade head`` -> ``downgrade -1`` ->
``upgrade +1`` cycle against it with a synchronous engine, and drops the
database in teardown. Nothing shared is touched.

Two deliberate choices keep this test self-contained:

1. **DB params come straight from the environment** (``POSTGRES_*`` from
   ``.env.test``), NOT from ``app.core.config.settings``. Importing the app
   settings would pull in conftest's autouse session DB fixture (which migrates
   the shared ``geolens_test`` template), coupling this isolated test to — and
   potentially corrupting — shared state. We build the psycopg-v3 URL ourselves.

2. **The throwaway DB gets its extensions created up front.** The baseline
   migration (0001) RAISES unless ``postgis`` (and the other required
   extensions) are present; a bare ``CREATE DATABASE`` inherits none, so we
   ``CREATE EXTENSION IF NOT EXISTS`` them before alembic runs.

Driver note: the project's sync engine uses **psycopg (v3)**; psycopg2 is NOT
installed. We construct a ``postgresql+psycopg://`` URL explicitly.

Skips cleanly if the database server is unreachable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command
from alembic.config import Config

# The persisted PersistentConfig store is catalog.app_settings (the AppSetting
# model), NOT a "persistent_config" table (that name in the brief is fictional).
_CONFIG_TABLE = "catalog.app_settings"
# A real plugin ID value — seeding with this also documents that ID values are
# preserved across the rename (they are identifiers, never renamed).
_SEED_VALUE = ["legend"]


def _pg_params() -> tuple[str, str, str, str]:
    """(user, password, host, port) built straight from env.

    Avoids importing app.core.config (which triggers conftest's autouse session
    DB fixture). Mirrors the ``.env.test`` values (POSTGRES_HOST=localhost,
    POSTGRES_PORT=5434).
    """
    return (
        os.environ.get("POSTGRES_USER", "geolens"),
        os.environ.get("POSTGRES_PASSWORD", "geolens"),
        os.environ.get("POSTGRES_HOST", "localhost"),
        os.environ.get("POSTGRES_PORT", "5434"),
    )


def _sync_base_url() -> str:
    """psycopg-v3 (sync) base URL, no trailing db name — for admin + reflection."""
    user, pw, host, port = _pg_params()
    return f"postgresql+psycopg://{user}:{pw}@{host}:{port}"


def _async_db_url(db_name: str) -> str:
    """asyncpg URL for a specific db — REQUIRED for alembic.

    ``alembic/env.py`` runs migrations via ``async_engine_from_config`` (an async
    engine). It honours the ``sqlalchemy.url`` we set on the Config, but that URL
    MUST use an async driver: a ``postgresql+psycopg://`` (sync) URL under the
    async engine silently fails to persist DDL (migrations appear to run but
    ``catalog.maps`` never materialises). So alembic gets ``+asyncpg`` while our
    reflection/seed engine stays on ``+psycopg`` (sync).
    """
    user, pw, host, port = _pg_params()
    return f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{db_name}"


def _alembic_cfg(async_db_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", async_db_url)
    return cfg


def _maps_columns(engine: sa.Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("maps", schema="catalog")}


def _config_rows(engine: sa.Engine) -> dict[str, list]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT key, value FROM {_CONFIG_TABLE} "
                "WHERE key IN ('enabled_widgets', 'enabled_plugins')"
            )
        ).fetchall()
    return {key: value for key, value in rows}


@pytest.fixture
def throwaway_db_name() -> Iterator[str]:
    """Create and drop an isolated throwaway Postgres DB for this test only.

    Yields the bare db name; the test derives the sync (psycopg, for reflection)
    and async (asyncpg, for alembic) URLs from it.
    """
    base = _sync_base_url()
    db_name = f"geolens_test_mig0025_{uuid.uuid4().hex[:12]}"

    try:
        admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
        with admin.begin() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        admin.dispose()
    except OperationalError as exc:  # pragma: no cover - infra guard
        pytest.skip(f"Postgres test server unreachable: {exc}")

    # A bare CREATE DATABASE has none of the prerequisites that scripts/init-db.sh
    # normally provisions, and the migration chain assumes them:
    #   - 0001_baseline RAISES unless postgis/pg_trgm/vector/unaccent exist.
    #   - 0023_geolens_readonly_role GRANTs to the cluster-level role
    #     ``geolens_readonly`` (created by init-db.sh, NOT by a migration), and
    #     references schemas ``catalog``/``data``.
    # Replicate exactly that prerequisite set (extensions + role + schemas) so the
    # full chain replays cleanly on the throwaway DB. (env.py also CREATE SCHEMA IF
    # NOT EXISTS catalog before stamping; the ``data`` schema + role are ours.)
    setup = create_engine(f"{base}/{db_name}", isolation_level="AUTOCOMMIT")
    try:
        with setup.begin() as conn:
            for ext in ("postgis", "pg_trgm", "vector", "unaccent"):
                conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS data"))
            conn.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_roles "
                    "WHERE rolname = 'geolens_readonly') THEN "
                    "CREATE ROLE geolens_readonly NOLOGIN; "
                    "END IF; END $$"
                )
            )
    finally:
        setup.dispose()

    try:
        yield db_name
    finally:
        admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
        with admin.begin() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
                )
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


def test_0025_upgrade_downgrade_round_trip(throwaway_db_name: str) -> None:
    # alembic (async_engine_from_config) gets the asyncpg URL; reflection/seeding
    # uses a sync psycopg engine on the same DB.
    cfg = _alembic_cfg(_async_db_url(throwaway_db_name))
    engine = create_engine(f"{_sync_base_url()}/{throwaway_db_name}")

    try:
        # 1. Upgrade to head — schema should now use the plugin vocabulary.
        command.upgrade(cfg, "head")
        cols = _maps_columns(engine)
        assert "plugins" in cols, "catalog.maps.plugins missing after upgrade"
        assert "widgets" not in cols, "catalog.maps.widgets should be gone after upgrade"

        # Seed an app_settings row under the renamed key with a real plugin ID.
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {_CONFIG_TABLE} "
                    "WHERE key IN ('enabled_widgets','enabled_plugins')"
                )
            )
            conn.execute(
                text(
                    f"INSERT INTO {_CONFIG_TABLE} (key, value) "
                    "VALUES ('enabled_plugins', :v)"
                ),
                {"v": '["legend"]'},
            )

        # 2. Downgrade exactly one step — both renames must reverse.
        command.downgrade(cfg, "-1")
        cols = _maps_columns(engine)
        assert "widgets" in cols, "catalog.maps.widgets missing after downgrade"
        assert "plugins" not in cols, "catalog.maps.plugins should be gone after downgrade"

        rows = _config_rows(engine)
        assert "enabled_widgets" in rows, "config key not reverted to enabled_widgets"
        assert "enabled_plugins" not in rows, "config key should not remain enabled_plugins"
        # Value preserved across the downgrade (ID strings untouched).
        assert rows["enabled_widgets"] == _SEED_VALUE, (
            f"config value not preserved on downgrade: {rows['enabled_widgets']!r}"
        )

        # 3. Re-upgrade — round-trip is idempotent and data survives.
        command.upgrade(cfg, "+1")
        cols = _maps_columns(engine)
        assert "plugins" in cols, "catalog.maps.plugins missing after re-upgrade"
        assert "widgets" not in cols, "catalog.maps.widgets should be gone after re-upgrade"

        rows = _config_rows(engine)
        assert "enabled_plugins" in rows, "config key not restored to enabled_plugins"
        assert "enabled_widgets" not in rows, "stale enabled_widgets key after re-upgrade"
        assert rows["enabled_plugins"] == _SEED_VALUE, (
            f"config value not preserved on re-upgrade: {rows['enabled_plugins']!r}"
        )
    finally:
        engine.dispose()
