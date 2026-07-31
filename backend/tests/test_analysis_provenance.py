"""Provenance written onto materialized analysis outputs (feat(#765)).

A materialized result used to land with an empty lineage, no keywords, and no
durable link to the dataset it came from. These tests pin the three products of
that fix end to end: ``records.lineage_summary``, ``records.derived_from``, and
inherited ``record_keywords`` child rows.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordKeyword
from app.processing.analysis.provenance import build_lineage_sentence
from app.processing.analysis.tasks import _materialize
from app.standards.stac.serializer import _build_stac_links

from tests.factories import get_user_id
from tests.test_analysis_materialize import _create_job
from tests.test_analysis_preview import _create_polygon_dataset

pytestmark = pytest.mark.anyio


async def _add_keyword(
    session: AsyncSession,
    record_id: uuid.UUID,
    keyword: str,
    keyword_type: str = "place",
) -> None:
    session.add(
        RecordKeyword(record_id=record_id, keyword=keyword, keyword_type=keyword_type)
    )
    await session.commit()


async def _buffer_to_dataset(
    session: AsyncSession,
    source: Dataset,
    user_id: uuid.UUID,
    *,
    title: str | None = None,
    distance_meters: float = 100,
) -> Dataset:
    """Run the real worker path and return the registered output dataset."""
    job = await _create_job(session, user_id)
    await _materialize(
        job_id=str(job.id),
        dataset_id=str(source.id),
        user_id=str(user_id),
        operation="buffer",
        title=title or f"Buffered {uuid.uuid4().hex[:6]}",
        distance_meters=distance_meters,
    )
    await session.refresh(job)
    assert job.status == "complete", job.error_message
    out = await session.get(Dataset, job.dataset_id)
    assert out is not None
    return out


async def _record_of(session: AsyncSession, dataset: Dataset) -> Record:
    record = await session.get(Record, dataset.record_id)
    assert record is not None
    await session.refresh(record)
    return record


class TestMaterializedProvenance:
    async def test_output_carries_lineage_and_derived_from(
        self, test_db_session: AsyncSession
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        source_record = await _record_of(test_db_session, source)
        source_record.title = f"Reservoirs {uuid.uuid4().hex[:6]}"
        await test_db_session.commit()

        out = await _buffer_to_dataset(test_db_session, source, admin_id)
        record = await _record_of(test_db_session, out)

        assert record.derived_from is not None
        assert record.derived_from["dataset_id"] == str(source.id)
        assert record.derived_from["operation"] == "buffer"
        assert record.derived_from["params"]["distance_meters"] == 100
        assert record.derived_from["created_at"]

        # The sentence names the operation, the source, the parameter and the
        # actor -- the four things that make it readable without the JSON.
        assert record.lineage_summary is not None
        assert record.lineage_summary.startswith("Buffered from")
        assert source_record.title in record.lineage_summary
        assert "100 m" in record.lineage_summary
        assert "admin" in record.lineage_summary

    async def test_keywords_inherit_as_child_rows_with_their_type(
        self, test_db_session: AsyncSession
    ):
        """Keywords are ``record_keywords`` rows, not ``theme_category`` values.

        ``Record.keywords`` is a relationship with a ``keyword_type`` CHECK
        constraint; ``theme_category`` is the array column sitting next to it.
        Writing the inherited values into the array would look like it worked.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        term = f"hydrology-{uuid.uuid4().hex[:6]}"
        await _add_keyword(test_db_session, source.record_id, term, "place")

        out = await _buffer_to_dataset(test_db_session, source, admin_id)
        record = await _record_of(test_db_session, out)

        rows = (
            (
                await test_db_session.execute(
                    select(RecordKeyword).where(RecordKeyword.record_id == record.id)
                )
            )
            .scalars()
            .all()
        )
        assert [(r.keyword, r.keyword_type) for r in rows] == [(term, "place")]
        assert term not in (record.theme_category or [])

    async def test_keywords_inherit_from_a_restricted_source(
        self, test_db_session: AsyncSession
    ):
        """Deliberate: the creator already has read access (Rule 1 gates the
        analysis) and the output is registered private, so an inherited keyword
        goes no further unless its owner publishes it. Recorded as a test so it
        is not "fixed" later; apply_analysis_provenance carries the argument.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="restricted"
        )
        term = f"restricted-{uuid.uuid4().hex[:6]}"
        await _add_keyword(test_db_session, source.record_id, term, "theme")

        out = await _buffer_to_dataset(test_db_session, source, admin_id)
        inherited = (
            (
                await test_db_session.execute(
                    select(RecordKeyword.keyword).where(
                        RecordKeyword.record_id == out.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert inherited == [term]

    async def test_output_no_longer_fails_the_lineage_validation_gate(
        self, test_db_session: AsyncSession
    ):
        """VAL-01 treats an empty ``lineage_summary`` as an error, so every
        materialized output used to fail that check on creation.
        """
        from app.modules.catalog.validation.service import validate_record

        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        out = await _buffer_to_dataset(test_db_session, source, admin_id)
        record = await _record_of(test_db_session, out)

        result = await validate_record(test_db_session, record, out)
        fields = [issue.field for issue in result.errors]
        assert "lineage_summary" not in fields

    async def test_search_finds_the_output_by_a_lineage_only_term(
        self,
        client: AsyncClient,
        test_db_session: AsyncSession,
        admin_auth_header: dict,
    ):
        """Populating lineage changes search results, which is the point: the
        source title now reaches the derived dataset's search vector.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        term = f"zoquil{uuid.uuid4().hex[:6]}"
        source_record = await _record_of(test_db_session, source)
        source_record.title = term
        await test_db_session.commit()

        out = await _buffer_to_dataset(
            test_db_session, source, admin_id, title=f"Output {uuid.uuid4().hex[:6]}"
        )

        resp = await client.get(
            "/search/datasets/", params={"q": term}, headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        ids = {feature["id"] for feature in resp.json()["features"]}
        assert str(out.id) in ids

    def test_the_buffer_distance_survives_the_sentence(self):
        """fix(#765 review): the lineage sentence must record the distance the
        geometry was actually built with.

        `:g` defaults to SIX significant digits, so it rounded silently. These
        are the measured cases: an ordinary 8-digit distance, a repeating
        decimal, and a value just under MAX_BUFFER_METERS that rounded UP past
        the ceiling it was checked against.
        """
        for distance, expected in (
            (500.0, "500 m"),
            (1609.34, "1609.34 m"),
            (12345.678, "12345.678 m"),
            (33.333333333, "33.333333333 m"),
            (99999.99, "99999.99 m"),
            (100000.0, "100000 m"),
        ):
            sentence = build_lineage_sentence(
                operation="buffer",
                source_title="Parcels",
                params={"distance_meters": distance},
                actor="admin",
                created_at=datetime(2026, 7, 31),
            )
            assert expected in sentence, f"{distance!r} rendered as {sentence!r}"

    async def test_clip_lineage_names_the_mask_layer(
        self, test_db_session: AsyncSession
    ):
        """The generator is the extension point for new operations; clip is the
        case that reads a second dataset's title rather than a scalar."""
        sentence = build_lineage_sentence(
            operation="clip",
            source_title="Parcels",
            params={"mask_source": "layer", "mask_dataset_id": str(uuid.uuid4())},
            actor="admin",
            created_at=datetime(2026, 7, 31),
            mask_title="Flood Zone",
        )
        assert sentence == (
            'Clipped from "Parcels" to "Flood Zone", created by admin on 2026-07-31.'
        )


class TestDerivedFromVisibility:
    async def test_detail_omits_derived_from_without_access_to_the_source(
        self,
        client: AsyncClient,
        test_db_session: AsyncSession,
        admin_auth_header: dict,
        viewer_auth_header: dict,
    ):
        """The output can be shared while its source stays private. The
        reference is omitted for a requester who cannot open the source, so a
        private dataset's id never leaks through a derived one.

        The inherited KEYWORD is the deliberate exception, asserted below so
        the decision is pinned rather than described. A keyword is a copied
        value its owner can delete before publishing, not a reference the
        requester could act on; see apply_analysis_provenance.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        term = f"codename-{uuid.uuid4().hex[:6]}"
        await _add_keyword(test_db_session, source.record_id, term, "theme")
        out = await _buffer_to_dataset(test_db_session, source, admin_id)

        # Publish the OUTPUT only.
        out_record = await _record_of(test_db_session, out)
        out_record.visibility = "public"
        out_record.record_status = "published"
        await test_db_session.commit()

        owner = await client.get(f"/datasets/{out.id}", headers=admin_auth_header)
        assert owner.status_code == 200, owner.text
        assert owner.json()["derived_from"]["dataset_id"] == str(source.id)

        other = await client.get(f"/datasets/{out.id}", headers=viewer_auth_header)
        assert other.status_code == 200, other.text
        assert other.json()["derived_from"] is None

        # The keyword endpoint gates the source itself...
        denied = await client.get(
            f"/records/{source.record_id}/keywords/", headers=viewer_auth_header
        )
        assert denied.status_code == 404

        # ...and yet the COPY on the published output is visible to that same
        # viewer. Intended, not an oversight: the output was registered
        # private and its owner published it.
        keywords = await client.get(
            f"/records/{out.record_id}/keywords/", headers=viewer_auth_header
        )
        assert keywords.status_code == 200, keywords.text
        assert [k["keyword"] for k in keywords.json()["keywords"]] == [term]


class TestDerivedFromParamsVisibility:
    async def test_a_private_mask_id_is_dropped_from_visible_params(
        self, test_db_session: AsyncSession
    ):
        """fix(#765 review): a clip carries a SECOND dataset id in its params.

        Source public, mask private: a requester who passes the source check
        would otherwise be handed the private mask's UUID, and with it the
        fact that it exists.
        """
        from app.modules.catalog.authorization import visible_derived_from

        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        mask = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        reference = {
            "dataset_id": str(source.id),
            "operation": "clip",
            "params": {"mask_source": "layer", "mask_dataset_id": str(mask.id)},
            "created_at": "2026-07-31T00:00:00+00:00",
        }

        anonymous = await visible_derived_from(test_db_session, reference, None, set())
        assert anonymous is not None
        assert anonymous["dataset_id"] == str(source.id)
        assert "mask_dataset_id" not in anonymous["params"]
        # The rest of the reference survives; only the id it may not see goes.
        assert anonymous["params"]["mask_source"] == "layer"
        # ...and the record's own JSONB is untouched by the redaction.
        assert reference["params"]["mask_dataset_id"] == str(mask.id)

    async def test_a_visible_mask_id_is_kept(self, test_db_session: AsyncSession):
        from app.modules.catalog.authorization import visible_derived_from

        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        mask = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        reference = {
            "dataset_id": str(source.id),
            "operation": "clip",
            "params": {"mask_source": "layer", "mask_dataset_id": str(mask.id)},
            "created_at": "2026-07-31T00:00:00+00:00",
        }

        visible = await visible_derived_from(test_db_session, reference, None, set())
        assert visible is not None
        assert visible["params"]["mask_dataset_id"] == str(mask.id)


class TestStacDerivedFromLink:
    """The STAC half.

    STAC Items are served for the raster family only
    (``_STAC_RECORD_TYPES``), so a vector analysis output never appears there
    today; these cover the link itself and the gate that decides whether a
    requester sees it.
    """

    def test_link_is_emitted_when_a_source_id_is_supplied(self):
        links = _build_stac_links(
            "item-1", "coll-1", "https://example.test/api/stac", "source-1"
        )
        derived = [link for link in links if link["rel"] == "derived_from"]
        assert derived == [
            {
                "rel": "derived_from",
                "href": "https://example.test/api/stac/items/source-1",
                "type": "application/geo+json",
            }
        ]

    def test_no_link_without_a_source_id(self):
        links = _build_stac_links("item-1", "coll-1", "https://example.test/api/stac")
        assert not [link for link in links if link["rel"] == "derived_from"]

    async def test_gate_hides_a_source_the_requester_cannot_fetch(
        self, test_db_session: AsyncSession
    ):
        """The gate runs the same query the item endpoints serve from, so the
        link can never point at an item the requester would get a 404 for.
        """
        from app.modules.auth.models import User
        from app.standards.stac.router import _visible_derived_from_id

        admin_id = await get_user_id(test_db_session, "admin")
        source = Record(
            title="Private raster source",
            visibility="private",
            record_status="published",
            record_type="raster_dataset",
            created_by=admin_id,
        )
        test_db_session.add(source)
        await test_db_session.flush()
        source_ds = Dataset(
            record_id=source.id,
            table_name=f"ds_{uuid.uuid4().hex[:12]}",
            srid=4326,
        )
        test_db_session.add(source_ds)
        await test_db_session.commit()

        derived = Record(
            title="Derived raster",
            visibility="public",
            record_status="published",
            record_type="raster_dataset",
            created_by=admin_id,
            derived_from={"dataset_id": str(source_ds.id), "operation": "buffer"},
        )
        test_db_session.add(derived)
        await test_db_session.commit()

        admin = await test_db_session.get(User, admin_id)
        assert (
            await _visible_derived_from_id(test_db_session, derived, admin, {"admin"})
        ) == str(source_ds.id)
        # Anonymous cannot open a private source, so the reference disappears
        # rather than dangling.
        assert (
            await _visible_derived_from_id(test_db_session, derived, None, set())
        ) is None

    async def test_gate_ignores_a_record_with_no_provenance(
        self, test_db_session: AsyncSession
    ):
        from app.standards.stac.router import _visible_derived_from_id

        record = Record(title="Plain", visibility="public", record_status="published")
        assert (
            await _visible_derived_from_id(test_db_session, record, None, set())
        ) is None
