"""fix(#1858): attempt-scoped staging tables are hidden and unregisterable.

``attempt_scoped_staging_table`` (``platform/jobs/heartbeat.py``) produces
``<base>_staging_<32 hex>``. Table discovery excluded ``%_staging`` and
``%_old``, and neither pattern matches that name, so a staging table left
behind by a worker killed between ``run_ogr2ogr`` and the swap was listed by
``GET /ingest/discover/`` and registerable through
``POST /ingest/register/bulk/`` as a permanent dataset. Nothing reaps such a
table: the sweeps in ``platform/jobs/sweep.py`` cover storage objects,
analysis outputs and VRT generations, and none of them looks at PostGIS
tables. Reaping orphans is deliberately out of scope here; hiding and refusing
them is what this pins.

The predicate is one POSIX regular expression evaluated by two engines --
PostgreSQL's ``~`` in the discovery query, Python's ``re`` in the registration
refusal -- so the first test checks the two against each other rather than
trusting that they agree.
"""

import uuid as _uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.heartbeat import (
    ATTEMPT_STAGING_NAME_PATTERN,
    attempt_scoped_staging_table,
    is_attempt_scoped_staging_table,
)
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio


# The producer's own output, plus the names that must stay registerable.
# `generate_table_name` slugifies a user-chosen title, so every entry below
# with `expected=False` is a name an operator can legitimately ask for.
_NAMES: list[tuple[str, bool]] = [
    ("parcels", False),
    ("parcels_staging", False),
    ("parcels_old", False),
    ("parcels_staging_area", False),
    ("staging", False),
    # Right shape, wrong length: 31 and 33 hex characters.
    ("parcels_staging_" + "a" * 31, False),
    ("parcels_staging_" + "a" * 33, False),
    # Right length, not hexadecimal.
    ("parcels_staging_" + "z" * 32, False),
    ("parcels_staging_03ff872f1a2b4c5d8e9f0a1b2c3d4e5f", True),
    ("_staging_03ff872f1a2b4c5d8e9f0a1b2c3d4e5f", True),
]


def test_the_producer_and_the_recognizer_agree() -> None:
    """Whatever the producer makes, the recognizer knows.

    The two live next to each other for this reason: a change to the suffix
    that did not reach the pattern would silently reopen the hole, and this is
    the assertion that would not survive it.
    """
    for base in ("parcels", "a", "x" * 80):
        name = attempt_scoped_staging_table(base, _uuid.uuid4())
        assert is_attempt_scoped_staging_table(name), name
        assert len(name) <= 63


@pytest.mark.parametrize(("name", "expected"), _NAMES)
def test_python_reads_the_pattern_as_intended(name: str, expected: bool) -> None:
    assert is_attempt_scoped_staging_table(name) is expected


async def test_postgres_reads_the_pattern_the_same_way(
    test_db_session: AsyncSession,
) -> None:
    """The discovery query evaluates the pattern; the refusal evaluates it in
    Python. One string, two engines, and nothing else checks that they agree.

    This is also the measurement the audit made against the live database: the
    old ``NOT LIKE '%\\_staging'`` predicate answered "keep" for
    ``parcels_staging_03ff872f...``.
    """
    for name, expected in _NAMES:
        matched = await test_db_session.scalar(
            text("SELECT :name ~ :pattern").bindparams(
                name=name, pattern=ATTEMPT_STAGING_NAME_PATTERN
            )
        )
        assert matched is expected, name


async def test_discovery_omits_a_leaked_staging_table(
    test_db_session: AsyncSession,
) -> None:
    """The failure the audit found: a leaked staging table offered for import.

    A sibling ordinary table is created alongside it and asserted present, so
    a discovery call that returned nothing at all cannot pass this.
    """
    from app.processing.ingest.service import discover_unregistered_tables

    prefix = f"sec6_{_uuid.uuid4().hex[:8]}"
    ordinary = f"{prefix}_parcels"
    leaked = attempt_scoped_staging_table(ordinary, _uuid.uuid4())

    for table in (ordinary, leaked):
        await test_db_session.execute(
            text(f'CREATE TABLE data."{table}" (gid serial PRIMARY KEY, name text)')
        )
    await test_db_session.commit()

    try:
        found = {
            table.table_name
            for table in await discover_unregistered_tables(test_db_session, limit=5000)
        }
        assert ordinary in found
        assert leaked not in found
    finally:
        await test_db_session.rollback()
        for table in (ordinary, leaked):
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{table}" CASCADE')
            )
        await test_db_session.commit()


async def test_registration_refuses_a_staging_table(
    test_db_session: AsyncSession,
) -> None:
    """Hiding one was never the same as refusing it.

    ``POST /ingest/register/bulk/`` takes the table name from the caller, so
    the discovery filter never stood between a leaked staging table and a
    permanent dataset bound to it.
    """
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import register_existing_table

    admin_id = await get_user_id(test_db_session, "admin")
    leaked = attempt_scoped_staging_table(
        f"sec6_{_uuid.uuid4().hex[:8]}_parcels", _uuid.uuid4()
    )

    await test_db_session.execute(
        text(f'CREATE TABLE data."{leaked}" (gid serial PRIMARY KEY, name text)')
    )
    await test_db_session.commit()

    try:
        with pytest.raises(ValueError) as excinfo:
            await register_existing_table(
                test_db_session,
                RegisterRequest(table_name=leaked, title="Leaked Staging"),
                SimpleNamespace(id=admin_id),
            )

        message = str(excinfo.value)
        # The name has to be in it: an operator looking at a list of tables
        # needs to know which one was refused.
        assert leaked in message
        assert "staging" in message
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{leaked}" CASCADE')
        )
        await test_db_session.commit()
