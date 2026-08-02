"""The audience seam agrees with the ladder it claims to mirror (feat(#1068)).

``DefaultPermissionExtension.record_audience`` answers "which principals can
read this record?" — the set-shaped reading of the rule ``filter_visible``
already applies per user. Nothing structural keeps the two in step, so this
file compares them account by account against a real database, across every
visibility rung, every publication status, and the owner / admin / grantee /
stranger roles that each rung treats differently.

That equivalence is the whole warrant for
``find_maps_broken_by_dataset_visibility`` trusting the seam: if the two ever
disagree, the shared-map guard reports an audience that is not the one viewers
actually get, and the disagreement is invisible from the calling side.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant, Record
from app.platform.extensions import RecordAudienceQuery
from app.platform.extensions.defaults import DefaultPermissionExtension
from tests.factories import create_dataset as _create_dataset

# Every value the `chk_records_visibility` CHECK admits, and every status the
# ladder distinguishes (`published` vs anything else).
_VISIBILITIES = ("public", "internal", "restricted", "private")
_STATUSES = ("published", "draft")


class _Principals:
    """The four accounts the ladder treats differently, plus their role sets."""

    def __init__(self, owner, admin, grantee, stranger):
        self.owner = owner
        self.admin = admin
        self.grantee = grantee
        self.stranger = stranger

    @property
    def all(self):
        return (self.owner, self.admin, self.grantee, self.stranger)

    def roles(self, user):
        """What ``get_user_roles`` would return for this account.

        Only ``admin`` matters to ``filter_visible``, and it must agree with the
        role rows ``record_audience`` resolves from the database — otherwise the
        two sides are answering about different people and the comparison proves
        nothing.
        """
        return {"admin"} if user is self.admin else set()


async def _make_user(session, label: str) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"aud_{label}_{suffix}",
        email=f"aud_{label}_{suffix}@example.test",
        is_active=True,
        status="active",
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def principals(test_db_session) -> _Principals:
    """Four fresh accounts: a non-admin owner, an admin, a grantee, a stranger.

    The owner is deliberately NOT an admin. Every existing guard test owns its
    dataset as the seeded admin, which makes "the owner keeps access" and "an
    admin keeps access" the same assertion — and the audience difference relies
    on them being separate.
    """
    owner = await _make_user(test_db_session, "owner")
    admin = await _make_user(test_db_session, "admin")
    grantee = await _make_user(test_db_session, "grantee")
    stranger = await _make_user(test_db_session, "stranger")

    admin_role = (
        await test_db_session.execute(select(Role).where(Role.name == "admin"))
    ).scalar_one()
    test_db_session.add(UserRole(user_id=admin.id, role_id=admin_role.id))
    await test_db_session.commit()
    return _Principals(owner, admin, grantee, stranger)


@pytest.fixture
async def granted_dataset(test_db_session, principals: _Principals):
    """A dataset owned by ``principals.owner`` with a grant reaching the grantee."""
    dataset = await _create_dataset(
        test_db_session,
        created_by=principals.owner.id,
        name=f"Audience DS {uuid.uuid4().hex[:6]}",
        visibility="private",
        record_status="published",
    )
    role = Role(name=f"aud-grant-{uuid.uuid4().hex[:8]}")
    test_db_session.add(role)
    await test_db_session.flush()
    test_db_session.add(UserRole(user_id=principals.grantee.id, role_id=role.id))
    test_db_session.add(DatasetGrant(dataset_id=dataset.id, role_id=role.id))
    await test_db_session.commit()
    return dataset


async def _readers_via_filter_visible(
    session, record, principals: _Principals, grant_cls
) -> set[uuid.UUID]:
    """The accounts whose filtered query returns the record — the per-user rule."""
    extension = DefaultPermissionExtension()
    readers = set()
    for user in principals.all:
        stmt = extension.filter_visible(
            select(Record.id).where(Record.id == record.id),
            SimpleNamespace(id=user.id),
            principals.roles(user),
            Record,
            grant_cls,
        )
        if (await session.execute(stmt)).scalar_one_or_none() is not None:
            readers.add(user.id)
    return readers


async def _readers_via_record_audience(
    session, dataset, record, principals: _Principals, grant_cls
) -> set[uuid.UUID]:
    """The same accounts, selected by the audience predicate — the set-shaped rule."""
    audience = await DefaultPermissionExtension().record_audience(
        RecordAudienceQuery(
            dataset_id=dataset.id,
            record_id=record.id,
            owner_id=record.created_by,
            visibility=record.visibility,
            record_status=record.record_status,
        ),
        User,
        grant_cls=grant_cls,
    )
    rows = await session.execute(
        select(User.id)
        .where(audience.users)
        .where(User.id.in_([user.id for user in principals.all]))
    )
    return set(rows.scalars())


@pytest.mark.parametrize("visibility", _VISIBILITIES)
@pytest.mark.parametrize("record_status", _STATUSES)
async def test_the_audience_is_exactly_who_filter_visible_admits(
    test_db_session,
    principals: _Principals,
    granted_dataset,
    visibility: str,
    record_status: str,
):
    """feat(#1068): the two readings of the ladder name the same accounts.

    Sixteen cells, each covering a rung the ladder handles differently: the
    creator exemption on ``private`` and ``restricted``, the grant on
    ``restricted``, the admin bypass everywhere, and the status gate that hides
    an unpublished record from everyone but its owner.
    """
    record = granted_dataset.record
    record.visibility = visibility
    record.record_status = record_status
    await test_db_session.commit()

    via_filter = await _readers_via_filter_visible(
        test_db_session, record, principals, DatasetGrant
    )
    via_audience = await _readers_via_record_audience(
        test_db_session, granted_dataset, record, principals, DatasetGrant
    )

    assert via_audience == via_filter
    # A cell where nobody at all can read would satisfy the equality above
    # trivially; the admin bypass means no cell is ever empty.
    assert principals.admin.id in via_filter


@pytest.mark.parametrize("visibility", _VISIBILITIES)
async def test_the_audience_is_empty_of_grantees_without_a_grant_class(
    test_db_session,
    principals: _Principals,
    granted_dataset,
    visibility: str,
):
    """A missing ``grant_cls`` drops the restricted rung on both sides.

    ``filter_visible`` appends no restricted condition when it has no grant
    class, which makes a restricted record unreachable rather than ungated —
    even by its owner. The audience has to be unreachable in the same way, or a
    caller that cannot supply the grant table gets a more permissive answer than
    the reads it is reasoning about.
    """
    record = granted_dataset.record
    record.visibility = visibility
    record.record_status = "published"
    await test_db_session.commit()

    via_filter = await _readers_via_filter_visible(
        test_db_session, record, principals, None
    )
    via_audience = await _readers_via_record_audience(
        test_db_session, granted_dataset, record, principals, None
    )

    assert via_audience == via_filter
    if visibility == "restricted":
        assert via_filter == {principals.admin.id}


async def test_the_anonymous_flag_matches_the_anonymous_filter(
    test_db_session,
    principals: _Principals,
    granted_dataset,
):
    """``includes_anonymous`` tracks ``filter_visible(user=None)`` on every cell.

    Anonymous visitors are rows in no table, so the flag is the only place the
    public map's audience can come from. Public+published is the one cell that
    admits them, and the assertion is written as an equivalence over all of them
    so a widened anonymous rung cannot pass by matching the one expected True.
    """
    extension = DefaultPermissionExtension()
    record = granted_dataset.record

    for visibility in _VISIBILITIES:
        for record_status in _STATUSES:
            record.visibility = visibility
            record.record_status = record_status
            await test_db_session.commit()

            anonymous_stmt = extension.filter_visible(
                select(Record.id).where(Record.id == record.id),
                None,
                set(),
                Record,
                DatasetGrant,
            )
            anonymous_reads = (
                await test_db_session.execute(anonymous_stmt)
            ).scalar_one_or_none() is not None
            audience = await extension.record_audience(
                RecordAudienceQuery(
                    dataset_id=granted_dataset.id,
                    record_id=record.id,
                    owner_id=record.created_by,
                    visibility=visibility,
                    record_status=record_status,
                ),
                User,
                grant_cls=DatasetGrant,
            )
            assert audience.includes_anonymous is anonymous_reads, (
                f"{visibility}/{record_status}"
            )


async def test_an_unrecognised_visibility_reaches_only_admins(
    test_db_session,
    principals: _Principals,
    granted_dataset,
):
    """A rung the ladder does not name is unreachable, not ungated.

    ``chk_records_visibility`` keeps such a value out of the database, so this
    one cannot be cross-checked against a stored record — but the branch exists
    because ``filter_visible`` builds no condition for an unknown value either,
    and a fall-through that admitted everyone would be the same class of silent
    widening this seam was added to close.
    """
    audience = await DefaultPermissionExtension().record_audience(
        RecordAudienceQuery(
            dataset_id=granted_dataset.id,
            record_id=granted_dataset.record_id,
            owner_id=principals.owner.id,
            visibility="sensitive",
            record_status="published",
        ),
        User,
        grant_cls=DatasetGrant,
    )
    rows = await test_db_session.execute(
        select(User.id)
        .where(audience.users)
        .where(User.id.in_([user.id for user in principals.all]))
    )
    assert set(rows.scalars()) == {principals.admin.id}
    assert audience.includes_anonymous is False
