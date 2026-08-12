"""Tests for the shared alembic runner (fix(#933)).

Proves each normalization does its one job, so that committed state no longer
makes a downgrade past a refuse-to-coerce migration fail for whichever
unrelated migration test happens to share the xdist worker:

- an antimeridian-crossing (MULTIPOLYGON) ``spatial_extent`` past
  ``0030_records_spatial_extent_type``
- an expiring API key or a bumped ``key_epoch`` past
  ``0029_api_key_hardening`` (fix(#1016))

The 0029 tests also cover the guard itself: that it fires on a database
holding that state, and that a clean database still downgrades.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tests.alembic_helpers import (
    enterprise_migrations_present,
    normalize_seam_extents,
    run_alembic,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

# 0029 is the revision under test; downgrading TO it leaves it applied, so the
# guard must be crossed by going one step further back.
_PRE_API_KEY_HARDENING = "0028_oauth_email_verified_backfill"


@pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)
async def test_seam_extent_no_longer_breaks_downgrade_past_0030(test_db_session):
    """The exact #924/#933 failure, reproduced then absorbed by the runner.

    A two-ring seam extent is committed, then a downgrade crossing 0030 runs
    via ``run_alembic`` — which normalizes first, so the refuse-to-coerce
    guard never fires. Without the normalization this downgrade exits 1 with
    ``RuntimeError: 1 catalog.records row(s) hold a MULTIPOLYGON``.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Seam Extent {uuid.uuid4().hex[:8]}",
    )
    # A Fiji-style extent split at the antimeridian: two rings, one on each
    # side — exactly what 0030's downgrade refuses to coerce.
    await test_db_session.execute(
        text(
            """
            UPDATE catalog.records SET spatial_extent = ST_GeomFromText(
              'MULTIPOLYGON(((177 -20, 180 -20, 180 -16, 177 -16, 177 -20)),
                            ((-180 -20, -178 -20, -178 -16, -180 -16, -180 -20)))',
              4326)
            WHERE id = :rid
            """
        ),
        {"rid": str(ds.record_id)},
    )
    await test_db_session.commit()

    try:
        down = run_alembic("downgrade", "0029_api_key_hardening")
        assert down.returncode == 0, (
            "downgrade past 0030 failed despite seam-extent normalization:\n"
            f"stdout:\n{down.stdout}\nstderr:\n{down.stderr}"
        )
    finally:
        # Leave the worker DB at head for sibling tests even on failure.
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, (
            f"re-upgrade to head failed:\nstdout:\n{up.stdout}\nstderr:\n{up.stderr}"
        )
    # The seeded row survives with its extent collapsed to the envelope —
    # acceptable loss in a test database, which is the helper's whole premise.


async def _seed_expiring_key(session, *, epoch_bump: bool) -> None:
    """Give the admin user an API key with an expiry, optionally bumping the
    owner's key_epoch — the two states 0029's downgrade refuses to drop."""
    admin_id = await get_user_id(session, "admin")
    await session.execute(
        text(
            """
            INSERT INTO catalog.api_keys
                (user_id, key_hash, name, is_active, expires_at, key_epoch)
            SELECT :uid, :hash, :name, true, :expires, u.key_epoch
            FROM catalog.users u WHERE u.id = :uid
            """
        ),
        {
            "uid": str(admin_id),
            "hash": f"guard-{uuid.uuid4().hex}",
            "name": "1016 guard fixture",
            "expires": datetime.now(timezone.utc) + timedelta(days=1),
        },
    )
    if epoch_bump:
        await session.execute(
            text("UPDATE catalog.users SET key_epoch = key_epoch + 1 WHERE id = :uid"),
            {"uid": str(admin_id)},
        )
    await session.commit()


@pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)
async def test_downgrade_past_0029_refuses_while_key_state_exists(test_db_session):
    """fix(#1016): the guard fires, and its message is actionable.

    ``normalize=False`` deliberately bypasses the runner's cleanup so the
    refusal itself is what is under test.
    """
    await _seed_expiring_key(test_db_session, epoch_bump=True)
    # 0030 is crossed on the way to 0029, so clear ITS state explicitly —
    # otherwise a seam extent left by a sibling test in this worker would fire
    # the wrong guard and the assertions below would test nothing.
    normalize_seam_extents()

    try:
        down = run_alembic("downgrade", _PRE_API_KEY_HARDENING, normalize=False)
        assert down.returncode != 0, (
            "0029 downgraded with expiry and epoch state present — expired keys "
            "would come back permanent and epoch-revoked keys would come back "
            f"live:\nstdout:\n{down.stdout}\nstderr:\n{down.stderr}"
        )
        combined = down.stdout + down.stderr
        # The counts, the inspection query, and the opt-out SQL: an operator
        # hitting this on a DR day needs all three without leaving the terminal.
        assert "API key(s) carry an expiry" in combined
        assert "SELECT ak.id, ak.user_id, ak.expires_at" in combined
        assert "DELETE FROM catalog.api_keys" in combined
        assert "UPDATE catalog.users SET key_epoch = 1" in combined
    finally:
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, (
            f"re-upgrade to head failed:\nstdout:\n{up.stdout}\nstderr:\n{up.stderr}"
        )


@pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)
async def test_key_state_no_longer_breaks_downgrade_past_0029(test_db_session):
    """fix(#1016): the same state, absorbed by the runner.

    This is the #933 shape. ``test_api_key_auth.py`` commits both an expiring
    key and a key_epoch bump and cleans up neither, so without the
    normalization every downgrade crossing 0029 — six files, twenty-plus call
    sites, all of them heading for 0004/0005/0009 — would fail depending only
    on which xdist worker the auth suite landed on.
    """
    await _seed_expiring_key(test_db_session, epoch_bump=True)

    try:
        down = run_alembic("downgrade", _PRE_API_KEY_HARDENING)
        assert down.returncode == 0, (
            "downgrade past 0029 failed despite API-key state normalization:\n"
            f"stdout:\n{down.stdout}\nstderr:\n{down.stderr}"
        )
    finally:
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, (
            f"re-upgrade to head failed:\nstdout:\n{up.stdout}\nstderr:\n{up.stderr}"
        )


@pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)
async def test_clean_database_still_downgrades_past_0029(test_db_session):
    """fix(#1016): the guard is state-dependent, not a blanket refusal.

    Runs with ``normalize=False`` so nothing clears state on the way through —
    a database that never held an expiry or an epoch bump downgrades on its
    own, which is what makes the refusal above meaningful.
    """
    await test_db_session.execute(
        text(
            "UPDATE catalog.api_keys SET expires_at = NULL WHERE expires_at IS NOT NULL"
        )
    )
    await test_db_session.execute(
        text("UPDATE catalog.users SET key_epoch = 1 WHERE key_epoch <> 1")
    )
    await test_db_session.commit()
    normalize_seam_extents()  # see the note in the refusal test above

    try:
        down = run_alembic("downgrade", _PRE_API_KEY_HARDENING, normalize=False)
        assert down.returncode == 0, (
            "a database with no key expiry or epoch state was still refused:\n"
            f"stdout:\n{down.stdout}\nstderr:\n{down.stderr}"
        )
    finally:
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, (
            f"re-upgrade to head failed:\nstdout:\n{up.stdout}\nstderr:\n{up.stderr}"
        )
