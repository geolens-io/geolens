"""Post-process the generated OpenAPI document into the contract the runtime serves."""

import functools
import json
from collections.abc import Callable

from fastapi import FastAPI

from app.platform.ratelimit import limiter
from app.standards.ogc.errors import (
    DATABASE_UNAVAILABLE_RESPONSE,
    INTERNAL_SERVER_ERROR_RESPONSE,
    ProblemDetail,
    RATE_LIMIT_RESPONSE,
    UNRESOLVABLE_CREDENTIAL_RESPONSE,
    UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
    UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
)
from app.standards.ogc.utils import standards_api_path


def _iter_api_routes(target_app: FastAPI) -> list:
    """Every APIRoute on the app as a ``RouteContext``, including ones nested
    in lazily-included routers — fastapi 0.140 stopped flattening
    ``include_router`` into ``app.routes``, so a plain
    ``isinstance(route, APIRoute)`` scan over ``app.routes`` silently sees
    almost nothing. Consumers must read the effective full path from
    ``ctx.path``/``ctx.path_format`` (``ctx.route.path`` lacks the parent
    router prefix for nested includes) and route attributes from
    ``ctx.route``."""
    from fastapi.routing import APIRoute, iter_route_contexts

    return [
        ctx
        for ctx in iter_route_contexts(target_app.routes)
        if isinstance(ctx.route, APIRoute)
    ]


def _dependency_uses(dependant, targets: set[object]) -> bool:
    """Return whether a FastAPI dependency tree calls one of ``targets``."""
    if dependant.call in targets:
        return True
    return any(_dependency_uses(child, targets) for child in dependant.dependencies)


def _route_operation(schema: dict, ctx, method: str) -> dict | None:
    """Resolve a route context to its generated OpenAPI operation."""
    return schema.get("paths", {}).get(ctx.path_format, {}).get(method.lower())


