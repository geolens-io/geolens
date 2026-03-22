from app.ogc.utils import build_url


# --- build_url() unit tests ---


def test_build_url_generates_absolute_urls():
    """build_url() returns absolute URL combining PUBLIC_BASE_URL with path."""
    result = build_url("/conformance")
    assert result.startswith("http")
    assert result.endswith("/conformance")


def test_build_url_avoids_double_slashes(monkeypatch):
    """build_url() normalizes trailing slash on base URL."""
    monkeypatch.setattr("app.ogc.utils.settings.public_base_url", "http://example.com/")
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


async def test_landing_page_openapi_link(client):
    """The service-desc link points to a valid OpenAPI JSON endpoint."""
    response = await client.get("/")
    data = response.json()

    service_desc = next(link for link in data["links"] if link["rel"] == "service-desc")
    assert service_desc["type"] == "application/vnd.oai.openapi+json;version=3.0"

    # Follow the link (extract path from absolute URL)
    from urllib.parse import urlparse

    path = urlparse(service_desc["href"]).path
    openapi_resp = await client.get(path)
    assert openapi_resp.status_code == 200
    openapi_data = openapi_resp.json()
    assert "openapi" in openapi_data


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
        "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30",
        # OGC API Features Part 1
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
    ]
    for cls in required_classes:
        assert cls in data["conformsTo"], f"Missing conformance class: {cls}"


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
    response = await client.get("/search/datasets", headers=admin_auth_header)
    assert response.status_code == 200
    data = response.json()
    if data["features"]:
        record = data["features"][0]
        assert "conformsTo" in record, "Record missing conformsTo"
        assert "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core" in record["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json" in record["conformsTo"]


# --- Regression test ---


async def test_health_still_works(client):
    """GET /health returns structured health response after OGC router registration."""
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "providers" in data
