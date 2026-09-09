"""fix(#1963): a publication change retires a dataset's tile signatures.

A signature bound only ``scope`` and ``exp``, and neither carried the state
that granted it, so a template minted while a dataset was published and public
kept serving tiles after the owner unpublished it or made it private. The scope
now folds in ``publication_version``, which rolls on publication-status and
visibility transitions only, so the stateless verify path refuses the stale
signature and an ordinary edit leaves a live template alone.
"""

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import create_raster_dataset, get_user_id


async def _admin_id(session) -> uuid.UUID:
    return await get_user_id(session, "admin")


async def _make_raster(session, *, created_by: uuid.UUID, visibility: str = "public"):
    return await create_raster_dataset(
        session,
        created_by=created_by,
        name=f"Revocation Raster {uuid.uuid4().hex[:6]}",
        visibility=visibility,
        record_status="published",
        table_name=f"sig_revoke_raster_{uuid.uuid4().hex[:8]}",
        source_filename="test.tif",
        create_raster_asset=True,
    )


async def _make_vector(session, *, created_by: uuid.UUID, visibility: str = "public"):
    record = Record(
        title=f"Revocation Vector {uuid.uuid4().hex[:6]}",
        summary="Point dataset for the signature revocation tests",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"sig_revoke_vector_{uuid.uuid4().hex[:8]}",
        source_format="geojson",
        source_filename="test.geojson",
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)

    table = dataset.table_name
    await session.execute(
        text(
            f"CREATE TABLE data.{table} ("
            "  gid SERIAL PRIMARY KEY,"
            "  geom GEOMETRY(Point, 3857),"
            "  geom_4326 GEOMETRY(Point, 4326))"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table} (geom, geom_4326) VALUES ("
            "  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            "  ST_SetSRID(ST_MakePoint(0, 0), 4326))"
        )
    )
    await session.commit()
    return dataset


async def _drop_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


def _evict_tile_meta() -> None:
    """Drop the 60 s metadata snapshots so the next tile asks the database.

    The caches bound revocation, not the signature: without this a test would
    be asserting the cache TTL rather than the scope.
    """
    from app.processing.tiles import router as tile_router

    with tile_router._dataset_cache_lock:
        tile_router._dataset_cache.clear()
    with tile_router._raster_meta_cache_lock:
        tile_router._raster_meta_cache.clear()


