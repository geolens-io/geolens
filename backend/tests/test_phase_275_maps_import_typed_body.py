"""Phase 275 / API-01 regression: POST /maps/import accepts a typed body.

Closes M-05 (v13.12 medium finding): the request body parameter changed from
``style: dict = Body(...)`` to a typed ``MapStyleImportRequest`` Pydantic
model. The OpenAPI ``requestBody`` schema now references the named component
instead of an inline ``additionalProperties: true`` object, and out-of-range
field values are rejected by Pydantic (422) before reaching
``parse_maplibre_style_import`` (which still emits 400 for deeper / structural
errors).
"""

from __future__ import annotations

import json

from httpx import AsyncClient


def test_openapi_schema_no_additional_properties_true_on_maps_import() -> None:
    """The /maps/import requestBody must reference MapStyleImportRequest, not a bare dict."""
    with open("openapi.json") as f:
        spec = json.load(f)

    schema = spec["paths"]["/maps/import"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    # Either a $ref or an inline object — never a bare additionalProperties:true
    # at the request-body root.
    assert (
        "additionalProperties" not in schema
        or schema.get("additionalProperties") is not True
    ), (
        f"additionalProperties:true on /maps/import body — API-01 regression. Got: {schema}"
    )

    if "$ref" in schema:
        assert schema["$ref"].endswith("MapStyleImportRequest"), schema

    # The named model must exist in components.schemas with the 12 named fields.
    components = spec["components"]["schemas"]
    assert "MapStyleImportRequest" in components, "MapStyleImportRequest schema missing"
    fields = components["MapStyleImportRequest"].get("properties", {})
    expected = {
        "version",
        "name",
        "metadata",
        "center",
        "zoom",
        "bearing",
        "pitch",
        "sources",
        "sprite",
        "glyphs",
        "terrain",
        "layers",
    }
    assert expected.issubset(fields.keys()), (
        f"Missing fields: {expected - fields.keys()}"
    )


class TestMapsImportTypedBody:
    """Behavior regression for the typed-body change (API-01 / M-05)."""

    async def test_post_maps_import_accepts_valid_minimal_body(
        self, client: AsyncClient, editor_auth_header: dict
    ) -> None:
        """A minimal valid MapLibre style still imports successfully (behavior preserved)."""
        body = {
            "version": 8,
            "name": "API-01 Round-trip Test",
            "sources": {},
            "layers": [],
        }
        resp = await client.post(
            "/maps/import",
            json=body,
            headers=editor_auth_header,
        )
        assert resp.status_code == 201, resp.text
        payload = resp.json()
        assert payload["map"]["name"] == "API-01 Round-trip Test"
        assert payload["summary"]["layers_imported"] == 0

    async def test_post_maps_import_rejects_out_of_range_zoom_with_422(
        self, client: AsyncClient, editor_auth_header: dict
    ) -> None:
        """Pydantic field constraints fire BEFORE parse_maplibre_style_import — 422 not 400.

        GeoLens uses RFC 7807 problem-details for 422 responses, so ``detail``
        is a flattened string like ``"body.zoom: Input should be less than or
        equal to 24"`` (see backend/app/api/main.py exception handlers). We
        assert the field name appears in that string rather than parsing the
        FastAPI default array shape.
        """
        body = {"version": 8, "name": "bad", "zoom": 99.0, "sources": {}, "layers": []}
        resp = await client.post(
            "/maps/import",
            json=body,
            headers=editor_auth_header,
        )
        assert resp.status_code == 422, resp.text
        payload = resp.json()
        # RFC 7807 problem-details shape: {type, title, status, detail}
        assert payload.get("status") == 422, payload
        assert "zoom" in (payload.get("detail") or ""), payload

    async def test_post_maps_import_extra_allow_forward_compat(
        self, client: AsyncClient, editor_auth_header: dict
    ) -> None:
        """Unknown MapLibre top-level keys (e.g. projection) round-trip through extra=allow."""
        body = {
            "version": 8,
            "name": "API-01 Forward-compat",
            "sources": {},
            "layers": [],
            "projection": {
                "type": "mercator"
            },  # not yet a named field — must still accept
        }
        resp = await client.post(
            "/maps/import",
            json=body,
            headers=editor_auth_header,
        )
        assert resp.status_code == 201, resp.text
