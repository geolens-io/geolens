"""Inherited-keyword derivation and disclosure warnings (feat #1070).

An analysis output carries a COPY of its source record's keywords
(``apply_analysis_provenance``); nothing marks the copied rows. These tests
pin the read-time derivation in ``records/inherited.py``: the inherited set is
the intersection of the record's keyword triples with its ``derived_from``
source's, the keywords endpoint marks it (gated on source access, like the
``derived_from`` reference itself), and the ``update_user_metadata``
chokepoint warns — on BOTH widening axes, visibility and record_status —
when the resolved state lets someone who cannot open the source read them.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordKeyword,
)
from app.modules.catalog.datasets.domain.schemas import DatasetMeta
from app.modules.catalog.datasets.domain.service import update_user_metadata
from app.modules.catalog.records.inherited import (
    disclosed_inherited_keywords,
    inherited_keyword_keys,
    resolve_inherited_source,
)

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _derived_pair(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    source_visibility: str = "private",
    derived_visibility: str = "private",
    derived_status: str = "published",
    source_keywords: tuple[str, ...] = ("codename",),
    copy_keywords: bool = True,
    own_keywords: tuple[str, ...] = (),
) -> tuple[Dataset, Dataset, Record, Record]:
    """A source dataset and a dataset derived from it, keywords included.

    Constructs its own rows rather than running the worker's materialize path:
    the derivation under test reads only ``derived_from`` and the keyword
    tables, and building the absence cases (no copy, deleted source) needs
    direct control over both.
    """
    source = await create_dataset(
        session,
        created_by=owner_id,
        visibility=source_visibility,
        name=f"Source {uuid.uuid4().hex[:6]}",
    )
    derived = await create_dataset(
        session,
        created_by=owner_id,
        visibility=derived_visibility,
        record_status=derived_status,
        name=f"Derived {uuid.uuid4().hex[:6]}",
    )
    source_record = await session.get(Record, source.record_id)
    derived_record = await session.get(Record, derived.record_id)
    assert source_record is not None and derived_record is not None
    for kw in source_keywords:
        session.add(
            RecordKeyword(record_id=source_record.id, keyword=kw, keyword_type="theme")
        )
        if copy_keywords:
            session.add(
                RecordKeyword(
                    record_id=derived_record.id, keyword=kw, keyword_type="theme"
                )
            )
    for kw in own_keywords:
        session.add(
            RecordKeyword(record_id=derived_record.id, keyword=kw, keyword_type="theme")
        )
    derived_record.derived_from = {
        "dataset_id": str(source.id),
        "operation": "buffer",
        "params": {},
        "created_at": "2026-08-03T00:00:00+00:00",
    }
    await session.commit()
    return source, derived, source_record, derived_record


async def _add_plain_user(session: AsyncSession) -> User:
    """An active, role-less, non-admin account this test constructs itself.

    The audience-gap query needs a real signed-in account standing in the
    widened audience; admin fixtures cannot serve (admins are in every
    audience), and borrowing a shared fixture role would couple the test to
    fixture ordering.
    """
    user = User(
        username=f"plain_{uuid.uuid4().hex[:10]}",
        email=f"plain_{uuid.uuid4().hex[:10]}@example.com",
        is_active=True,
        status="active",
    )
    session.add(user)
    await session.commit()
    return user


class TestInheritedDerivation:
    async def test_inherited_set_is_the_intersection(
        self, test_db_session: AsyncSession
    ):
        """Only keywords present on BOTH records count as inherited."""
        admin_id = await get_user_id(test_db_session, "admin")
        _, _, _, derived_record = await _derived_pair(
            test_db_session,
            admin_id,
            source_keywords=("codename", "deleted-after-copy"),
            copy_keywords=False,
            own_keywords=("codename", "riverine"),
        )
        source = await resolve_inherited_source(test_db_session, derived_record)
        assert source is not None
        keys = await inherited_keyword_keys(test_db_session, derived_record, source)
        assert keys == {("codename", None, "theme")}

    async def test_record_without_derived_from_has_no_source(
        self, test_db_session: AsyncSession
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)
        record = await test_db_session.get(Record, ds.record_id)
        assert await resolve_inherited_source(test_db_session, record) is None

    async def test_deleted_source_dataset_yields_no_source(
        self, test_db_session: AsyncSession
    ):
        """A gone source leaves nothing to attribute inheritance to."""
        admin_id = await get_user_id(test_db_session, "admin")
        source, _, _, derived_record = await _derived_pair(test_db_session, admin_id)
        await test_db_session.delete(source)
        await test_db_session.commit()
        assert await resolve_inherited_source(test_db_session, derived_record) is None

    async def test_unparseable_source_id_yields_no_source(
        self, test_db_session: AsyncSession
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        _, _, _, derived_record = await _derived_pair(test_db_session, admin_id)
        derived_record.derived_from = {"dataset_id": "not-a-uuid"}
        await test_db_session.commit()
        assert await resolve_inherited_source(test_db_session, derived_record) is None


class TestDisclosureWarning:
    """The update_user_metadata chokepoint, keyed off resolved state."""

    async def test_warning_fires_on_visibility_widening(
        self, test_db_session: AsyncSession
    ):
        """Axis 1: internal -> public reaches anonymous; a private source does not."""
        admin_id = await get_user_id(test_db_session, "admin")
        _, derived, _, _ = await _derived_pair(
            test_db_session, admin_id, derived_visibility="internal"
        )
        warnings: list[str] = []
        await update_user_metadata(
            test_db_session,
            derived.id,
            DatasetMeta(visibility="public"),
            warnings_out=warnings,
        )
        await test_db_session.commit()
        assert len(warnings) == 1
        assert "codename" in warnings[0]

    async def test_warning_fires_on_publish(self, test_db_session: AsyncSession):
        """Axis 2: record_status internal -> published widens to all signed-in."""
        admin_id = await get_user_id(test_db_session, "admin")
        await _add_plain_user(test_db_session)
        _, derived, _, _ = await _derived_pair(
            test_db_session,
            admin_id,
            derived_visibility="internal",
            derived_status="internal",
        )
        warnings: list[str] = []
        await update_user_metadata(
            test_db_session,
            derived.id,
            DatasetMeta(record_status="published"),
            warnings_out=warnings,
        )
        await test_db_session.commit()
        assert len(warnings) == 1
        assert "codename" in warnings[0]

    async def test_no_warning_without_inherited_keywords(
        self, test_db_session: AsyncSession
    ):
        """The same widening move is silent when nothing was inherited."""
        admin_id = await get_user_id(test_db_session, "admin")
        _, derived, _, _ = await _derived_pair(
            test_db_session,
            admin_id,
            derived_visibility="internal",
            copy_keywords=False,
            own_keywords=("riverine",),
        )
        warnings: list[str] = []
        await update_user_metadata(
            test_db_session,
            derived.id,
            DatasetMeta(visibility="public"),
            warnings_out=warnings,
        )
        await test_db_session.commit()
        assert warnings == []

    async def test_no_warning_when_source_audience_covers(
        self, test_db_session: AsyncSession
    ):
        """A public+published source is readable by everyone the move admits."""
        admin_id = await get_user_id(test_db_session, "admin")
        _, derived, _, _ = await _derived_pair(
            test_db_session,
            admin_id,
            source_visibility="public",
            derived_visibility="internal",
        )
        warnings: list[str] = []
        await update_user_metadata(
            test_db_session,
            derived.id,
            DatasetMeta(visibility="public"),
            warnings_out=warnings,
        )
        await test_db_session.commit()
        assert warnings == []

    async def test_no_warning_on_non_audience_edit(self, test_db_session: AsyncSession):
        """A title edit never asks the audience question, gap or no gap."""
        admin_id = await get_user_id(test_db_session, "admin")
        _, derived, _, _ = await _derived_pair(
            test_db_session, admin_id, derived_visibility="internal"
        )
        warnings: list[str] = []
        await update_user_metadata(
            test_db_session,
            derived.id,
            DatasetMeta(title="Renamed, audience untouched"),
            warnings_out=warnings,
        )
        await test_db_session.commit()
        assert warnings == []

    async def test_disclosed_list_survives_a_deleted_source(
        self, test_db_session: AsyncSession
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        source, derived, _, derived_record = await _derived_pair(
            test_db_session, admin_id, derived_visibility="public"
        )
        await test_db_session.delete(source)
        await test_db_session.commit()
        assert (
            await disclosed_inherited_keywords(
                test_db_session, derived_record, derived.id
            )
            == []
        )


class TestKeywordsEndpointShape:
    async def test_inherited_flags_and_counterfactual_gap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        _, _, _, derived_record = await _derived_pair(
            test_db_session, admin_id, own_keywords=("riverine",)
        )

        resp = await client.get(
            f"/records/{derived_record.id}/keywords/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        flags = {k["keyword"]: k["inherited"] for k in body["keywords"]}
        assert flags == {"codename": True, "riverine": False}
        # Private derived, private source, same owner: the audiences coincide.
        assert body["inherited_audience_gap"] is False

        # The counterfactual an owner asks before widening: at public+published
        # the audience includes anonymous, which a private source never does.
        resp = await client.get(
            f"/records/{derived_record.id}/keywords/"
            "?audience_visibility=public&audience_record_status=published",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["inherited_audience_gap"] is True

    async def test_flags_redacted_without_source_access(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A requester who cannot open the source sees all-false flags —
        indistinguishable from a record that was never derived (#765's rule)."""
        admin_id = await get_user_id(test_db_session, "admin")
        _, _, _, derived_record = await _derived_pair(
            test_db_session, admin_id, derived_visibility="public"
        )

        resp = await client.get(
            f"/records/{derived_record.id}/keywords/", headers=viewer_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [k["inherited"] for k in body["keywords"]] == [False]
        assert body["inherited_audience_gap"] is False

        # The owner-side view of the SAME record does resolve the flags.
        resp = await client.get(
            f"/records/{derived_record.id}/keywords/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert [k["inherited"] for k in resp.json()["keywords"]] == [True]


class TestPatchWarningSurface:
    async def test_patch_response_carries_metadata_warnings(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        _, derived, _, _ = await _derived_pair(
            test_db_session, admin_id, derived_visibility="internal"
        )
        resp = await client.patch(
            f"/datasets/{derived.id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        warnings = resp.json()["metadata_warnings"]
        assert warnings and "codename" in warnings[0]

        # The move applied — the warning is advisory, not a refusal.
        resp = await client.patch(
            f"/datasets/{derived.id}",
            json={"title": "still public"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["metadata_warnings"] is None
