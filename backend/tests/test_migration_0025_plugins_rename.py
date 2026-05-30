"""Upgrade/downgrade round-trip test for the 0025 widgets->plugins rename.

BE-RENAME-01 acceptance: an upgrade/downgrade round-trip proving the rename is
reversible and preserves existing row/config values.

Isolation model
---------------
The project's ``conftest.py`` builds a session-scoped *template* database
migrated to head and clones a fresh per-test DB from it (see the
``_test_db_lifecycle`` session fixture and ``settings.test_database_url``).
Running a real ``alembic downgrade`` against those shared/cloned databases would
mutate schema that other tests (and, under ``-n 4``, other workers) depend on.
So this test deliberately does NOT use those fixtures.

Instead it provisions its own throwaway Postgres database (uuid-suffixed name,
parallel-safe), runs the real ``alembic upgrade head`` -> ``downgrade -1`` ->
``upgrade +1`` cycle against it with a synchronous engine, and drops the
database in teardown. Nothing shared is touched.

Driver note: the project's sync engine uses **psycopg (v3)**
(``settings.test_database_url_sync`` is ``postgresql+psycopg://...``); psycopg2
is NOT installed. We derive the throwaway DB URL from that sync URL so we use
the same installed driver alembic uses, rather than a bare ``postgresql://``
URL (which SQLAlchemy would route to the absent psycopg2).

Requires the test-DB env (``POSTGRES_HOST=localhost``, ``POSTGRES_PORT=5434``
from ``.env.test``, surfaced via ``settings.test_database_url_sync``); skips
cleanly if the database server is unreachable.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command
from alembic.config import Config
from app.core.config import settings

_REVISION = "0025_widgets_to_plugins_rename"
# A real plugin ID value — seeding with this also documents that ID values are
# preserved across the rename (they are identifiers, never renamed).
_SEED_VALUE = ["legend"]


def _sync_base_url() -> str:
    """psycopg-v3 base URL (no trailing db name) from the project's sync test URL."""
    # e.g. "postgresql+psycopg://geolens:geolens@localhost:5434/geolens_test"
    return settings.test_database_url_sync.rsplit("/", 1)[0]


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _maps_columns(engine: sa.Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("maps", schema="catalog")}


def _config_rows(engine: sa.Engine) -> dict[str, list]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT key, value FROM persistent_config "
                "WHERE key IN ('enabled_widgets', 'enabled_plugins')"
            )
        ).fetchall()
    return {key: value for key, value in rows}


@pytest.fixture
def throwaway_db_url() -> Iterator[str]:
    """Create and drop an isolated throwaway Postgres DB for this test only."""
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

    try:
        yield f"{base}/{db_name}"
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


def test_0025_upgrade_downgrade_round_trip(throwaway_db_url: str) -> None:
    cfg = _alembic_cfg(throwaway_db_url)
    engine = create_engine(throwaway_db_url)

    try:
        # 1. Upgrade to head — schema should now use the plugin vocabulary.
        command.upgrade(cfg, "head")
        cols = _maps_columns(engine)
        assert "plugins" in cols, "catalog.maps.plugins missing after upgrade"
        assert "widgets" not in cols, "catalog.maps.widgets should be gone after upgrade"

        # Seed a persistent_config row under the renamed key with a real plugin ID.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM persistent_config "
                    "WHERE key IN ('enabled_widgets','enabled_plugins')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO persistent_config (key, value) "
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
