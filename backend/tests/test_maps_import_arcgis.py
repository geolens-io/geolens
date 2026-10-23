"""POST /maps/import/arcgis-webmap: access to matched datasets, creation and dry runs."""

from __future__ import annotations

import time
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import _create_test_user
from tests.factories import create_dataset

URL = "/maps/import/arcgis-webmap/"


def _webmap(*layer_ids: str, title: str = "Layer") -> dict:
    return {
        "baseMap": {"baseMapLayers": [{"url": "https://esri/base"}]},
        "operationalLayers": [
            {
                "id": layer_id,
                "layerType": "ArcGISFeatureLayer",
                "title": f"{title} {layer_id}",
                "url": f"https://x/arcgis/rest/services/S/FeatureServer/{index}",
                "layerDefinition": {
                    "drawingInfo": {
                        "renderer": {
                            "type": "simple",
                            "symbol": {
                                "type": "esriSFS",
                                "style": "esriSFSSolid",
                                "color": [255, 0, 0, 255],
                                "outline": {"color": [0, 0, 0, 255], "width": 1},
                            },
                        }
                    }
                },
            }
            for index, layer_id in enumerate(layer_ids)
        ],
    }


def _body(webmap: dict, matches: dict | None = None, **extra) -> dict:
    return {
        "webmap": webmap,
        "title": f"Imported {uuid.uuid4().hex[:6]}",
        "dataset_matches": {k: str(v) for k, v in (matches or {}).items()},
        **extra,
    }