async def _mint(client: AsyncClient, dataset_id, admin_auth_header: dict) -> dict:
    resp = await client.get(f"/tiles/token/{dataset_id}/", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    token = resp.json()
    return {"sig": token["sig"], "exp": token["exp"], "scope": token["scope"]}


async def _set_status(
    client: AsyncClient, dataset_id, admin_auth_header: dict, target: str
) -> None:
    resp = await client.patch(
        f"/datasets/{dataset_id}/status/",
        json={"status": target},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text


async def _patch_dataset(
    client: AsyncClient, dataset_id, admin_auth_header: dict, body: dict
) -> None:
    resp = await client.patch(
        f"/datasets/{dataset_id}", json=body, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestUnpublishRetiresOutstandingSignatures:
    async def test_raster_refuses_a_signature_minted_before_the_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        params = await _mint(client, dataset.id, admin_auth_header)
        await _set_status(client, dataset.id, admin_auth_header, "internal")
        _evict_tile_meta()

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id), **params},
        )

        assert resp.status_code == 404, resp.text

    async def test_vector_refuses_a_signature_minted_before_the_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            await _set_status(client, dataset.id, admin_auth_header, "internal")
            _evict_tile_meta()

            resp = await client.get(
                f"/tiles/data.{dataset.table_name}/0/0/0.pbf", params=params
            )

            assert resp.status_code == 404, resp.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_cluster_refuses_a_signature_minted_before_the_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            await _set_status(client, dataset.id, admin_auth_header, "internal")
            _evict_tile_meta()

            resp = await client.get(
                f"/tiles/clusters/data.{dataset.table_name}/0/0/0.pbf", params=params
            )

            assert resp.status_code == 404, resp.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_a_fresh_signature_still_works_after_the_unpublish(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The owner's own draft preview keeps working; only the stale one dies."""
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        try:
            await _set_status(client, dataset.id, admin_auth_header, "internal")
            params = await _mint(client, dataset.id, admin_auth_header)

            resp = await client.get(
                f"/tiles/data.{dataset.table_name}/0/0/0.pbf", params=params
            )

            assert resp.status_code == 200, resp.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_the_metadata_patch_route_retires_signatures_too(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PATCH /datasets/{id} writes record_status without the status route."""
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            await _patch_dataset(
                client, dataset.id, admin_auth_header, {"record_status": "internal"}
            )
            _evict_tile_meta()

            resp = await client.get(
                f"/tiles/data.{dataset.table_name}/0/0/0.pbf", params=params
            )

            assert resp.status_code == 404, resp.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_a_stale_v_param_does_not_resurrect_a_raster_signature(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """`v` picks the raster metadata cache key, never the version compared."""
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        token = (
            await client.get(f"/tiles/token/{dataset.id}/", headers=admin_auth_header)
        ).json()
        stale_v = parse_qs(urlsplit(token["tile_url"]).query)["v"][0]
        await _set_status(client, dataset.id, admin_auth_header, "internal")
        _evict_tile_meta()

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={
                "dataset_id": str(dataset.id),
                "sig": token["sig"],
                "exp": token["exp"],
                "scope": token["scope"],
                "v": stale_v,
            },
        )

        assert resp.status_code == 404, resp.text


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestGoingPrivateRetiresOutstandingSignatures:
    """The worse case: the token endpoint mints for anonymous callers on a
    public published dataset, so the surviving holder is a stranger."""

    async def test_raster_refuses_a_signature_minted_while_public(
        self, client: AsyncClient, test_db_session, admin_auth_header: dict
    ):
        dataset = await _make_raster(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        anon = await client.get(f"/tiles/token/{dataset.id}/")
        assert anon.status_code == 200, anon.text
        token = anon.json()
        await _patch_dataset(
            client, dataset.id, admin_auth_header, {"visibility": "private"}
        )
        _evict_tile_meta()

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={
                "dataset_id": str(dataset.id),
                "sig": token["sig"],
                "exp": token["exp"],
                "scope": token["scope"],
            },
        )

        assert resp.status_code == 401, resp.text

    @pytest.mark.parametrize("route", ["data", "clusters/data"])
    async def test_vector_routes_refuse_a_signature_minted_while_public(
        self, client: AsyncClient, test_db_session, admin_auth_header: dict, route: str
    ):
        dataset = await _make_vector(
            test_db_session, created_by=await _admin_id(test_db_session)
        )
        try:
            anon = await client.get(f"/tiles/token/{dataset.id}/")
            assert anon.status_code == 200, anon.text
            token = anon.json()
            await _patch_dataset(
                client, dataset.id, admin_auth_header, {"visibility": "private"}
            )
            _evict_tile_meta()

            resp = await client.get(
                f"/tiles/{route}.{dataset.table_name}/0/0/0.pbf",
                params={
                    "sig": token["sig"],
                    "exp": token["exp"],
                    "scope": token["scope"],
                },
            )

            assert resp.status_code == 403, resp.text
            assert "Scope mismatch" in resp.json()["detail"]
        finally:
            await _drop_table(test_db_session, dataset.table_name)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestAnOrdinaryEditKeepsSignaturesAlive:
    """The counter is deliberately not `tile_cache_version`.

    Binding to that one would retire every live template on every feature
    write, column change and reupload, and the client only recovers through a
    throttled reactive re-mint.
    """

    async def test_a_feature_delete_does_not_retire_a_signature(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            visibility="private",
        )
        try:
            # A second row, so the tile after the delete is still non-empty and
            # a surviving signature reads as 200 rather than the empty-tile 204.
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{dataset.table_name} (geom, geom_4326) VALUES ("
                    "  ST_Transform(ST_SetSRID(ST_MakePoint(1, 1), 4326), 3857),"
                    "  ST_SetSRID(ST_MakePoint(1, 1), 4326))"
                )
            )
            await test_db_session.commit()
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"
            before = await client.get(url, params=params)

            deleted = await client.delete(
                f"/datasets/{dataset.id}/features/1", headers=admin_auth_header
            )
            assert deleted.status_code == 204, deleted.text
            _evict_tile_meta()

            after = await client.get(url, params=params)

            assert before.status_code == 200, before.text
            assert after.status_code == 200, after.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_a_tile_columns_change_does_not_retire_a_signature(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            visibility="private",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            await _patch_dataset(
                client, dataset.id, admin_auth_header, {"tile_columns": []}
            )
            _evict_tile_meta()

            resp = await client.get(
                f"/tiles/data.{dataset.table_name}/0/0/0.pbf", params=params
            )

            assert resp.status_code == 200, resp.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestRepublishDoesNotResurrect:
    async def test_a_signature_from_before_the_unpublish_stays_dead(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A private dataset, so the signature is the only way in either way."""
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            visibility="private",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"

            await _set_status(client, dataset.id, admin_auth_header, "internal")
            await _set_status(client, dataset.id, admin_auth_header, "published")
            _evict_tile_meta()

            after = await client.get(url, params=params)
            reminted = await client.get(
                url, params=await _mint(client, dataset.id, admin_auth_header)
            )

            assert after.status_code == 403, after.text
            assert "Scope mismatch" in after.json()["detail"]
            assert reminted.status_code == 200, reminted.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    async def test_a_visibility_round_trip_does_not_resurrect_either(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Both endpoints stay non-public, so the signature is the only way in."""
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            visibility="private",
        )
        try:
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"

            await _patch_dataset(
                client, dataset.id, admin_auth_header, {"visibility": "restricted"}
            )
            await _patch_dataset(
                client, dataset.id, admin_auth_header, {"visibility": "private"}
            )
            _evict_tile_meta()

            after = await client.get(url, params=params)
            reminted = await client.get(
                url, params=await _mint(client, dataset.id, admin_auth_header)
            )

            assert after.status_code == 403, after.text
            assert "Scope mismatch" in after.json()["detail"]
            assert reminted.status_code == 200, reminted.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)


def _publication_state_writes(root) -> dict[str, list[str]]:
    """Every write to ``record_status`` or ``visibility`` under ``root``.

    Attribute assignment is one spelling of four. A guard that saw only that
    one would pass while ``setattr``, an ``update(...).values(...)`` and a
    mapping write each reopened #1963.
    """
    import ast

    names = {"record_status", "visibility"}
    sites: dict[str, list[str]] = {}

    def record(path, kind: str) -> None:
        sites.setdefault(str(path.relative_to(root)), []).append(kind)

    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            targets: list = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in names:
                    record(path, f"attr:{target.attr}")
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value in names
                ):
                    record(path, f"item:{target.slice.value}")
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if (
                called == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in names
            ):
                record(path, f"setattr:{node.args[1].value}")
            if called == "values":
                for keyword in node.keywords:
                    if keyword.arg in names:
                        record(path, f"values:{keyword.arg}")
    return {key: sorted(value) for key, value in sites.items()}


class TestEveryPublicationStateWriterIsAccountedFor:
    def test_the_scan_sees_every_writer_in_backend_app(self):
        """A new entry means: decide whether that write must roll the counter.

        ``tasks_common.py`` stamps an initial status on a dataset that does not
        exist yet, which no outstanding signature can name.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        assert _publication_state_writes(root) == {
            "modules/catalog/datasets/api/router_data.py": [
                "attr:record_status",
                "attr:record_status",
            ],
            "modules/catalog/datasets/domain/service_metadata.py": [
                "attr:record_status",
                "attr:record_status",
                "attr:visibility",
            ],
            "processing/ingest/tasks_common.py": ["attr:record_status"],
        }

    def test_the_scan_catches_the_indirect_spellings(self, tmp_path):
        """The negative control for the three shapes plain assignment hides."""
        (tmp_path / "sneaky.py").write_text(
            "def f(record, session, payload):\n"
            "    setattr(record, 'record_status', 'draft')\n"
            "    session.execute(update(Record).values(visibility='private'))\n"
            "    payload['record_status'] = 'draft'\n"
        )

        assert _publication_state_writes(tmp_path) == {
            "sneaky.py": [
                "item:record_status",
                "setattr:record_status",
                "values:visibility",
            ]
        }

    def test_every_live_transition_rolls_the_publication_version(self):
        """A writer that skips the roll reopens #1963 silently."""
        import pathlib

        backend = pathlib.Path(__file__).resolve().parents[1]
        router = (
            backend / "app/modules/catalog/datasets/api/router_data.py"
        ).read_text()
        metadata = (
            backend / "app/modules/catalog/datasets/domain/service_metadata.py"
        ).read_text()

        def block(source: str, start: str, end: str) -> str:
            first, last = source.find(start), source.find(end)
            assert first != -1 and last != -1, (start, end)
            return source[first:last]

        blocks = {
            "/status/": (
                block(
                    router,
                    "async def update_publication_status",
                    "async def set_target_status",
                ),
                "_roll_publication_version",
            ),
            "/target-status/": (
                router[router.find("async def set_target_status") :],
                "_roll_publication_version",
            ),
            "_apply_visibility_change": (
                block(
                    metadata,
                    "async def _apply_visibility_change",
                    "async def _apply_record_status_change",
                ),
                "bump_publication_version_on",
            ),
            "_apply_record_status_change": (
                block(
                    metadata,
                    "async def _apply_record_status_change",
                    "async def _apply_is_dem",
                ),
                "bump_publication_version_on",
            ),
        }
        for label, (source, call) in blocks.items():
            assert f"{call}(" in source, f"{label} no longer rolls publication_version"


class TestEveryScopeDerivationAgrees:
    def test_a_saved_map_style_signs_the_layer_at_its_publication_version(self):
        """The style document is the fourth minter and shares the derivation."""
        from urllib.parse import parse_qs, urlsplit

        from app.modules.catalog.maps.style_json import build_maplibre_style

        from tests.test_maps_style_json import _layer, _map

        layer = _layer().model_copy(update={"publication_version": 7})
        style = build_maplibre_style(_map(), [layer])

        tile_url = next(iter(style["sources"].values()))["tiles"][0]
        assert parse_qs(urlsplit(tile_url).query)["scope"] == ["public_stops:p7"]


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestASharedCacheIsNotACapabilityChannel:
    """Why the revocation boundary does not extend to a shared HTTP cache.

    A signed response is only ever marked publicly cacheable in the one state
    where the same URL, stripped of its signature, is served to anyone. So a
    shared cache can hold bytes that were world-readable when it stored them,
    and never bytes a capability unlocked (#1928's declared cache-scope rule).
    """

    @pytest.mark.parametrize(
        ("visibility", "record_status", "expected_scope", "anonymous_status"),
        [
            ("public", "published", "public", 200),
            ("public", "internal", "private", 404),
            ("private", "published", "private", 403),
        ],
    )
    async def test_public_cache_scope_implies_anonymous_readability(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        visibility: str,
        record_status: str,
        expected_scope: str,
        anonymous_status: int,
    ):
        dataset = await _make_vector(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            visibility=visibility,
        )
        try:
            if record_status != "published":
                await _set_status(client, dataset.id, admin_auth_header, record_status)
            params = await _mint(client, dataset.id, admin_auth_header)
            url = f"/tiles/data.{dataset.table_name}/0/0/0.pbf"

            signed = await client.get(url, params=params)
            unsigned = await client.get(url)

            assert signed.status_code == 200, signed.text
            assert signed.headers["cache-control"].startswith(expected_scope)
            assert unsigned.status_code == anonymous_status, unsigned.text
        finally:
            await _drop_table(test_db_session, dataset.table_name)

    @pytest.mark.parametrize(
        ("visibility", "record_status", "expected_scope", "anonymous_status"),
        [
            ("public", "published", "public", 200),
            ("public", "internal", "private", 404),
            ("private", "published", "private", 401),
        ],
    )
    async def test_raster_cache_status_implies_anonymous_readability(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        visibility: str,
        record_status: str,
        expected_scope: str,
        anonymous_status: int,
    ):
        """`X-GeoLens-Cache-Status` is what nginx's raster_cache keys off."""
        dataset = await _make_raster(
            test_db_session,
            created_by=await _admin_id(test_db_session),
            visibility=visibility,
        )
        if record_status != "published":
            await _set_status(client, dataset.id, admin_auth_header, record_status)
            _evict_tile_meta()
        params = await _mint(client, dataset.id, admin_auth_header)

        signed = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id), **params},
        )
        unsigned = await client.get(
            "/tiles/raster-auth-check/", params={"dataset_id": str(dataset.id)}
        )

        assert signed.status_code == 200, signed.text
        assert signed.headers["x-geolens-cache-status"] == expected_scope
        assert unsigned.status_code == anonymous_status, unsigned.text
