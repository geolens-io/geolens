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