async def _owned_maps(client: AsyncClient, headers: dict) -> list[dict]:
    resp = await client.get("/maps/?owned_only=true", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["maps"]


@pytest.fixture
async def editor(client: AsyncClient, admin_auth_header: dict):
    headers, user_id = await _create_test_user(client, admin_auth_header, "editor")
    return headers, uuid.UUID(user_id)


class TestCreate:
    async def test_creates_a_map_with_layers_and_notes(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(
            test_db_session, created_by=editor_id, visibility="private"
        )
        webmap = _webmap("a", "b")

        resp = await client.post(
            URL, json=_body(webmap, {"a": ds.id}, name="Parcels"), headers=headers
        )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        created = data["map"]
        assert created["name"] == "Parcels"
        assert created["visibility"] == "private"
        assert [layer["dataset_id"] for layer in created["layers"]] == [str(ds.id)]
        assert created["layers"][0]["paint"]["fill-color"] == "#ff0000"
        assert data["layer_ids"] == {"a": created["layers"][0]["id"]}
        assert [u["layer_id"] for u in data["unmatched_layers"]] == ["b"]
        assert data["loss_report"]["summary"]["unmatched_layer"] == 1
        assert created["basemap_style"] == "openfreemap-positron"
        first_line = created["notes"].splitlines()[0]
        assert first_line.startswith("ArcGIS migration notes (")
        assert "unmatched_layer" in created["notes"]

        got = await client.get(f"/maps/{created['id']}", headers=headers)
        assert got.status_code == 200
        assert len(got.json()["layers"]) == 1

    async def test_no_slash_path_is_served(self, client: AsyncClient, editor) -> None:
        headers, _ = editor
        resp = await client.post(
            "/maps/import/arcgis-webmap", json=_body(_webmap()), headers=headers
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["map"]["layers"] == []

    async def test_a_webmap_with_only_unsupported_layers_makes_an_empty_map(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        webmap = {
            "operationalLayers": [
                {"id": "t", "layerType": "ArcGISTiledMapServiceLayer", "title": "Tiles"}
            ]
        }
        resp = await client.post(URL, json=_body(webmap), headers=headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["map"]["layers"] == []
        assert data["loss_report"]["summary"]["unsupported_layer_type"] == 1

    async def test_long_reports_are_cut_at_the_notes_limit(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        webmap = _webmap(*[f"id{i}" for i in range(300)], title="T" * 240)
        resp = await client.post(URL, json=_body(webmap), headers=headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        notes = data["map"]["notes"]
        assert len(notes) <= 50_000
        assert notes.splitlines()[-1].endswith("more entries in the CLI report")
        assert len(data["loss_report"]["items"]) > 300

    async def test_a_name_is_required_from_somewhere_else_defaults(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        resp = await client.post(
            URL, json={"webmap": _webmap(), "dataset_matches": {}}, headers=headers
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["map"]["name"] == "Imported ArcGIS web map"


class TestDryRun:
    async def test_returns_the_translation_without_creating_a_map(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(test_db_session, created_by=editor_id)
        before = await _owned_maps(client, headers)

        resp = await client.post(
            URL, json=_body(_webmap("a"), {"a": ds.id}, dry_run=True), headers=headers
        )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["map"] is None
        assert data["layer_ids"] == {}
        assert data["layers"][0]["dataset_id"] == str(ds.id)
        assert await _owned_maps(client, headers) == before


class TestCategoryTyping:
    async def test_a_dataset_column_types_categories_the_web_map_does_not_declare(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(
            test_db_session,
            created_by=editor_id,
            column_info=[{"name": "CODE", "type": "integer"}],
        )
        webmap = _webmap("a")
        webmap["operationalLayers"][0]["layerDefinition"]["drawingInfo"]["renderer"] = {
            "type": "uniqueValue",
            "field1": "CODE",
            "uniqueValueInfos": [
                {
                    "value": "1",
                    "symbol": {"type": "esriSFS", "color": [255, 0, 0, 255]},
                },
                {
                    "value": "2",
                    "symbol": {"type": "esriSFS", "color": [0, 0, 255, 255]},
                },
            ],
        }

        resp = await client.post(URL, json=_body(webmap, {"a": ds.id}), headers=headers)

        assert resp.status_code == 201, resp.text
        layer = resp.json()["map"]["layers"][0]
        assert [c["value"] for c in layer["style_config"]["categories"]] == [1, 2]


class TestDatasetAccess:
    """A caller must never get a map that references a dataset they can't read."""

    async def test_another_users_private_dataset_is_refused_and_no_map_is_made(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        headers, _ = editor
        _, owner_id = await _create_test_user(client, admin_auth_header, "editor")
        private = await create_dataset(
            test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
        )
        before = await _owned_maps(client, headers)

        resp = await client.post(
            URL, json=_body(_webmap("a"), {"a": private.id}), headers=headers
        )

        assert resp.status_code == 404, resp.text
        assert str(private.id) not in resp.text
        assert await _owned_maps(client, headers) == before

    async def test_a_dataset_that_does_not_exist_answers_the_same_404(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        headers, _ = editor
        _, owner_id = await _create_test_user(client, admin_auth_header, "editor")
        private = await create_dataset(
            test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
        )
        missing = await client.post(
            URL, json=_body(_webmap("a"), {"a": uuid.uuid4()}), headers=headers
        )
        forbidden = await client.post(
            URL, json=_body(_webmap("a"), {"a": private.id}), headers=headers
        )
        assert missing.status_code == forbidden.status_code == 404
        assert missing.json() == forbidden.json()

    async def test_one_inaccessible_dataset_refuses_the_whole_request(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        _, owner_id = await _create_test_user(client, admin_auth_header, "editor")
        mine = await create_dataset(test_db_session, created_by=editor_id)
        private = await create_dataset(
            test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
        )
        resp = await client.post(
            URL,
            json=_body(_webmap("a", "b"), {"a": mine.id, "b": private.id}),
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    async def test_a_dry_run_does_not_confirm_a_private_dataset_exists(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        headers, _ = editor
        _, owner_id = await _create_test_user(client, admin_auth_header, "editor")
        private = await create_dataset(
            test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
        )
        resp = await client.post(
            URL,
            json=_body(_webmap("a"), {"a": private.id}, dry_run=True),
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    async def test_a_match_for_a_layer_not_in_the_web_map_is_still_checked(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        headers, _ = editor
        _, owner_id = await _create_test_user(client, admin_auth_header, "editor")
        private = await create_dataset(
            test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
        )
        resp = await client.post(
            URL, json=_body(_webmap("a"), {"zzz": private.id}), headers=headers
        )
        assert resp.status_code == 404, resp.text

    async def test_an_admin_can_attach_any_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        _, editor_id = editor
        private = await create_dataset(
            test_db_session, created_by=editor_id, visibility="private"
        )
        resp = await client.post(
            URL,
            json=_body(_webmap("a"), {"a": private.id}),
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        assert len(resp.json()["map"]["layers"]) == 1


class TestRequestRules:
    async def test_an_oversized_web_map_is_a_422(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        webmap = {"operationalLayers": [], "padding": "x" * 1_100_000}
        resp = await client.post(URL, json=_body(webmap), headers=headers)
        assert resp.status_code == 422, resp.text

    async def test_unknown_request_fields_are_refused(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        resp = await client.post(
            URL,
            json={**_body(_webmap()), "owner_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_a_viewer_cannot_import(
        self, client: AsyncClient, viewer_auth_header: dict
    ) -> None:
        resp = await client.post(URL, json=_body(_webmap()), headers=viewer_auth_header)
        assert resp.status_code == 403

    async def test_sign_in_is_required(self, client: AsyncClient) -> None:
        resp = await client.post(URL, json=_body(_webmap()))
        assert resp.status_code == 401


class TestVisibility:
    async def test_public_is_refused_for_an_editor_when_restricted(
        self, client: AsyncClient, editor, monkeypatch
    ) -> None:
        import app.core.persistent_config as pc

        class _On:
            async def get(self, _db):
                return True

        monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _On())
        headers, _ = editor
        before = await _owned_maps(client, headers)
        resp = await client.post(
            URL, json=_body(_webmap(), visibility="public"), headers=headers
        )
        assert resp.status_code == 403, resp.text
        assert await _owned_maps(client, headers) == before

    async def test_a_public_map_cannot_hold_a_private_dataset_and_nothing_is_kept(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        _, editor_id = editor
        private = await create_dataset(
            test_db_session, created_by=editor_id, visibility="private"
        )
        before = await _owned_maps(client, admin_auth_header)
        resp = await client.post(
            URL,
            json=_body(_webmap("a"), {"a": private.id}, visibility="public"),
            headers=admin_auth_header,
        )
        assert resp.status_code == 400, resp.text
        assert await _owned_maps(client, admin_auth_header) == before


class TestLayerIdMapping:
    async def test_maps_each_imported_layer_to_its_map_layer_and_skips_the_rest(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        first = await create_dataset(test_db_session, created_by=editor_id)
        second = await create_dataset(test_db_session, created_by=editor_id)
        webmap = _webmap("a", "b", "c")
        resp = await client.post(
            URL,
            json=_body(webmap, {"c": second.id, "a": first.id}),
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        by_dataset = {
            layer["dataset_id"]: layer["id"] for layer in data["map"]["layers"]
        }
        assert data["layer_ids"] == {
            "a": by_dataset[str(first.id)],
            "c": by_dataset[str(second.id)],
        }
        assert "b" not in data["layer_ids"]


class TestBounds:
    async def test_too_many_operational_layers_is_a_422(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        started = time.monotonic()
        resp = await client.post(
            URL,
            json=_body({"operationalLayers": [{}] * 320_000}, dry_run=True),
            headers=headers,
        )
        assert resp.status_code == 422, resp.text[:200]
        assert "operational layers" in resp.text
        assert time.monotonic() - started < 10

    async def test_group_members_count_toward_the_layer_limit(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        group = {"layerType": "GroupLayer", "layers": [{}] * 2500}
        resp = await client.post(
            URL,
            json=_body({"operationalLayers": [group]}, dry_run=True),
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_a_renderer_with_hundreds_of_thousands_of_classes_is_bounded(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(test_db_session, created_by=editor_id)
        webmap = _webmap("a")
        webmap["operationalLayers"][0]["layerDefinition"]["drawingInfo"]["renderer"] = {
            "type": "uniqueValue",
            "field1": "f",
            "uniqueValueInfos": [0] * 480_000,
        }
        started = time.monotonic()
        resp = await client.post(
            URL, json=_body(webmap, {"a": ds.id}, dry_run=True), headers=headers
        )
        assert resp.status_code == 201, resp.text[:200]
        assert time.monotonic() - started < 10
        assert len(resp.content) < 1_000_000
        report = resp.json()["loss_report"]
        assert len(report["items"]) <= 1001


class TestFilterAndIds:
    @pytest.mark.parametrize("dry_run", [True, False])
    async def test_a_non_finite_number_drops_the_filter_with_a_loss(
        self, client: AsyncClient, test_db_session, editor, dry_run: bool
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(test_db_session, created_by=editor_id)
        webmap = _webmap("a")
        webmap["operationalLayers"][0]["layerDefinition"]["definitionExpression"] = (
            "POP > 1e400"
        )
        resp = await client.post(
            URL, json=_body(webmap, {"a": ds.id}, dry_run=dry_run), headers=headers
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["layers"][0]["filter"] is None
        assert data["loss_report"]["summary"]["definition_expression"] == 1

    async def test_a_repeated_layer_id_imports_once_and_is_reported(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(test_db_session, created_by=editor_id)
        webmap = _webmap("a", "a")
        resp = await client.post(URL, json=_body(webmap, {"a": ds.id}), headers=headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert len(data["map"]["layers"]) == 1
        assert data["layer_ids"] == {"a": data["map"]["layers"][0]["id"]}
        assert data["loss_report"]["summary"]["duplicate_layer_id"] == 1


class TestResponseShape:
    async def test_layer_ids_stay_paired_when_the_response_drops_a_row(
        self, client: AsyncClient, test_db_session, editor, monkeypatch
    ) -> None:
        from app.modules.catalog.maps import _router_helpers

        headers, editor_id = editor
        first = await create_dataset(test_db_session, created_by=editor_id)
        second = await create_dataset(test_db_session, created_by=editor_id)
        real = _router_helpers.filter_layer_rows_by_dataset_visibility

        async def drop_first(db, rows, user):
            return (await real(db, rows, user))[1:]

        monkeypatch.setattr(
            _router_helpers, "filter_layer_rows_by_dataset_visibility", drop_first
        )
        resp = await client.post(
            URL,
            json=_body(_webmap("a", "b"), {"a": first.id, "b": second.id}),
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert [x["dataset_id"] for x in data["map"]["layers"]] == [str(second.id)]
        assert data["layer_ids"] == {"b": data["map"]["layers"][0]["id"]}

    async def test_a_dry_run_gets_the_same_400_for_a_public_map_with_a_private_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        _, editor_id = editor
        private = await create_dataset(
            test_db_session, created_by=editor_id, visibility="private"
        )
        body = _body(_webmap("a"), {"a": private.id}, visibility="public")
        real = await client.post(URL, json=body, headers=admin_auth_header)
        dry = await client.post(
            URL, json={**body, "dry_run": True}, headers=admin_auth_header
        )
        assert real.status_code == dry.status_code == 400
        assert real.json() == dry.json()


class TestPublicRefusalBody:
    async def test_dry_run_and_import_name_several_datasets_the_same_way(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, editor
    ) -> None:
        _, editor_id = editor
        zed = await create_dataset(
            test_db_session, created_by=editor_id, visibility="private", name="Zed"
        )
        abe = await create_dataset(
            test_db_session, created_by=editor_id, visibility="private", name="Abe"
        )
        body = _body(_webmap("a", "b"), {"a": zed.id, "b": abe.id}, visibility="public")
        real = await client.post(URL, json=body, headers=admin_auth_header)
        dry = await client.post(
            URL, json={**body, "dry_run": True}, headers=admin_auth_header
        )
        assert real.status_code == dry.status_code == 400
        assert real.json() == dry.json()
        assert real.json()["detail"]["datasets"] == "Abe, Zed"


class TestHugeNumbers:
    async def test_a_huge_group_opacity_is_not_a_500(
        self, client: AsyncClient, test_db_session, editor
    ) -> None:
        headers, editor_id = editor
        ds = await create_dataset(test_db_session, created_by=editor_id)
        webmap = _webmap("a")
        webmap["operationalLayers"] = [
            {
                "id": "g",
                "layerType": "GroupLayer",
                "title": "G",
                "opacity": 10**400,
                "layers": webmap["operationalLayers"],
            }
        ]
        resp = await client.post(URL, json=_body(webmap, {"a": ds.id}), headers=headers)
        assert resp.status_code == 201, resp.text
        assert len(resp.json()["map"]["layers"]) == 1


class TestViewpoint:
    async def test_rotation_is_stored_as_the_bearing(
        self, client: AsyncClient, editor
    ) -> None:
        headers, _ = editor
        webmap = {
            "initialState": {
                "viewpoint": {
                    "rotation": 90,
                    "targetGeometry": {
                        "xmin": -8300000,
                        "ymin": 4900000,
                        "xmax": -8200000,
                        "ymax": 5000000,
                        "spatialReference": {"wkid": 102100},
                    },
                }
            }
        }
        resp = await client.post(URL, json=_body(webmap), headers=headers)
        assert resp.status_code == 201, resp.text
        assert resp.json()["map"]["bearing"] == -90
