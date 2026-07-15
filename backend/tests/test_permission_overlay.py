"""Composed integration tests for the enterprise ABAC PermissionExtension.

These exercise the private overlay's ``EnterprisePermissionExtension.filter_visible``
against the REAL core models (``Record`` / ``DatasetGrant`` / ``User`` /
``UserRole``) and a REAL Postgres database, so a core column rename
(``sensitivity_classification`` / ``owner_org`` / ``spatial_extent``) or a
baseline that silently *widens* is caught. The overlay's own suite can only
compile the ABAC predicate against a test-local ``_Record`` fake, so this file
is the composed counterpart that lives in CORE (only core ships the ORM model +
DB fixtures). See enterprise-overlay-audit-20260715 §6 and enterprise issue #13.

Skip-not-fail: the overlay is imported via ``pytest.importorskip`` inside the
``enterprise_permission`` fixture, exactly like conftest's
``saml_overlay_registered``. An OSS checkout without ``geolens_enterprise``
SKIPS these tests instead of failing collection; the overlay's cross-repo CI job
installs the overlay and forces them to run.

ABAC is inert unless ``GEOLENS_PERM_ABAC_MODE=role``. Each test sets the mode
via ``monkeypatch`` BEFORE constructing the extension, because
``load_policy()`` reads the environment at construction time.
"""

from __future__ import annotations

import json
import uuid

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.platform.extensions.defaults import DefaultPermissionExtension

# A 10x10 degree box used as the ABAC region for the spatial-straddle tests.
REGION_WKT = "POLYGON((0 0, 0 10, 10 10, 10 0, 0 0))"
EXTENT_INSIDE = "POLYGON((2 2, 2 4, 4 4, 4 2, 2 2))"  # fully within REGION
EXTENT_OUTSIDE = "POLYGON((20 20, 20 22, 22 22, 22 20, 20 20))"  # fully outside
EXTENT_STRADDLE = "POLYGON((8 8, 8 12, 12 12, 12 8, 8 8))"  # crosses the boundary


