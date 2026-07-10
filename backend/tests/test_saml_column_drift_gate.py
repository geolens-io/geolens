"""fix(#435): `alembic check` must see drift on the four core-owned SAML columns.

`env.py`'s `include_object` hid `idp_entity_id`, `idp_sso_url`, `idp_certificate`,
and `sp_entity_id` from autogenerate whenever no enterprise overlay was installed.
That was right when only the overlay's `e002_add_saml_columns` created them. Core
migration `0008_oauth_saml_columns` now creates all four on every OSS database, so
the exclusion had turned into a blind spot: dropping one still passed the gate.

The positive case (`alembic check` clean at head, columns present and included) is
covered by `TestAlembicCheckNoDrift` in `test_email_verification_migration.py`.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import text

_BACKEND_DIR = Path(__file__).resolve().parent.parent

SAML_COLUMNS = ("idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id")


def _enterprise_migrations_present() -> bool:
    from alembic.config import Config

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    return " " in (cfg.get_main_option("version_locations") or "").strip()


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason="OSS migration drift gate; multi-head under the enterprise overlay",
)


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    from app.core.config import settings

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    env["POSTGRES_DB"] = settings.postgres_db_test
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


def _autocommit_engine():
    from app.core.config import settings

    return sqlalchemy.create_engine(
        settings.test_database_url_sync, isolation_level="AUTOCOMMIT"
    )


def test_env_py_does_not_filter_saml_columns() -> None:
    """Fast guard: no SAML column may be named in `env.py`'s object filter.

    `env.py` runs migrations on import, so read its source rather than importing it.
    """
    source = (_BACKEND_DIR / "alembic" / "env.py").read_text()

    for column in SAML_COLUMNS:
        assert column not in source, (
            f"{column} is named in alembic/env.py — the OSS-only SAML exclusion is "
            "back, and the drift gate is blind to a core-owned column again"
        )


@_SKIP_UNDER_OVERLAY
def test_alembic_check_fails_when_a_saml_column_is_dropped() -> None:
    """Drop one column, prove the gate fails, then put it back.

    Pre-fix this test would have passed `alembic check` with the column missing.
    """
    _run_alembic("upgrade", "head")

    engine = _autocommit_engine()
    try:
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE catalog.oauth_providers DROP COLUMN idp_sso_url")
            )
        try:
            result = _run_alembic("check")
            assert result.returncode != 0, (
                "alembic check passed with catalog.oauth_providers.idp_sso_url "
                "dropped — the drift gate is blind to core-owned SAML columns.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
            assert "idp_sso_url" in (result.stdout + result.stderr)
        finally:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE catalog.oauth_providers "
                        "ADD COLUMN IF NOT EXISTS idp_sso_url VARCHAR(512)"
                    )
                )
    finally:
        engine.dispose()

    restored = _run_alembic("check")
    assert restored.returncode == 0, (
        f"drift gate still failing after restore:\n{restored.stdout}{restored.stderr}"
    )
