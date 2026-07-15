"""Regression coverage for the generated API contract."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap

from fastapi.routing import APIRoute

from app.api.main import app


def _openapi() -> dict:
    app.openapi_schema = None
    return app.openapi()


def _literal_http_statuses(node: ast.AST) -> set[int]:
    """Resolve literal FastAPI status expressions used by route handlers."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return {node.value}
    if isinstance(node, ast.Attribute):
        match = re.match(r"HTTP_(\d{3})_", node.attr)
        return {int(match.group(1))} if match else set()
    if isinstance(node, ast.IfExp):
        return _literal_http_statuses(node.body) | _literal_http_statuses(node.orelse)
    return set()


def _direct_http_exception_statuses(endpoint) -> set[int]:
    source = textwrap.dedent(inspect.getsource(endpoint))
    tree = ast.parse(source)
    statuses: set[int] = set()
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        function_name = (
            call.func.id
            if isinstance(call.func, ast.Name)
            else call.func.attr
            if isinstance(call.func, ast.Attribute)
            else None
        )
        if function_name != "HTTPException":
            continue
        status_node = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "status_code"
            ),
            call.args[0] if call.args else None,
        )
        if status_node is not None:
            statuses.update(_literal_http_statuses(status_node))
    return statuses


def test_problem_details_use_runtime_media_type_and_schema() -> None:
    spec = _openapi()
    response = spec["paths"]["/maps/"]["get"]["responses"]["400"]

    assert response["content"] == {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
        }
    }


def test_problem_detail_accepts_structured_runtime_details() -> None:
    spec = _openapi()
    detail_schema = spec["components"]["schemas"]["ProblemDetail"]["properties"][
        "detail"
    ]

    assert {item.get("type") for item in detail_schema["anyOf"]} == {
        "string",
        "object",
        "array",
    }


def test_openapi_documents_all_runtime_authentication_forms() -> None:
    spec = _openapi()

    schemes = spec["components"]["securitySchemes"]
    assert schemes["ApiKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
        "description": "GeoLens API key. Preferred API-key transport.",
    }
    assert schemes["ApiKeyQuery"]["name"] == "api_key"

    protected = spec["paths"]["/admin/users/"]["get"]["security"]
    assert {} not in protected
    assert protected == [
        {"OAuth2PasswordBearer": []},
        {"ApiKeyHeader": []},
        {"ApiKeyQuery": []},
    ]


def test_openapi_marks_optional_identity_as_anonymous_capable() -> None:
    spec = _openapi()
    expected = [
        {},
        {"OAuth2PasswordBearer": []},
        {"ApiKeyHeader": []},
        {"ApiKeyQuery": []},
    ]

    assert spec["paths"]["/search/datasets/"]["get"]["security"] == expected

    # Public STAC operations resolve credentials at runtime but intentionally
    # use the schema-free optional dependency so generated clients stay public.
    stac_collection = spec["paths"]["/stac/collections/{collection_id}"]["get"]
    assert "security" not in stac_collection


def test_rate_limited_operations_document_problem_429() -> None:
    spec = _openapi()
    response = spec["paths"]["/auth/login"]["post"]["responses"]["429"]

    assert response["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetail"
    }
    assert response["headers"]["Retry-After"]["schema"]["type"] == "integer"
    # The shared limiter has a global default, so undecorated routes also expose
    # 429. Exempt vector routes document their own semaphore/pool-busy 429,
    # while an exempt raster proxy with no equivalent failure remains outside.
    assert "429" in spec["paths"]["/auth/config/"]["get"]["responses"]
    vector = spec["paths"]["/tiles/{table_path}/{z}/{x}/{y}.pbf"]["get"]
    clusters = spec["paths"]["/tiles/clusters/{table_path}/{z}/{x}/{y}.pbf"]["get"]
    assert "429" in vector["responses"]
    assert "429" in clusters["responses"]
    raster_proxy = spec["paths"]["/tiles/raster-proxy/{dataset_id}/{z}/{x}/{y}.{fmt}"][
        "get"
    ]
    assert "429" not in raster_proxy["responses"]


