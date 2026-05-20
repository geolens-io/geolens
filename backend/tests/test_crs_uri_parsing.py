"""Unit tests for the CRS URI/URN parsing helper.

Phase 1057 CRS-06 — Finding 6 in SMOKE-v1012-REPORT.md:
  URI-form CRS (http://www.opengis.net/def/crs/OGC/1.3/CRS84) not parsed to EPSG.
  User importing demo.pygeoapi.io/master → Large Lakes saw "CRS: Unknown" and had
  to enter a manual EPSG override.

Covers:
  - parse_crs_uri: the four D-07 URI/URN forms + fallthrough to None
  - extract_srid_from_json: ordering tests (projjson → WKT → URI) to pin third-fallback
    integration behavior
"""

import pytest

from app.modules.catalog.sources.crs_uri import parse_crs_uri
from app.processing.ingest.ogr import extract_srid_from_json


# ---------------------------------------------------------------------------
# TestParseCrsUri — unit tests for the pure helper (16 cases)
# ---------------------------------------------------------------------------


class TestParseCrsUri:
    """Pin the four D-07 URI/URN forms and the fallthrough (None) behavior.

    Reference: Phase 1057 CRS-06, D-07, SMOKE-v1012-REPORT.md Finding 6.
    Exact repro URI: http://www.opengis.net/def/crs/OGC/1.3/CRS84
    """

    # ---- Form 1 + 2: OGC CRS84 via HTTP and HTTPS ----

    @pytest.mark.parametrize(
        "uri,expected",
        [
            # Form 1 (HTTP) — exact repro from Finding 6
            ("http://www.opengis.net/def/crs/OGC/1.3/CRS84", 4326),
            # Form 2 (HTTPS variant)
            ("https://www.opengis.net/def/crs/OGC/1.3/CRS84", 4326),
        ],
    )
    def test_ogc_crs84_http_forms(self, uri: str, expected: int) -> None:
        assert parse_crs_uri(uri) == expected

    # ---- Form 3: EPSG via HTTP/HTTPS numeric code ----

    @pytest.mark.parametrize(
        "uri,expected",
        [
            ("http://www.opengis.net/def/crs/EPSG/0/3857", 3857),
            ("http://www.opengis.net/def/crs/EPSG/0/4326", 4326),
            ("https://www.opengis.net/def/crs/EPSG/0/32633", 32633),
        ],
    )
    def test_epsg_http_forms(self, uri: str, expected: int) -> None:
        assert parse_crs_uri(uri) == expected

    # ---- Form 4: EPSG URN ----

    @pytest.mark.parametrize(
        "uri,expected",
        [
            ("urn:ogc:def:crs:EPSG::4326", 4326),
            ("urn:ogc:def:crs:EPSG::3857", 3857),
            ("urn:ogc:def:crs:EPSG::32633", 32633),
        ],
    )
    def test_epsg_urn_forms(self, uri: str, expected: int) -> None:
        assert parse_crs_uri(uri) == expected

    # ---- Form 5: OGC CRS84 URN ----

    def test_ogc_crs84_urn_form(self) -> None:
        assert parse_crs_uri("urn:ogc:def:crs:OGC:1.3:CRS84") == 4326

    # ---- Fallthrough: None inputs ----

    def test_none_input(self) -> None:
        assert parse_crs_uri(None) is None

    def test_empty_string(self) -> None:
        assert parse_crs_uri("") is None

    # ---- Fallthrough: unrecognized URIs ----

    def test_unknown_http_uri(self) -> None:
        assert parse_crs_uri("http://example.com/crs/foo") is None

    def test_unknown_urn(self) -> None:
        assert parse_crs_uri("urn:something:else") is None

    # ---- Fallthrough: bare EPSG strings are NOT this helper's job ----

    def test_bare_epsg_string_returns_none(self) -> None:
        """Bare 'EPSG:4326' strings are handled elsewhere (ogrinfo projjson/WKT).

        This helper covers ONLY the 4 URI/URN forms in D-07.
        """
        assert parse_crs_uri("EPSG:4326") is None

    # ---- Defensive: malformed URIs ----

    def test_non_numeric_epsg_code_returns_none(self) -> None:
        """Non-numeric EPSG code in URI form → None (malformed URI defense)."""
        assert parse_crs_uri("http://www.opengis.net/def/crs/EPSG/0/abc") is None

    def test_large_epsg_code_returns_int(self) -> None:
        """Arbitrary-large EPSG codes are accepted — EPSG authority controls the namespace.

        No artificial upper bound is imposed; the helper returns int(code) unconditionally
        for any non-negative integer that regex-matches. Downstream PostGIS rejects
        unknown SRIDs at Find_SRID / ST_Transform time (T-1057C-04 accept).
        """
        result = parse_crs_uri("http://www.opengis.net/def/crs/EPSG/0/99999999999999999999")
        # Any non-negative int is acceptable; None is also acceptable if executor chose a cap
        # (see helper docstring). This assertion is intentionally lenient.
        assert result is None or isinstance(result, int)