@pytest.fixture
def enterprise_permission():
    """Import the overlay's permission package or SKIP (never fail).

    Mirrors conftest's ``saml_overlay_registered``: the deferred
    ``pytest.importorskip`` keeps collection working in community-only
    environments while the overlay CI job forces a real run.
    """
    return pytest.importorskip(
        "geolens_enterprise.permission",
        reason="geolens_enterprise package is not installed",
    )


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _add_user(session) -> User:
    user = User(username=_unique("abac_user"), status="active", is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _add_record(
    session,
    *,
    visibility: str = "public",
    record_status: str = "published",
    sensitivity: str | None = None,
    owner_org: str | None = None,
    extent_wkt: str | None = None,
    created_by: uuid.UUID | None = None,
) -> Record:
    record = Record(
        title=_unique("record"),
        visibility=visibility,
        record_status=record_status,
        record_type="vector_dataset",
        sensitivity_classification=sensitivity,
        owner_org=owner_org,
        spatial_extent=(
            WKTElement(extent_wkt, srid=4326) if extent_wkt is not None else None
        ),
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    return record


async def _grant_dataset(session, record: Record, role: Role) -> None:
    """Wire a real DatasetGrant so the default's restricted-grant JOIN runs
    against real ``Dataset`` / ``DatasetGrant`` / ``UserRole`` rows."""
    dataset = Dataset(record_id=record.id, table_name=_unique("tbl"))
    session.add(dataset)
    await session.flush()
    session.add(DatasetGrant(dataset_id=dataset.id, role_id=role.id))
    await session.flush()


async def _visible_ids(session, stmt) -> set[uuid.UUID]:
    result = await session.execute(stmt)
    return set(result.scalars().all())


async def test_filter_visible_subset_invariant(
    enterprise_permission, test_db_session, clean_tables, monkeypatch
):
    """Overlay filter is always a SUBSET of the community baseline, and it
    genuinely narrows for a plain user — exercised for admin, a plain user with
    a dataset grant, and an anonymous caller against real seeded rows."""
    session = test_db_session
    role_name = _unique("analyst")

    owner = await _add_user(session)
    plain_user = await _add_user(session)

    # Real role + grant so the plain user carries a dataset grant (drift tripwire
    # on DatasetGrant/UserRole schema); the overlay narrows regardless of it.
    granted_role = Role(name=role_name, description="ABAC test role")
    session.add(granted_role)
    await session.flush()
    session.add(UserRole(user_id=plain_user.id, role_id=granted_role.id))
    await session.flush()

    rec_a = await _add_record(
        session, sensitivity="internal", owner_org="alpha", created_by=owner.id
    )  # allowed by ABAC (internal <= confidential, org alpha)
    rec_b = await _add_record(
        session, sensitivity="restricted", owner_org="alpha", created_by=owner.id
    )  # narrowed out: classification above clearance
    rec_c = await _add_record(
        session, sensitivity="internal", owner_org="beta", created_by=owner.id
    )  # narrowed out: org not in allow-list
    rec_d = await _add_record(
        session, sensitivity=None, owner_org="alpha", created_by=owner.id
    )  # narrowed out: NULL sensitivity -> most-restrictive under "restricted"
    rec_restricted = await _add_record(
        session,
        visibility="restricted",
        sensitivity="internal",
        owner_org="alpha",
        created_by=owner.id,
    )
    await _grant_dataset(session, rec_restricted, granted_role)
    await session.commit()

    seeded = {rec_a.id, rec_b.id, rec_c.id, rec_d.id, rec_restricted.id}

    monkeypatch.setenv("GEOLENS_PERM_ABAC_MODE", "role")
    monkeypatch.setenv(
        "GEOLENS_PERM_ROLE_POLICY",
        json.dumps({role_name: {"clearance": "confidential", "orgs": ["alpha"]}}),
    )

    default = DefaultPermissionExtension()
    overlay = enterprise_permission.EnterprisePermissionExtension()

    # --- plain user with a dataset grant: overlay strictly narrows ---
    base_plain = await _visible_ids(
        session,
        default.filter_visible(
            select(Record.id), plain_user, {role_name}, Record, DatasetGrant
        ),
    )
    over_plain = await _visible_ids(
        session,
        overlay.filter_visible(
            select(Record.id), plain_user, {role_name}, Record, DatasetGrant
        ),
    )
    assert over_plain <= base_plain  # global subset invariant (never widens)
    assert rec_a.id in over_plain
    assert {rec_b.id, rec_c.id, rec_d.id} <= base_plain  # visible at baseline
    assert not ({rec_b.id, rec_c.id, rec_d.id} & over_plain)  # narrowed out
    # fix(#515): the grant path must be LIVE — the restricted record reaches the
    # baseline via Dataset.record_id -> DatasetGrant -> UserRole, and survives
    # the ABAC narrowing because it is internal/alpha (within policy).
    assert rec_restricted.id in base_plain
    assert rec_restricted.id in over_plain

    # --- admin: admin_bypass -> overlay == baseline (equal, still a subset) ---
    base_admin = await _visible_ids(
        session,
        default.filter_visible(
            select(Record.id), plain_user, {"admin"}, Record, DatasetGrant
        ),
    )
    over_admin = await _visible_ids(
        session,
        overlay.filter_visible(
            select(Record.id), plain_user, {"admin"}, Record, DatasetGrant
        ),
    )
    assert over_admin <= base_admin
    assert seeded <= over_admin  # admin sees all seeded rows, unfiltered

    # --- anonymous caller: overlay short-circuits to the baseline (inert) ---
    base_anon = await _visible_ids(
        session,
        default.filter_visible(select(Record.id), None, set(), Record, DatasetGrant),
    )
    over_anon = await _visible_ids(
        session,
        overlay.filter_visible(select(Record.id), None, set(), Record, DatasetGrant),
    )
    assert (over_anon & seeded) == (base_anon & seeded)
    assert rec_a.id in over_anon  # public + published stays visible
    assert rec_restricted.id not in base_anon  # grants never leak to anonymous


async def test_filter_visible_spatial_straddle_within_excludes(
    enterprise_permission, test_db_session, clean_tables, monkeypatch
):
    """Under the default ``within`` predicate, a record whose extent straddles
    the region boundary is EXCLUDED — only fully-contained extents pass."""
    session = test_db_session
    role_name = _unique("geo")
    user = await _add_user(session)

    inside = await _add_record(session, sensitivity="public", extent_wkt=EXTENT_INSIDE)
    outside = await _add_record(
        session, sensitivity="public", extent_wkt=EXTENT_OUTSIDE
    )
    straddle = await _add_record(
        session, sensitivity="public", extent_wkt=EXTENT_STRADDLE
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_PERM_ABAC_MODE", "role")
    monkeypatch.setenv("GEOLENS_PERM_SPATIAL_PREDICATE", "within")
    monkeypatch.setenv(
        "GEOLENS_PERM_ROLE_POLICY",
        json.dumps({role_name: {"clearance": "restricted", "region_wkt": REGION_WKT}}),
    )

    overlay = enterprise_permission.EnterprisePermissionExtension()
    visible = await _visible_ids(
        session,
        overlay.filter_visible(
            select(Record.id), user, {role_name}, Record, DatasetGrant
        ),
    )

    seeded = {inside.id, outside.id, straddle.id}
    assert visible & seeded == {inside.id}


async def test_filter_visible_spatial_straddle_intersects_includes(
    enterprise_permission, test_db_session, clean_tables, monkeypatch
):
    """Switching the predicate to ``intersects`` INCLUDES the straddling record
    (any overlap qualifies) while the fully-outside record stays excluded."""
    session = test_db_session
    role_name = _unique("geo")
    user = await _add_user(session)

    inside = await _add_record(session, sensitivity="public", extent_wkt=EXTENT_INSIDE)
    outside = await _add_record(
        session, sensitivity="public", extent_wkt=EXTENT_OUTSIDE
    )
    straddle = await _add_record(
        session, sensitivity="public", extent_wkt=EXTENT_STRADDLE
    )
    await session.commit()

    monkeypatch.setenv("GEOLENS_PERM_ABAC_MODE", "role")
    monkeypatch.setenv("GEOLENS_PERM_SPATIAL_PREDICATE", "intersects")
    monkeypatch.setenv(
        "GEOLENS_PERM_ROLE_POLICY",
        json.dumps({role_name: {"clearance": "restricted", "region_wkt": REGION_WKT}}),
    )

    overlay = enterprise_permission.EnterprisePermissionExtension()
    visible = await _visible_ids(
        session,
        overlay.filter_visible(
            select(Record.id), user, {role_name}, Record, DatasetGrant
        ),
    )

    seeded = {inside.id, outside.id, straddle.id}
    assert visible & seeded == {inside.id, straddle.id}


async def test_filter_visible_inert_when_mode_unset(
    enterprise_permission, test_db_session, clean_tables, monkeypatch
):
    """With ABAC mode unset the overlay returns EXACTLY the delegate result —
    same rows and the same compiled statement (no narrowing clause added)."""
    session = test_db_session
    monkeypatch.delenv("GEOLENS_PERM_ABAC_MODE", raising=False)
    user = await _add_user(session)
    rec = await _add_record(session, sensitivity="restricted", created_by=user.id)
    await session.commit()

    default = DefaultPermissionExtension()
    overlay = enterprise_permission.EnterprisePermissionExtension()

    base_stmt = default.filter_visible(
        select(Record.id), user, {"viewer"}, Record, DatasetGrant
    )
    over_stmt = overlay.filter_visible(
        select(Record.id), user, {"viewer"}, Record, DatasetGrant
    )

    assert str(over_stmt) == str(base_stmt)  # no restrictive clause appended
    assert await _visible_ids(session, over_stmt) == await _visible_ids(
        session, base_stmt
    )
    assert rec.id in await _visible_ids(session, over_stmt)  # own record visible


def test_abac_clause_compiles_against_real_record_columns(
    enterprise_permission, monkeypatch
):
    """The restrictive clause must reference the REAL Record columns; a rename of
    sensitivity_classification / owner_org / spatial_extent trips this guard even
    without a database."""
    from geolens_enterprise.permission.policy import load_policy
    from geolens_enterprise.permission.predicates import build_abac_clause

    role_name = _unique("compile")
    monkeypatch.setenv("GEOLENS_PERM_ABAC_MODE", "role")
    monkeypatch.setenv(
        "GEOLENS_PERM_ROLE_POLICY",
        json.dumps(
            {
                role_name: {
                    "clearance": "confidential",
                    "region_wkt": REGION_WKT,
                    "orgs": ["alpha"],
                }
            }
        ),
    )

    policy = load_policy()
    scope = policy.resolve({role_name})
    clause_sql = str(build_abac_clause(Record, scope, policy))

    assert "sensitivity_classification" in clause_sql
    assert "owner_org" in clause_sql
    assert "spatial_extent" in clause_sql