def test_global_exception_contracts_cover_reachable_operations() -> None:
    spec = _openapi()

    db_backed = spec["paths"]["/admin/users/"]["get"]["responses"]
    assert db_backed["503"]["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetail"
    }

    health = spec["paths"]["/health"]["get"]["responses"]
    assert "500" in health
    assert health["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }


def test_non_streaming_ai_operations_document_upstream_failures() -> None:
    spec = _openapi()

    for path in (
        "/ai/generate-map/",
        "/ai/chat/",
        "/ai/metadata/summary/",
        "/ai/metadata/keywords/",
        "/ai/metadata/lineage/",
        "/ai/metadata/quality-statement/",
    ):
        response = spec["paths"][path]["post"]["responses"]["502"]
        assert response["content"]["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/ProblemDetail"
        }


def test_upload_quota_and_upstream_failures_are_route_scoped() -> None:
    spec = _openapi()

    quota_routes = (
        "/ingest/upload",
        "/ingest/upload/presigned",
        "/ingest/upload/presigned/{job_id}/complete",
        "/datasets/{dataset_id}/reupload",
        "/datasets/{dataset_id}/reupload/presigned",
        "/datasets/{dataset_id}/reupload/presigned/{job_id}/complete",
    )
    for path in quota_routes:
        assert "413" in spec["paths"][path]["post"]["responses"]

    upstream_routes = (
        "/ingest/upload/presigned",
        "/ingest/upload/presigned/{job_id}/complete",
        "/datasets/{dataset_id}/reupload/service/preview",
        "/datasets/{dataset_id}/reupload/presigned",
        "/datasets/{dataset_id}/reupload/presigned/{job_id}/complete",
        "/services/stac/collections",
        "/services/stac/search",
    )
    for path in upstream_routes:
        assert "502" in spec["paths"][path]["post"]["responses"]

    for path, method in (
        ("/ingest/upload/config", "get"),
        ("/ingest/upload", "post"),
        ("/services/stac/connect", "post"),
        ("/services/stac/import", "post"),
    ):
        assert "502" not in spec["paths"][path][method]["responses"]


def test_frontend_settings_dependencies_are_in_openapi() -> None:
    spec = _openapi()

    edition = spec["paths"]["/settings/edition/"]["get"]
    assert "security" not in edition
    assert set(edition["responses"]) == {"200", "429", "500"}

    for path in (
        "/settings/feature-flags/",
        "/settings/branding/",
        "/settings/basemaps/",
        "/settings/map-defaults/",
        "/settings/enabled-plugins/",
        "/settings/tile-config/",
    ):
        operation = spec["paths"][path]["get"]
        assert "security" not in operation
        assert set(operation["responses"]) == {"200", "429", "500", "503"}

    enterprise_tabs = spec["paths"]["/settings/enterprise-tabs/"]["get"]
    assert {} not in enterprise_tabs["security"]
    assert {next(iter(item)) for item in enterprise_tabs["security"]} == {
        "OAuth2PasswordBearer",
        "ApiKeyHeader",
        "ApiKeyQuery",
    }


def test_stac_item_operations_publish_typed_geojson_responses() -> None:
    spec = _openapi()
    expected = {
        ("/stac/collections/{collection_id}/items", "get"): (
            "StacItemCollectionResponse"
        ),
        ("/stac/collections/{collection_id}/items/{item_id}", "get"): (
            "StacItemResponse"
        ),
        ("/stac/items/{item_id}", "get"): "StacItemResponse",
        ("/stac/search", "get"): "StacItemCollectionResponse",
        ("/stac/search", "post"): "StacItemCollectionResponse",
    }

    for (path, method), schema_name in expected.items():
        content = spec["paths"][path][method]["responses"]["200"]["content"]
        assert content == {
            "application/geo+json": {
                "schema": {"$ref": f"#/components/schemas/{schema_name}"}
            }
        }

    collections = spec["components"]["schemas"]["StacCollectionListResponse"]
    assert collections["properties"]["collections"]["items"] == {
        "$ref": "#/components/schemas/StacCollection"
    }

    bbox_options = spec["components"]["schemas"]["StacItemResponse"]["properties"][
        "bbox"
    ]["anyOf"]
    assert {
        (option.get("minItems"), option.get("maxItems"))
        for option in bbox_options
        if option.get("type") == "array"
    } == {(4, 4), (6, 6)}


def test_sse_contract_describes_frames_and_decoded_event_payloads() -> None:
    spec = _openapi()

    expected_models = {
        "/ai/generate-map/stream/": {
            "SSEToolStartEvent",
            "SSEToolResultEvent",
            "SSEMapDoneEvent",
            "SSEErrorEvent",
        },
        "/ai/chat/stream/": {
            "SSETokenEvent",
            "SSEToolStartEvent",
            "SSEToolResultEvent",
            "SSEActionsEvent",
            "SSEChatDoneEvent",
            "SSEErrorEvent",
        },
    }

    for path, model_names in expected_models.items():
        content = spec["paths"][path]["post"]["responses"]["200"]["content"]
        assert set(content) == {"text/event-stream"}
        media = content["text/event-stream"]
        assert media["schema"]["type"] == "string"
        assert media["example"].startswith("event:")
        assert "discriminator" not in media["x-geolens-event-schema"]
        assert {
            ref["$ref"].rsplit("/", 1)[-1]
            for ref in media["x-geolens-event-schema"]["oneOf"]
        } == model_names
        assert model_names <= set(spec["components"]["schemas"])


def test_critical_contract_schemas_include_examples() -> None:
    spec = _openapi()
    schemas = spec["components"]["schemas"]

    for schema_name in (
        "ProblemDetail",
        "StatusUpdate",
        "StatusUpdateResponse",
        "DatasetMeta",
        "StacItemResponse",
        "StacItemCollectionResponse",
        "StacSearchBody",
    ):
        assert schemas[schema_name]["examples"], schema_name

    # Keep the established generated-SDK component name while new backend call
    # sites use the compatibility alias ``DatasetMetaUpdate``.
    assert "DatasetMetaUpdate" not in schemas


def test_internal_pagination_prefers_skip_with_deprecated_offset_alias() -> None:
    spec = _openapi()

    for path in (
        "/audit/datasets/{dataset_id}/column-ddl",
        "/datasets/{dataset_id}/vrt/generations/",
    ):
        parameters = {
            item["name"]: item for item in spec["paths"][path]["get"]["parameters"]
        }
        assert parameters["skip"]["schema"]["minimum"] == 0
        assert parameters["offset"]["deprecated"] is True
        assert parameters["offset"]["schema"]["anyOf"][0]["minimum"] == 0


def test_direct_route_http_exceptions_are_documented() -> None:
    """Prevent direct handler raises from drifting beyond OpenAPI responses."""
    spec = _openapi()
    missing: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        raised = _direct_http_exception_statuses(route.endpoint)
        if not raised:
            continue
        for method in route.methods or ():
            operation = spec["paths"][route.path_format].get(method.lower())
            if operation is None:
                continue
            documented = {
                int(code) for code in operation["responses"] if code.isdigit()
            }
            for status_code in sorted(raised - documented):
                missing.append(f"{method} {route.path_format}: {status_code}")

    assert missing == []


def test_openapi_has_no_dangling_local_ref_pointers() -> None:
    """Every $ref in the exported document must resolve within the document.

    Raw ``responses=`` schemas built with ``model_json_schema()`` carry
    ``#/$defs/...`` pointers that dangle at document scope and make strict
    consumers (docs generators, ref bundlers) reject the whole contract —
    use ``inline_json_schema()`` for those instead.
    """
    spec = _openapi()
    dangling: list[str] = []

    def resolve(pointer: str) -> bool:
        node: object = spec
        for token in pointer.lstrip("#/").split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or token not in node:
                return False
            node = node[token]
        return True

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str) and value.startswith("#"):
                    if not resolve(value):
                        dangling.append(f"{path}: {value}")
                else:
                    walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(spec, "")
    assert dangling == []