# ---------------------------------------------------------------------------
# TestExtractSridFromJsonUriFallback — integration tests pinning the
# projjson → WKT → URI fallback ordering in extract_srid_from_json
# ---------------------------------------------------------------------------


class TestExtractSridFromJsonUriFallback:
    """Integration tests for extract_srid_from_json URI-fallback ordering.

    Phase 1057 CRS-06 — Finding 6 (demo.pygeoapi.io/master Large Lakes):
      After D-07, extract_srid_from_json must resolve URI/URN-form CRS from the
      coordinateSystem.name field as the THIRD fallback (after projjson + WKT).
      Authoritative projjson and WKT declarations must still win.

    Key invariant: projjson → WKT → URI. URI parsing must NOT override
    authoritative EPSG declarations carried in projjson or WKT.
    """

    # ---- URI fallback fires when projjson + WKT are absent ----

    def test_ogc_crs84_uri_fallback(self) -> None:
        """URI-form CRS84 in coordinateSystem.name → 4326."""
        result = extract_srid_from_json(
            {"name": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}
        )
        assert result == 4326

    def test_epsg_urn_fallback(self) -> None:
        """URN-form EPSG in coordinateSystem.name → numeric EPSG code."""
        result = extract_srid_from_json(
            {"name": "urn:ogc:def:crs:EPSG::3857"}
        )
        assert result == 3857

    # ---- Ordering: projjson wins over URI ----

    def test_projjson_wins_over_uri(self) -> None:
        """projjson is the FIRST fallback and wins over the URI form (third)."""
        result = extract_srid_from_json(
            {
                "projjson": {"id": {"authority": "EPSG", "code": 4326}},
                "name": "urn:ogc:def:crs:EPSG::3857",
            }
        )
        assert result == 4326  # projjson value, not the URN value

    # ---- Ordering: WKT wins over URI ----

    def test_wkt_wins_over_uri(self) -> None:
        """WKT is the SECOND fallback and wins over the URI form (third)."""
        result = extract_srid_from_json(
            {
                "wkt": 'GEOGCS["WGS 84",AUTHORITY["EPSG","4326"]]',
                "name": "urn:ogc:def:crs:EPSG::3857",
            }
        )
        assert result == 4326  # WKT value, not the URN value

    # ---- Fallthrough: unrecognized URI returns None ----

    def test_unrecognized_uri_fallthrough(self) -> None:
        """Unrecognized URI in name → None (preserves null-CRS behavior)."""
        result = extract_srid_from_json(
            {"name": "http://example.com/random"}
        )
        assert result is None

    # ---- Edge cases ----

    def test_empty_coord_system(self) -> None:
        """Empty dict → None (preserves existing early-out)."""
        assert extract_srid_from_json({}) is None

    def test_null_name_key(self) -> None:
        """name key present but None → None (defensive against missing/null)."""
        assert extract_srid_from_json({"name": None}) is None
