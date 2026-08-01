"""Select by location: keep the source features that hit a mask (#955).

One test per acceptance criterion on the issue.

The fixture that carries most of them is an L-shaped mask. Its envelope is a
3x3 square but its geometry covers only the bottom bar and the left bar, so a
feature parked in the notch overlaps the envelope and misses the geometry.
That is the exact shape a bbox-only filter gets wrong, and it is why this
operation could not simply reuse ``render_clip_layer_join``'s WHERE.

    3 +---+
      | L |          notch = x(1,3] y(1,3]
    1 |   +-------+  a feature here passes && and fails ST_Intersects
      |           |
    0 +-----------+
      0     1     3

Requirements:
  - Docker database must be running (docker compose up db)
"""

import json
import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.service_analysis import PREVIEW_FEATURE_CAP
from app.platform.analysis_sql import MAX_SOURCE_FEATURES
from app.processing.analysis.tasks import _materialize

from tests.factories import get_user_id
from tests.test_analysis_materialize import _create_job
from tests.test_analysis_spatial_join import _create_layer

# The L, as WKT and as GeoJSON. Both mask paths must agree on the same shape,
# so they are written once here rather than per test.
L_WKT = "POLYGON((0 0, 3 0, 3 1, 1 1, 1 3, 0 3, 0 0))"
L_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [3, 0], [3, 1], [1, 1], [1, 3], [0, 3], [0, 0]]],
}

# A polygon straddling the mask's right edge: x 2->4 against a bar ending at
# x=3. Clip would return the x 2->3 half; a selection must return all of it.
STRADDLER_WKT = "POLYGON((2 0.5, 4 0.5, 4 0.8, 2 0.8, 2 0.5))"


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


def _materialize_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/materialize/"


async def _create_mask_layer(
    session: AsyncSession, *, created_by: uuid.UUID, visibility: str = "public"
):
    """A one-row mask layer holding the L."""
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Geometry",
        geometry_type="POLYGON",
        visibility=visibility,
        values_sql=(
            f"('L', ST_GeomFromText('{L_WKT}', 4326), ST_GeomFromText('{L_WKT}', 4326))"
        ),
    )


async def _create_probe_features(
    session: AsyncSession, *, created_by: uuid.UUID, visibility: str = "public"
):
    """Four source rows covering every branch of the predicate.

    gid 1 hits the mask, gid 2 sits in the notch (the bbox trap), gid 3 is
    outside the envelope entirely, gid 4 has no geometry at all.
    """
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Geometry",
        geometry_type="POINT",
        visibility=visibility,
        feature_count=4,
        values_sql=(
            "('inside', ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326),"
            " ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326)),"
            "('in_notch', ST_SetSRID(ST_MakePoint(2, 2), 4326),"
            " ST_SetSRID(ST_MakePoint(2, 2), 4326)),"
            "('far_away', ST_SetSRID(ST_MakePoint(10, 10), 4326),"
            " ST_SetSRID(ST_MakePoint(10, 10), 4326)),"
            "('nullgeom', NULL, NULL)"
        ),
    )


def _selected_gids(payload: dict) -> list:
    return [f["properties"]["gid"] for f in payload["geojson"]["features"]]