def _normalize_security_contract(target_app: FastAPI, schema: dict) -> None:
    """Publish every runtime credential form and anonymous-capable alternative."""

    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
        require_session_credential,
    )

    security_schemes = schema.setdefault("components", {}).setdefault(
        "securitySchemes", {}
    )
    security_schemes["ApiKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
        "description": "GeoLens API key. Preferred API-key transport.",
    }
    security_schemes["ApiKeyQuery"] = {
        "type": "apiKey",
        "in": "query",
        "name": "api_key",
        "description": (
            "Legacy API-key query parameter, accepted on GET/HEAD/OPTIONS "
            "only; ignored on any other method. Prefer X-Api-Key."
        ),
    }

    # ``get_optional_user_no_security_schema`` stays credential-aware at
    # runtime without stamping auth onto generated clients; only the normal
    # optional dependencies gain security alternatives here.
    #
    # Both optional dependencies belong in this set — they differ
    # in what an unresolvable credential does (401 vs anonymous), not in
    # whether the operation accepts one, and the published contract is the
    # latter.
    optional_targets = {get_optional_user, get_optional_user_fail_open}
    credential_alternatives = [
        {"OAuth2PasswordBearer": []},
        {"ApiKeyHeader": []},
        {"ApiKeyQuery": []},
    ]

    for ctx in _iter_api_routes(target_app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        optional_auth = _dependency_uses(route.dependant, optional_targets)
        # These routes refuse an API key at runtime, so they publish bearer only.
        bearer_only = _dependency_uses(route.dependant, {require_session_credential})
        alternatives = credential_alternatives[: 1 if bearer_only else None]
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            existing = operation.get("security", [])
            has_bearer = any("OAuth2PasswordBearer" in item for item in existing)
            if not optional_auth and not has_bearer:
                continue

            preserved = [
                item
                for item in existing
                if not any(
                    key in item
                    for key in ("OAuth2PasswordBearer", "ApiKeyHeader", "ApiKeyQuery")
                )
            ]
            operation["security"] = (
                ([{}] if optional_auth else []) + alternatives + preserved
            )


def _document_rate_limits(target_app: FastAPI, schema: dict) -> None:
    """Attach the runtime SlowAPI 429 contract to every non-exempt operation."""

    for ctx in _iter_api_routes(target_app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        endpoint_name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        # The limiter has a global default, so undecorated routes are limited too.
        # Only explicit @limiter.exempt handlers bypass the middleware contract.
        if endpoint_name in limiter._exempt_routes:
            continue
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is not None:
                operation.setdefault("responses", {}).setdefault(
                    "429", RATE_LIMIT_RESPONSE
                )


def _document_unresolvable_credential_401(target_app: FastAPI, schema: dict) -> None:
    """Publish the #1518 401 on every operation that can raise it.

    ``get_optional_user`` refuses a supplied-but-unresolvable credential,
    so a 401 is now normal on routes documented as anonymous-only; SDK
    error unions need it or a typed client can't represent it.

    Targets all three optional dependencies — one more than
    ``_normalize_security_contract`` — since ``get_optional_user_fail_open``
    defers to its own handlers, and ``get_optional_user_no_security_schema``
    answers identically to ``get_optional_user`` despite being excluded
    from the security-marker set. Only writes ``responses``,
    never ``security``, so it can't stamp an auth requirement back on.
    Pinned by ``test_no_security_schema_ops_get_401_without_security``.

    A handler ``CAPABILITY`` marks in ``FAIL_OPEN_ALLOWLIST``
    (``tests/test_optional_auth_failure_mode_1518.py``) gets a response
    naming only the capability it actually accepts; every other operation
    gets the plain, capability-free description.
    """

    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    )
    from app.modules.catalog.datasets.api.router_aggregate import aggregate_endpoint
    from app.modules.catalog.datasets.api.router_data import get_dataset_rows_endpoint
    from app.modules.catalog.features.router import get_features_geojson_z_endpoint
    from app.modules.catalog.maps.router_sharing import get_shared_map_endpoint
    from app.processing.tiles.router import (
        cluster_tile_endpoint,
        get_tile_tokens_batch,
        raster_auth_check,
        raster_tile_proxy,
        tile_endpoint,
    )

    credential_aware = {
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    }
    # Vector/raster tile serving verifies both X-Embed-Token and a signed
    # template (sig, exp, scope); the batch token mint and the other
    # capability handlers check X-Embed-Token only.
    capability_responses = {
        aggregate_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_dataset_rows_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_features_geojson_z_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_shared_map_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_tile_tokens_batch: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        tile_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
        cluster_tile_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
        raster_tile_proxy: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
        raster_auth_check: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
    }

    for ctx in _iter_api_routes(target_app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        if not _dependency_uses(route.dependant, credential_aware):
            continue
        response = capability_responses.get(route.endpoint)
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            responses = operation.setdefault("responses", {})
            if response is not None:
                # A mapped route's shared generic 401 (spread from an
                # ERROR_RESPONSES_* constant on the route or an ancestor
                # router) would otherwise win by already occupying the key;
                # the mapping names what this route actually accepts, so it
                # overrides rather than defers to that generic text.
                responses["401"] = response
            else:
                # setdefault: a route that already documents its own 401 with
                # a more specific description keeps it.
                responses.setdefault("401", UNRESOLVABLE_CREDENTIAL_RESPONSE)


def _document_global_failures(target_app: FastAPI, schema: dict) -> None:
    """Document exception handlers that apply outside individual routers."""

    from app.core.dependencies import get_db

    for ctx in _iter_api_routes(target_app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        uses_database = _dependency_uses(route.dependant, {get_db})
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            responses = operation.setdefault("responses", {})
            responses.setdefault("500", INTERNAL_SERVER_ERROR_RESPONSE)
            if uses_database:
                responses.setdefault("503", DATABASE_UNAVAILABLE_RESPONSE)


def _repair_depends_bound_query_model(schema: dict) -> None:
    """Publish the query parameters a ``Depends()``-bound model fails to declare.

    ``SearchQueryParams`` reaches ``collection_items`` via
    ``Depends()``, and two fields don't survive — ``keywords`` reads as a
    GET JSON body, and ``cql2_filter_lang``'s alias ``filter-lang`` can't
    be named by pydantic's synthesized ``__init__``. Copies the correct
    definitions from ``search_datasets_endpoint`` rather than restating
    them (a hand-written mirror drifts); ``collection_items`` can't use
    that form itself since its five OGC parameters collapse a query
    model to one scalar.

    Deliberate asymmetry: still BINDS the legacy GET body at runtime,
    just doesn't advertise it — a malformed body gets a 400 the contract
    doesn't describe. Sending none, as every correct client does, is fine.
    """
    paths = schema.get("paths", {})
    donor = paths.get("/search/datasets/", {}).get("get")
    target = paths.get("/collections/datasets/items", {}).get("get")
    if donor is None or target is None:
        return

    donated = {
        parameter["name"]: parameter
        for parameter in donor.get("parameters", [])
        if parameter.get("name") in {"keywords", "filter-lang"}
    }
    if len(donated) != 2:
        # The donor stopped declaring them correctly; leave the target alone
        # rather than publishing a half-repaired contract.
        return

    parameters = [
        parameter
        for parameter in target.get("parameters", [])
        if parameter.get("name") not in {"cql2_filter_lang", *donated}
    ]
    parameters.extend(donated.values())
    target["parameters"] = parameters

    # The phantom body this defect produces. Only drop the one the model caused.
    body = target.get("requestBody", {})
    body_schema = body.get("content", {}).get("application/json", {}).get("schema", {})
    if body_schema.get("title") == "Keywords":
        target.pop("requestBody", None)


def _normalize_validation_error_contract(schema: dict) -> None:
    """Publish the RFC 7807 body every validation failure actually returns.

    FastAPI stamps ``422 -> HTTPValidationError`` (an ``application/json`` body
    of ``{detail: [{loc, msg, type}, ...]}``) on every operation with request
    validation. The ``RequestValidationError`` handler in
    ``standards/ogc/errors.py`` overrides that at runtime with a problem+json
    ``ProblemDetail`` whose ``detail`` is flattened to one string, and generated
    clients inherit the published shape. The standards-path loop below applies
    the same correction under the OGC status rule; this covers every other
    operation.
    """
    validation_response = {
        "description": "Validation error",
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"}
            }
        },
    }
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head"}:
                continue
            responses = operation.get("responses", {})
            if "422" in responses:
                responses["422"] = dict(validation_response)


def _drop_unreferenced_validation_models(schema: dict) -> None:
    """Drop FastAPI's validation models once nothing references them.

    Checked, not popped unconditionally: a route may declare
    ``HTTPValidationError`` in ``responses=``, and dropping a still-
    referenced component breaks SDK generation with a dangling ``$ref``.

    Excludes only the candidate from the search, not both —
    ``HTTPValidationError`` holds the sole ``$ref`` to
    ``ValidationError``, so excluding both would delete a schema a
    surviving operation still points at. Container checked before leaf,
    so dropping it makes the leaf unreferenced next pass; reversed, the
    leaf would be held alive by a container about to go.
    """
    schemas = schema.get("components", {}).get("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        others = json.dumps(
            {
                **{k: v for k, v in schema.items() if k != "components"},
                "schemas": {k: v for k, v in schemas.items() if k != name},
            }
        )
        if f"#/components/schemas/{name}" not in others:
            schemas.pop(name, None)


# OGC API Common requires malformed standards-path parameters to use 400.  The
# runtime RequestValidationError handler applies that contract; normalize the
# generated description too so machine clients are not told to expect FastAPI's
# native 422 response on OGC/STAC/DCAT operations.
def _standards_aware_openapi(
    target_app: FastAPI, fastapi_openapi: Callable[[], dict]
) -> dict:
    schema = fastapi_openapi()
    if schema.get("x-geolens-standards-errors") == "400-problem-details":
        return schema

    # Error responses reference ProblemDetail explicitly under the RFC 7807
    # media type. Register the component here rather than using FastAPI's
    # ``responses={..., "model": ...}`` shortcut, which also advertises an
    # application/json body that the runtime never returns.
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas["ProblemDetail"] = ProblemDetail.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )

    # SSE is framed text at the HTTP layer, while each ``data`` field carries
    # one of these JSON payloads. The streaming operations reference the DTOs
    # through a vendor extension, so register them explicitly without falsely
    # advertising the whole response as application/json.
    from app.processing.ai.schemas import (
        SSEActionsEvent,
        SSEChatDoneEvent,
        SSEErrorEvent,
        SSEMapDoneEvent,
        SSETokenEvent,
        SSEToolResultEvent,
        SSEToolStartEvent,
    )

    for event_model in (
        SSEActionsEvent,
        SSEChatDoneEvent,
        SSEErrorEvent,
        SSEMapDoneEvent,
        SSETokenEvent,
        SSEToolResultEvent,
        SSEToolStartEvent,
    ):
        event_schema = event_model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        for definition_name, definition in event_schema.pop("$defs", {}).items():
            schemas.setdefault(definition_name, definition)
        schemas[event_model.__name__] = event_schema

    _normalize_security_contract(target_app, schema)
    _document_unresolvable_credential_401(target_app, schema)
    _document_rate_limits(target_app, schema)
    _document_global_failures(target_app, schema)
    _normalize_validation_error_contract(schema)
    _repair_depends_bound_query_model(schema)

    for path, path_item in schema.get("paths", {}).items():
        if standards_api_path(path) is None:
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            responses = operation.setdefault("responses", {})
            responses.pop("422", None)
            responses.setdefault(
                "400",
                {
                    "description": "Bad request — invalid standards parameters",
                    "content": {
                        "application/problem+json": {
                            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
                        }
                    },
                },
            )

            if path == "/collections/datasets/items" and method == "get":
                for parameter in operation.get("parameters", []):
                    if parameter.get("name") in {"type", "ids", "externalIds"}:
                        # OGC API Records 1.0 requirements 24/30/32 specify
                        # comma-separated form arrays (explode=false).
                        parameter["style"] = "form"
                        parameter["explode"] = False

    _drop_unreferenced_validation_models(schema)

    schema["x-geolens-standards-errors"] = "400-problem-details"
    target_app.openapi_schema = schema
    return schema


def install_standards_aware_openapi(target_app: FastAPI) -> None:
    """Serve ``_standards_aware_openapi`` as ``target_app.openapi``."""
    target_app.openapi = functools.partial(  # type: ignore[method-assign]
        _standards_aware_openapi, target_app, target_app.openapi
    )
