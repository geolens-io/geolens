from app.standards.ogc.utils import build_url


# --- build_url() unit tests ---


def test_build_url_generates_absolute_urls():
    """build_url() returns absolute URL combining PUBLIC_BASE_URL with path."""
    result = build_url("/conformance")
    assert result.startswith("http")
    assert result.endswith("/conformance")


def test_build_url_avoids_double_slashes(monkeypatch):
    """build_url() normalizes trailing slash on base URL."""
    # Patch in both the source module and the importing module
    monkeypatch.setattr(
        "app.standards.ogc.utils.get_env_public_api_url",
        lambda request=None: "http://example.com/",
    )
    result = build_url("/conformance")
    assert "//conformance" not in result
    assert result == "http://example.com/conformance"


# --- Landing page endpoint tests ---


async def test_landing_page_returns_200_without_auth(client):
    """GET / returns 200 with no Authorization header."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "description" in data
    assert "links" in data

    # Check required rel values are present
    rels = {link["rel"] for link in data["links"]}
    assert "self" in rels
    assert "conformance" in rels
    assert "data" in rels
    assert "service-desc" in rels


async def test_landing_page_links_are_absolute(client):
    """All href values in landing page links are absolute URLs."""
    response = await client.get("/")
    data = response.json()
    for link in data["links"]:
        assert link["href"].startswith("http"), (
            f"Link rel={link['rel']} has non-absolute href: {link['href']}"
        )


async def test_landing_page_service_doc_link(client):
    """The service-doc link is present with correct type."""
    response = await client.get("/")
    data = response.json()

    service_doc = next(
        (link for link in data["links"] if link["rel"] == "service-doc"), None
    )
    assert service_doc is not None, "Missing service-doc link"
    assert service_doc["type"] == "text/html"


async def test_landing_page_omits_service_doc_in_production(client, monkeypatch):
    """In production, FastAPI disables Swagger (/docs -> 404), so the landing page
    must NOT advertise a dead service-doc link. service-desc (/openapi.json stays
    served in production) must remain."""
    from app.core.config import settings

    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    response = await client.get("/")
    assert response.status_code == 200
    rels = {link["rel"] for link in response.json()["links"]}
    assert "service-doc" not in rels
    assert "service-desc" in rels


async def test_landing_page_openapi_link(client):
    """The service-desc link points to a valid OpenAPI JSON endpoint."""
    response = await client.get("/")
    data = response.json()

    service_desc = next(link for link in data["links"] if link["rel"] == "service-desc")
    assert service_desc["type"] == "application/vnd.oai.openapi+json;version=3.1"

    # Follow the link (extract path from absolute URL)
    from urllib.parse import urlparse

    path = urlparse(service_desc["href"]).path
    openapi_resp = await client.get(path)
    assert openapi_resp.status_code == 200
    openapi_data = openapi_resp.json()
    assert openapi_data["openapi"].startswith("3.1.")


async def test_standards_openapi_documents_problem_400(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    operation = response.json()["paths"]["/collections/datasets/items"]["get"]
    assert "400" in operation["responses"]
    assert "422" not in operation["responses"]
    assert "application/problem+json" in operation["responses"]["400"]["content"]

    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["type"]["schema"]["type"] == "array"
    assert parameters["ids"]["schema"]["type"] == "array"
    assert parameters["externalIds"]["schema"]["type"] == "array"
    for name in ("type", "ids", "externalIds"):
        assert parameters[name]["style"] == "form"
        assert parameters[name]["explode"] is False

    dcat_operation = response.json()["paths"]["/datasets/dcat/"]["get"]
    assert "400" in dcat_operation["responses"]
    assert "422" not in dcat_operation["responses"]

    dcat_us_operation = response.json()["paths"]["/datasets/dcat-us/3.0/"]["get"]
    assert "503" in dcat_us_operation["responses"]

    feature_schema = operation["responses"]["200"]["content"]["application/geo+json"][
        "schema"
    ]
    assert feature_schema == {
        "$ref": "#/components/schemas/OGCFeatureCollectionResponse"
    }
    item_operation = response.json()["paths"][
        "/collections/datasets/items/{record_id}"
    ]["get"]
    item_schema = item_operation["responses"]["200"]["content"]["application/geo+json"][
        "schema"
    ]
    assert item_schema == {"$ref": "#/components/schemas/OGCRecordResponse"}


# --- Landing page f parameter tests ---


async def test_landing_page_f_json_accepted(client):
    """GET /?f=json returns 200."""
    response = await client.get("/", params={"f": "json"})
    assert response.status_code == 200


async def test_landing_page_f_unsupported_returns_400(client):
    """GET /?f=xml returns 400 with error detail."""
    response = await client.get("/", params={"f": "xml"})
    assert response.status_code == 400
    data = response.json()
    assert "Unsupported format" in data["detail"]


async def test_landing_page_reports_serialized_language(client):
    response = await client.get("/", headers={"Accept-Language": "fr"})
    assert response.status_code == 200
    assert response.headers["content-language"] == "en"


async def test_anonymous_standards_cors_default_is_read_only(client, monkeypatch):
    async def _deny_origin(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed",
        _deny_origin,
    )

    response = await client.get(
        "/conformance", headers={"Origin": "https://client.example"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers

    preflight = await client.options(
        "/collections/datasets/items",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Accept",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"

    dcat_preflight = await client.options(
        "/datasets/dcat/",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Accept",
        },
    )
    assert dcat_preflight.status_code == 200
    assert dcat_preflight.headers["access-control-allow-origin"] == "*"
    assert (
        "X-GeoLens-Source-Dataset-Count"
        in dcat_preflight.headers["access-control-expose-headers"]
    )

    credentialed = await client.get(
        "/conformance",
        headers={
            "Origin": "https://client.example",
            "Cookie": "session=not-a-real-session",
        },
    )
    assert "access-control-allow-origin" not in credentialed.headers


async def test_head_is_served_wherever_the_preflight_advertises_it(client, monkeypatch):
    """fix(#1470): the preflight said HEAD was allowed; the route said 405.

    ``_set_public_cors_headers`` answers a standards preflight with
    ``GET, HEAD, POST, OPTIONS``, so a browser client that trusts it sent HEAD
    and got ``405 allow: GET``. Both surfaces are now derived from
    ``standards_api_path``.

    ``_is_origin_allowed`` is stubbed for the same reason the sibling CORS
    test above stubs it, and it is load-bearing rather than tidy: a real
    lookup populates ``cors._origins_cache``, a module global with a 30s TTL
    and no invalidation on settings write. Under ``pytest -n 4`` that cache
    outlives this test and makes ``test_persistent_config.py::
    test_cors_preflight_returns_200`` read a stale origin set and 405 — which
    is exactly how it failed on this PR's first CI run.
    """

    async def _deny_origin(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed",
        _deny_origin,
    )

    preflight = await client.options(
        "/collections",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "HEAD",
            "Access-Control-Request-Headers": "Accept",
        },
    )
    assert preflight.status_code == 200
    assert "HEAD" in preflight.headers["access-control-allow-methods"]

    for path in ("/collections", "/", "/conformance", "/stac", "/datasets/dcat/"):
        head = await client.head(path)
        get = await client.get(path)
        assert head.status_code == 200, path
        assert head.status_code == get.status_code, path
        assert head.headers.get("content-type") == get.headers.get("content-type"), path
        assert head.content == b"", path
        assert get.content, path


async def test_head_stays_off_non_standards_routes(client):
    """The pass is scoped by the same classifier, not applied app-wide."""
    response = await client.head("/datasets/")
    assert response.status_code == 405
    assert "HEAD" not in response.headers.get("allow", "")


async def test_standards_405_allow_header_reports_head(client):
    """A 405 must enumerate what the surface answers, HEAD included.

    HEAD is registered as a separate route (see
    ``_register_standards_head_routes``), and starlette builds ``Allow`` from
    the first partial match — the GET-only canonical route — so the header
    understated the surface until the standards error handler restated it.
    """
    for path in ("/conformance", "/collections", "/stac"):
        response = await client.request("PUT", path)
        assert response.status_code == 405, path
        methods = {m.strip() for m in response.headers["allow"].split(",")}
        assert methods == {"GET", "HEAD"}, path

    # Scoped: a native route's 405 keeps the methods it actually serves.
    native = await client.request("PUT", "/datasets/")
    assert native.status_code == 405
    assert "HEAD" not in native.headers.get("allow", "")


async def test_standards_router_errors_keep_problem_details(client):
    """The 405 handler binds starlette's base class, not fastapi's subclass.

    Routers raise fastapi's ``HTTPException``, which must keep resolving to
    the problem+json handler — registering a base-class handler beside it
    would be a silent contract change if MRO lookup preferred the general one.
    """
    response = await client.get("/collections/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


# --- Conformance endpoint tests ---


async def test_conformance_returns_200_without_auth(client):
    """GET /conformance returns 200 with no Authorization header."""
    response = await client.get("/conformance")
    assert response.status_code == 200
    data = response.json()
    assert "conformsTo" in data
    assert isinstance(data["conformsTo"], list)


async def test_conformance_contains_required_classes(client):
    """GET /conformance includes OGC API Common and Features Part 1 conformance classes."""
    response = await client.get("/conformance")
    data = response.json()
    required_classes = [
        # OGC API Common
        "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core",
        "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page",
        "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json",
        # OGC API Features Part 1
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    ]
    for cls in required_classes:
        assert cls in data["conformsTo"], f"Missing conformance class: {cls}"
    assert not any(value.endswith("/conf/oas30") for value in data["conformsTo"])


async def test_conformance_contains_records_classes(client):
    """GET /conformance includes OGC API Records Part 1 conformance classes."""
    response = await client.get("/conformance")
    assert response.status_code == 200
    data = response.json()
    required_records_classes = [
        "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core",
        "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core-query-parameters",
        "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json",
    ]
    for cls in required_records_classes:
        assert cls in data["conformsTo"], f"Missing Records class: {cls}"


async def test_conformance_f_json_accepted(client):
    """GET /conformance?f=json returns 200."""
    response = await client.get("/conformance", params={"f": "json"})
    assert response.status_code == 200


# fix(#1674 codex): qgis/QGIS#62156 (merged 2025-06-05, first released in QGIS
# 3.44) fixed the OAPIF provider's server-capability detection to recognize
# the FINAL-SPEC conformance class name `cql2/1.0/conf/basic-spatial-functions`
# -- QGIS<3.44 only recognized the deprecated draft name
# `cql2/{0.0,1.0}/conf/basic-spatial-operators`. QgsOapifProvider::init() sets
# two independent capability flags from the classes below (verified against
# the merged patch, src/providers/wfs/oapif/qgsoapifprovider.cpp):
#
#   mServerSupportsFilterCql2Text (base gate for ANY filter push-down; ALL
#   four required):
#     cql2/{0.0,1.0}/conf/basic-cql2
#     ogcapi-features-3/{0.0,1.0}/conf/filter
#     ogcapi-features-3/{0.0,1.0}/conf/features-filter
#     cql2/{0.0,1.0}/conf/cql2-text
#
#   mServerSupportsBasicSpatialFunctions (gates S_INTERSECTS/BBOX()/POINT()
#   push-down specifically -- the class this PR fixed recognition of):
#     cql2/1.0/conf/basic-spatial-functions
#
# The CQL2 spec (opengeospatial/ogcapi-features, cql2/standard/requirements/
# basic-spatial-functions/REQ_spatial-functions.adoc) mandates only
# S_INTERSECTS for this class, which is exactly what GeoLens's filter
# validator (standards/ogc/filtering.py) supports -- advertising it is
# honest. GeoLens serves the 1.0 URI for every class below; this pins that
# set so a future conformance-list edit cannot silently drop QGIS push-down.
_QGIS_3_44_CQL2_PUSHDOWN_CLASSES = [
    "http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2",
    "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter",
    "http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter",
    "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
    "http://www.opengis.net/spec/cql2/1.0/conf/basic-spatial-functions",
]


async def test_conformance_pins_qgis_344_cql2_pushdown_classes(client):
    """GET /conformance advertises every class QGIS>=3.44 needs before it
    pushes CQL2 filters (including spatial S_INTERSECTS) down to this server.

    A regression here never 500s or 400s anywhere: QGIS just falls back to
    client-side filtering, which is silent until someone notices a large
    layer got slow. See qgis/QGIS#62156 for the exact detection logic.
    """
    response = await client.get("/conformance")
    assert response.status_code == 200
    conforms_to = response.json()["conformsTo"]
    for cls in _QGIS_3_44_CQL2_PUSHDOWN_CLASSES:
        assert cls in conforms_to, f"Missing QGIS CQL2 push-down class: {cls}"


async def test_conformance_f_unsupported_returns_400(client):
    """GET /conformance?f=xml returns 400."""
    response = await client.get("/conformance", params={"f": "xml"})
    assert response.status_code == 400
    data = response.json()
    assert "Unsupported format" in data["detail"]


# --- Per-record conformsTo test ---


async def test_ogc_record_includes_conforms_to(client, admin_auth_header):
    """OGC Record responses include conformsTo array."""
    response = await client.get("/search/datasets/", headers=admin_auth_header)
    assert response.status_code == 200
    data = response.json()
    if data["features"]:
        record = data["features"][0]
        assert "conformsTo" in record, "Record missing conformsTo"
        assert (
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core"
            in record["conformsTo"]
        )
        assert (
            "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json"
            in record["conformsTo"]
        )


# --- Regression test ---


async def test_health_still_works(client):
    """GET /health returns structured health response after OGC router registration."""
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "providers" in data