class TestSelectionIsExact:
    async def test_a_feature_in_the_notch_is_not_selected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 2, the headline: envelope overlap is not selection.

        gid 2 sits at (2,2), inside the mask's 3x3 bounding box and outside
        the L itself. Clip's ``EXISTS (... WHERE geom_4326 && _src.geom_4326)``
        admits it; only the real ST_Intersects term rejects it.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        src = await _create_probe_features(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert _selected_gids(resp.json()) == [1]

        # Prove the fixture actually exercises the trap rather than passing
        # because nothing overlapped: the bbox-only predicate takes gid 2 too.
        bbox_only = (
            (
                await test_db_session.execute(
                    text(
                        f"SELECT s.gid FROM data.{src.table_name} AS s "  # noqa: S608
                        f"WHERE EXISTS (SELECT 1 FROM data.{mask.table_name} AS m "
                        f"WHERE m.geom_4326 && s.geom_4326) ORDER BY s.gid"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert list(bbox_only) == [1, 2], "fixture no longer exercises the bbox trap"

    async def test_a_drawn_mask_selects_the_same_features(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The inline-mask path is exact too, and agrees with the layer path.

        The two render different SQL (a WHERE against a literal geometry vs an
        EXISTS against a table), so "same shape, same answer" is a property
        worth asserting rather than assuming.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_probe_features(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask": L_GEOJSON},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert _selected_gids(resp.json()) == [1]

    async def test_an_invalid_source_geometry_still_answers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Neither predicate repairs its operands, so this pins the assumption
        that lets them skip it: ST_Intersects accepts invalid geometry and
        agrees with the repaired answer.

        A bowtie is self-intersecting and therefore invalid. ST_Intersection
        raises on it (which is why clip repairs first); ST_Intersects does not.
        If that ever stops holding, this test fails rather than the operation
        silently dropping rows.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        bowtie = "POLYGON((0.2 0.2, 0.8 0.8, 0.8 0.2, 0.2 0.8, 0.2 0.2))"
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                f"('bowtie', ST_GeomFromText('{bowtie}', 4326),"
                f" ST_GeomFromText('{bowtie}', 4326))"
            ),
        )
        assert not (
            await test_db_session.execute(
                text(
                    f"SELECT ST_IsValid(geom_4326) FROM data.{src.table_name}"  # noqa: S608
                )
            )
        ).scalar_one(), "fixture must actually be invalid"

        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert _selected_gids(resp.json()) == [1]

    async def test_a_non_polygonal_mask_row_does_not_select(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The ST_Dimension term, and the reason it exists.

        _load_mask_dataset rejects a non-polygonal mask DATASET, but the
        catalog classifies geometry_type from the FIRST feature (fix(#682)), so
        a POLYGON-typed layer can still hold a line row. Clip drops those in
        _mask_pieces; without the dimension term a selection would honour them,
        and clipping and selecting against one layer would disagree.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",  # classified from row 1, which IS a polygon
            feature_count=2,
            values_sql=(
                f"('L', ST_GeomFromText('{L_WKT}', 4326),"
                f" ST_GeomFromText('{L_WKT}', 4326)),"
                "('stray_line',"
                " ST_GeomFromText('LINESTRING(1.5 1.5, 2.5 2.5)', 4326),"
                " ST_GeomFromText('LINESTRING(1.5 1.5, 2.5 2.5)', 4326))"
            ),
        )
        src = await _create_probe_features(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        # gid 2 sits at (2,2), ON the stray line. It stays unselected.
        assert _selected_gids(resp.json()) == [1]


class TestGeometriesSurviveWhole:
    async def test_the_selected_geometry_equals_the_source_geometry(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 3, and the line between this operation and clip.

        The straddler pokes out past the mask's right edge. A clip returns the
        overlap; a selection returns the feature.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                f"('straddler', ST_GeomFromText('{STRADDLER_WKT}', 4326),"
                f" ST_GeomFromText('{STRADDLER_WKT}', 4326))"
            ),
        )

        selected = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert selected.status_code == 200, selected.text
        features = selected.json()["geojson"]["features"]
        assert len(features) == 1

        equals_source = (
            await test_db_session.execute(
                text(
                    "SELECT ST_Equals(geom_4326, "  # noqa: S608
                    "ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) "
                    f"FROM data.{src.table_name} WHERE gid = 1"
                ).bindparams(g=json.dumps(features[0]["geometry"]))
            )
        ).scalar_one()
        assert equals_source, "selection must not modify the geometry"

        # And the contrast: a clip of the same pair does change it.
        clipped = await client.post(
            _preview_url(src.id),
            json={"operation": "clip", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert clipped.status_code == 200, clipped.text
        assert (
            clipped.json()["geojson"]["features"][0]["geometry"]
            != features[0]["geometry"]
        ), "fixture must straddle the mask edge for this contrast to mean anything"


class TestNullGeometries:
    async def test_null_rows_in_either_layer_neither_crash_nor_select(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 6. The source fixture already carries a NULL row (gid 4);
        this adds one on the mask side too.

        Neither predicate carries an explicit IS NOT NULL guard: `&&` yields
        NULL against a NULL operand and PostgreSQL's three-valued logic drops
        the row. Asserted rather than argued, because a redundant-looking guard
        is exactly the kind of thing a later edit removes.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            feature_count=2,
            values_sql=(
                f"('L', ST_GeomFromText('{L_WKT}', 4326),"
                f" ST_GeomFromText('{L_WKT}', 4326)),"
                "('nullgeom', NULL, NULL)"
            ),
        )
        src = await _create_probe_features(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert _selected_gids(resp.json()) == [1]
        assert resp.json()["feature_count"] == 1
        # The count runs its own statement, so it needs its own proof that the
        # NULL rows did not reach it.
        assert resp.json()["match_count"] == 1


class TestSelectedCount:
    async def test_the_count_is_exact_beyond_the_preview_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 5: the deliverable is the record list, so its SIZE cannot
        be a capped number.

        The preview truncates at PREVIEW_FEATURE_CAP; match_count comes from a
        second, uncapped statement built from the same WHERE.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        total = PREVIEW_FEATURE_CAP + 25
        # Points spread along y inside the mask's left bar (x=0.5, y 0->3),
        # plus one in the notch that must not be counted.
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POINT",
            feature_count=total + 1,
            values_sql=(
                "('notch', ST_SetSRID(ST_MakePoint(2, 2), 4326),"
                " ST_SetSRID(ST_MakePoint(2, 2), 4326))"
            ),
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{src.table_name} (name, geom, geom_4326) "  # noqa: S608
                "SELECT 'p' || i,"
                " ST_SetSRID(ST_MakePoint(0.5, i * 0.005), 4326),"
                " ST_SetSRID(ST_MakePoint(0.5, i * 0.005), 4326)"
                " FROM generate_series(1, :n) AS i"
            ).bindparams(n=total)
        )
        await test_db_session.commit()

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["truncated"] is True
        assert body["feature_count"] == PREVIEW_FEATURE_CAP
        assert body["match_count"] == total, "the notch point must not be counted"
        # A row-filtering operation cannot report a source total (clip's rule).
        assert body["source_feature_count"] is None

    async def test_the_count_matches_the_feature_list_under_the_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The count statement is rendered separately from the preview, so this
        pins the two to the same answer on the same inputs — including the
        NULL-geometry row, which neither may count."""
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        src = await _create_probe_features(test_db_session, created_by=admin_id)

        for body in (
            {"operation": "select_by_location", "mask_dataset_id": str(mask.id)},
            {"operation": "select_by_location", "mask": L_GEOJSON},
        ):
            resp = await client.post(
                _preview_url(src.id), json=body, headers=admin_auth_header
            )
            assert resp.status_code == 200, resp.text
            payload = resp.json()
            assert payload["match_count"] == payload["feature_count"] == 1


class TestAccessControl:
    async def test_a_mask_layer_the_caller_cannot_see_is_a_404(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 4: Rule 1 applies to BOTH datasets. Read on the source and
        not on the mask is a 404, on preview and materialize alike."""
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_probe_features(test_db_session, created_by=admin_id)
        private_mask = await _create_mask_layer(
            test_db_session, created_by=admin_id, visibility="private"
        )

        for url in (_preview_url(src.id), _materialize_url(src.id)):
            resp = await client.post(
                url,
                json={
                    "operation": "select_by_location",
                    "mask_dataset_id": str(private_mask.id),
                    "title": "Nope",
                },
                headers=editor_auth_header,
            )
            assert resp.status_code == 404, f"{url}: {resp.text}"

    async def test_a_private_source_is_a_404_even_with_a_visible_mask(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The other direction of the same rule."""
        admin_id = await get_user_id(test_db_session, "admin")
        private_src = await _create_probe_features(
            test_db_session, created_by=admin_id, visibility="private"
        )
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(private_src.id),
            json={
                "operation": "select_by_location",
                "mask_dataset_id": str(mask.id),
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 404, resp.text


class TestEnqueueValidation:
    async def test_oversized_source_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 7. The router reads MAX_SOURCE_FEATURES with .get(), so a
        missing key leaves the operation with NO ceiling rather than a default
        one — the entry existing is half the assertion."""
        assert "select_by_location" in MAX_SOURCE_FEATURES
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        src = await _create_probe_features(test_db_session, created_by=admin_id)
        src.feature_count = MAX_SOURCE_FEATURES["select_by_location"] + 1
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(src.id),
            json={
                "operation": "select_by_location",
                "mask_dataset_id": str(mask.id),
                "title": "Too big",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large" in resp.text

    async def test_exactly_one_mask_source_is_required(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Neither mask nor both: the same rule clip carries, now shared."""
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        src = await _create_probe_features(test_db_session, created_by=admin_id)

        neither = await client.post(
            _preview_url(src.id),
            json={"operation": "select_by_location"},
            headers=admin_auth_header,
        )
        assert neither.status_code == 422, neither.text

        both = await client.post(
            _preview_url(src.id),
            json={
                "operation": "select_by_location",
                "mask": L_GEOJSON,
                "mask_dataset_id": str(mask.id),
            },
            headers=admin_auth_header,
        )
        assert both.status_code == 422, both.text

    async def test_mask_params_are_still_dropped_for_other_operations(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """_ANALYSIS_PARAM_OWNERS values became tuples to let two operations
        share the mask pair. A stray mask_dataset_id on a centroid must still
        be dropped rather than resolved — a private id here would 404 if the
        widening had accidentally made the params global."""
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_probe_features(test_db_session, created_by=admin_id)
        private_mask = await _create_mask_layer(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.post(
            _preview_url(src.id),
            json={
                "operation": "centroid",
                "mask_dataset_id": str(private_mask.id),
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text


class TestMaterialize:
    async def test_the_saved_dataset_carries_whole_geometries_and_columns(
        self,
        test_db_session: AsyncSession,
    ):
        """The worker uses the same renderer as the preview, so the saved
        dataset is the approved selection rather than a second answer."""
        admin_id = await get_user_id(test_db_session, "admin")
        mask = await _create_mask_layer(test_db_session, created_by=admin_id)
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            feature_count=3,
            values_sql=(
                f"('straddler', ST_GeomFromText('{STRADDLER_WKT}', 4326),"
                f" ST_GeomFromText('{STRADDLER_WKT}', 4326)),"
                "('notch',"
                " ST_GeomFromText('POLYGON((2 2, 2.5 2, 2.5 2.5, 2 2.5, 2 2))', 4326),"
                " ST_GeomFromText('POLYGON((2 2, 2.5 2, 2.5 2.5, 2 2.5, 2 2))',"
                " 4326)),"
                "('nullgeom', NULL, NULL)"
            ),
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(src.id),
            user_id=str(admin_id),
            operation="select_by_location",
            title=f"Selected {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        out = await test_db_session.get(Dataset, job.dataset_id)
        assert out is not None
        assert out.feature_count == 1

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT o.gid, o.name,"  # noqa: S608
                    f" ST_Equals(o.geom_4326, s.geom_4326)"
                    f" FROM data.{out.table_name} AS o"
                    f" JOIN data.{src.table_name} AS s ON s.gid = o.gid"
                )
            )
        ).all()
        assert len(rows) == 1
        gid, name, same_geom = rows[0]
        assert (gid, name) == (1, "straddler")
        assert same_geom, "materialize must not clip the selected geometry"

    async def test_a_drawn_mask_materializes_through_the_generic_branch(
        self,
        test_db_session: AsyncSession,
    ):
        """The inline path adds no branch to _build_materialize_select; it
        rides render_geometry_expr's identity expression and _wrap_not_empty.
        Worth its own test precisely because nothing in the worker names it."""
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_probe_features(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(src.id),
            user_id=str(admin_id),
            operation="select_by_location",
            title=f"Drawn {uuid.uuid4().hex[:6]}",
            mask=L_GEOJSON,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        out = await test_db_session.get(Dataset, job.dataset_id)
        assert out is not None
        assert out.feature_count == 1
        names = (
            (
                await test_db_session.execute(
                    text(f"SELECT name FROM data.{out.table_name}")  # noqa: S608
                )
            )
            .scalars()
            .all()
        )
        assert list(names) == ["inside"]
