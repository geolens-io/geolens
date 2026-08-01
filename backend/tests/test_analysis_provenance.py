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

    def test_every_operation_names_its_second_layer(self):
        """fix(#1097 review): the four new operations had no branch, so they
        fell through to "<operation> applied to <source>".

        That sentence is a product surface — the dataset page renders it,
        search indexes it, and DCAT exports it — so an overlay whose entire
        point is the second layer was described without naming one.
        """
        cases = [
            (
                "spatial_join",
                {"join_dataset_id": "x", "join_fields": ["owner", "value"]},
                {"join_title": "Parcels Registry"},
                'Joined from "Points" against "Parcels Registry"',
            ),
            (
                "intersect",
                {"mask_dataset_id": "x"},
                {"mask_title": "Zones"},
                'Intersected from "Points" with "Zones"',
            ),
            (
                "select_by_location",
                {"mask_source": "layer", "mask_dataset_id": "x"},
                {"mask_title": "Zones"},
                'Selected from "Points" by "Zones"',
            ),
            (
                "select_by_location",
                {"mask_source": "drawn"},
                {},
                'Selected from "Points" by a drawn area',
            ),
            ("measure", {}, {}, 'Measurements computed from "Points"'),
        ]
        for operation, params, titles, expected in cases:
            sentence = build_lineage_sentence(
                operation=operation,
                source_title="Points",
                params=params,
                actor="admin",
                created_at=datetime(2026, 7, 31),
                **titles,
            )
            assert sentence == (f"{expected}, created by admin on 2026-07-31."), (
                f"{operation} with {params!r} rendered as {sentence!r}"
            )
            # The fallback is what these branches exist to avoid.
            assert "applied to" not in sentence, operation

    def test_the_sentence_never_names_a_private_layers_columns(self):
        """fix(#1097 review): lineage_summary has no per-requester form.

        It is stored once and served raw — the dataset page returns it, search
        indexes it, three DCAT services export it — and none of those pass it
        through visible_derived_from, which is what access-checks the
        structured provenance per requester.

        So anything the redaction treats as sensitive must not reach this
        prose. join_fields is a dependent of join_dataset_id in
        _DATASET_ID_PARAMS precisely because a column list is most of a
        schema, and the previous round routed it around that redaction while
        making the sentence more useful.
        """
        from app.modules.catalog.authorization import _DATASET_ID_PARAMS

        sentence = build_lineage_sentence(
            operation="spatial_join",
            source_title="Points",
            params={
                "join_dataset_id": "x",
                "join_fields": ["parcel_owner", "assessed_value"],
            },
            actor="admin",
            created_at=datetime(2026, 7, 31),
            join_title="Parcels Registry",
        )
        assert "parcel_owner" not in sentence
        assert "assessed_value" not in sentence
        # And the reason, stated where it can rot loudly: these are the keys
        # the redaction drops, so they are the keys prose may not carry.
        assert "join_fields" in _DATASET_ID_PARAMS["join_dataset_id"]

    def test_a_second_layer_whose_title_is_gone_still_reads_as_a_sentence(self):
        """A deleted or unreadable layer yields no title, and a bare UUID would
        not read. Same treatment clip already gave it, extended to the
        operations that now name a layer."""
        for operation, params in (
            ("spatial_join", {"join_dataset_id": "x"}),
            ("intersect", {"mask_dataset_id": "x"}),
            ("select_by_location", {"mask_source": "layer", "mask_dataset_id": "x"}),
        ):
            sentence = build_lineage_sentence(
                operation=operation,
                source_title="Points",
                params=params,
                actor="admin",
                created_at=datetime(2026, 7, 31),
            )
            assert "another layer" in sentence, operation
            assert "x" not in sentence.replace("Intersected", "").replace(
                "transferring", ""
            ), f"{operation} leaked an id into the sentence: {sentence!r}"


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

    async def test_a_private_join_layer_takes_its_column_names_with_it(
        self, test_db_session: AsyncSession
    ):
        """fix(#1097 review): the mask was not the last dataset id in params.

        Spatial join carries join_dataset_id, and the redaction covered only
        the mask — so a public join output derived through a PRIVATE join layer
        published that layer's id to every viewer.

        join_fields goes with it. Dropping the id alone would still publish the
        private layer's column names, which is most of what its schema is: an
        id you cannot resolve is a weaker disclosure than the list of fields
        someone chose to copy out of it.
        """
        from app.modules.catalog.authorization import visible_derived_from

        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        join = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        reference = {
            "dataset_id": str(source.id),
            "operation": "spatial_join",
            "params": {
                "join_dataset_id": str(join.id),
                "join_fields": ["parcel_owner", "assessed_value"],
            },
            "created_at": "2026-07-31T00:00:00+00:00",
        }

        anonymous = await visible_derived_from(test_db_session, reference, None, set())
        assert anonymous is not None
        assert "join_dataset_id" not in anonymous["params"]
        assert "join_fields" not in anonymous["params"]
        # The record's own JSONB is untouched — this redacts a copy per
        # requester, it does not destroy the provenance.
        assert reference["params"]["join_fields"] == ["parcel_owner", "assessed_value"]

    async def test_a_visible_join_layer_keeps_its_fields(
        self, test_db_session: AsyncSession
    ):
        """The guard on the redaction above: it must key off ACCESS, not off
        the param existing. An owner reading their own output still gets the
        lineage that makes it reproducible."""
        from app.modules.catalog.authorization import visible_derived_from

        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        join = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        reference = {
            "dataset_id": str(source.id),
            "operation": "spatial_join",
            "params": {
                "join_dataset_id": str(join.id),
                "join_fields": ["parcel_owner"],
            },
            "created_at": "2026-07-31T00:00:00+00:00",
        }

        visible = await visible_derived_from(test_db_session, reference, None, set())
        assert visible is not None
        assert visible["params"]["join_dataset_id"] == str(join.id)
        assert visible["params"]["join_fields"] == ["parcel_owner"]

    async def test_a_spatial_join_records_the_layer_and_fields_it_used(
        self, test_db_session: AsyncSession
    ):
        """fix(#1097 review): end to end, through the real worker.

        The unit-level whitelist check above says the key is allowed through.
        This says it actually arrives, because the two are separable: the
        params reach apply_analysis_provenance and are then filtered, so a
        whitelist assertion alone would have passed throughout the window when
        nothing was being stored.
        """
        from tests.test_analysis_spatial_join import (
            _create_probe_points,
            _create_two_overlapping_polygons,
        )

        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(points.id),
            user_id=str(admin_id),
            operation="spatial_join",
            title=f"Joined {uuid.uuid4().hex[:6]}",
            join_dataset_id=str(polys.id),
            join_fields=["name", "pop"],
        )
        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        out = await test_db_session.get(Dataset, job.dataset_id)
        record = await _record_of(test_db_session, out)
        assert record.derived_from is not None
        params = record.derived_from["params"]
        # The layer it joined against, and the columns it copied. Without both,
        # the lineage cannot explain where the join_* columns came from.
        assert params["join_dataset_id"] == str(polys.id)
        assert params["join_fields"] == ["name", "pop"]

    async def test_a_drawn_selection_still_records_that_it_was_drawn(
        self, test_db_session: AsyncSession
    ):
        """fix(#1097 review): mask_source was recorded for clip alone.

        The drawn geometry itself is deliberately kept out of provenance — it
        can be kilobytes — so this discriminator is the ONLY trace that an area
        shaped the selection. Without it a drawn select_by_location serialised
        empty params: a lineage saying a selection happened by no visible
        means.
        """
        from tests.test_analysis_preview import _create_polygon_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(source.id),
            user_id=str(admin_id),
            operation="select_by_location",
            title=f"Selected {uuid.uuid4().hex[:6]}",
            mask={
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
            },
        )
        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        out = await test_db_session.get(Dataset, job.dataset_id)
        record = await _record_of(test_db_session, out)
        assert record.derived_from["params"]["mask_source"] == "drawn"

    def test_both_writers_of_mask_source_agree_on_which_operations_have_one(self):
        """The two writers of this fact must not drift.

        The router records it on the job (Admin Jobs reads that to diagnose a
        run) and the worker records it in provenance (the durable lineage).
        They are separate constants because processing/ cannot import from
        app.modules.catalog (PROCESS-02), and separate constants are how the
        previous round's fix landed in one writer and not the other.

        Pinned rather than deduplicated, since the import boundary is the
        reason the duplication exists.
        """
        from app.modules.catalog.datasets.domain.schemas import MASK_OPERATIONS
        from app.processing.analysis.tasks import _DRAWN_MASK_OPERATIONS

        assert set(_DRAWN_MASK_OPERATIONS) == set(MASK_OPERATIONS), (
            "the job metadata and the durable provenance disagree about which "
            "operations can take a drawn mask, so one of them is recording a "
            "discriminator the other omits"
        )

    def test_every_dataset_id_param_is_redactable(self):
        """Structural: everything STORED that names a dataset must be
        access-checked per requester.

        fix(#1097 review): this reads PARAM_KEYS now, not the params dict at
        the _materialize call site. The first version parsed the call site and
        was checking the wrong layer — join_dataset_id was passed there and
        then dropped by build_derived_from's PARAM_KEYS filter, so it never
        reached records.derived_from at all. The test passed, and it was
        confirming a pairing between two things that had no bearing on what
        was stored.

        PARAM_KEYS is the storage contract, so it is the one that matters: a
        key added there becomes visible to every requester who can see the
        output. This is also why the redaction and the whitelist have to move
        together — adding join_dataset_id to PARAM_KEYS without the matching
        _DATASET_ID_PARAMS row is precisely how a private join layer's id would
        reach an unauthorised reader.

        The failure mode is silence: an unredacted id looks like ordinary
        provenance and nothing errors.
        """
        from app.modules.catalog.authorization import _DATASET_ID_PARAMS
        from app.processing.analysis.provenance import PARAM_KEYS

        stored_ids = {k for k in PARAM_KEYS if k.endswith("_dataset_id")}
        assert stored_ids, (
            "no *_dataset_id keys in PARAM_KEYS — either the naming convention "
            "changed or this test has stopped checking anything"
        )
        missing = stored_ids - set(_DATASET_ID_PARAMS)
        assert not missing, (
            f"{sorted(missing)} are stored in records.derived_from but are not "
            "in _DATASET_ID_PARAMS, so they are published to requesters who "
            "cannot access the dataset they name. Add a row (and list any "
            "param that DESCRIBES that dataset as a dependent, the way "
            "join_fields hangs off join_dataset_id)."
        )


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
