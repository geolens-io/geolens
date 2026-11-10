"""normalize_nfc runs in before-validators, where the payload is untyped."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.text import normalize_nfc


class TestHelper:
    def test_composes_combining_characters(self) -> None:
        assert normalize_nfc("e\u0301") == "\u00e9"

    @pytest.mark.parametrize("value", [None, 123, 1.5, True, ["a"], {"a": 1}])
    def test_a_non_string_passes_through_for_the_field_to_reject(
        self, value: object
    ) -> None:
        assert normalize_nfc(value) is value  # type: ignore[arg-type]


@pytest.mark.anyio
class TestRoutes:
    async def test_collections_answer_422_for_a_numeric_name(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        resp = await client.post(
            "/catalog/collections/", json={"name": 123}, headers=admin_auth_header
        )
        assert resp.status_code == 422, resp.text

    async def test_maps_import_answers_422_for_a_numeric_name(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        resp = await client.post(
            "/maps/import/arcgis-webmap/",
            json={"webmap": {}, "name": 123},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text
        resp = await client.post(
            "/maps/import/arcgis-webmap/",
            json={"webmap": {}, "title": ["x"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text
