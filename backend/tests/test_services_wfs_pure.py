"""Unit tests for pure XML and URL helpers in app.services.wfs.

These exercise the WFS GetCapabilities XML parser and the capabilities URL
builder without any network calls. The parser is exercised across WFS 1.0,
1.1, and 2.0 namespace shapes so regressions in namespace handling surface
quickly.
"""

from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.catalog.sources.adapters.wfs import (
    build_capabilities_url,
    parse_wfs_capabilities,
)


class TestParseWfsCapabilities:
    def test_wfs_1_1_namespace(self):
        xml = """<?xml version="1.0"?>
        <wfs:WFS_Capabilities version="1.1.0"
            xmlns:wfs="http://www.opengis.net/wfs">
          <wfs:FeatureTypeList>
            <wfs:FeatureType>
              <wfs:Name>ns:roads</wfs:Name>
              <wfs:Title>Roads</wfs:Title>
              <wfs:DefaultSRS>EPSG:4326</wfs:DefaultSRS>
            </wfs:FeatureType>
            <wfs:FeatureType>
              <wfs:Name>ns:parcels</wfs:Name>
              <wfs:Title>Parcels</wfs:Title>
              <wfs:DefaultSRS>EPSG:3857</wfs:DefaultSRS>
            </wfs:FeatureType>
          </wfs:FeatureTypeList>
        </wfs:WFS_Capabilities>
        """
        version, layers = parse_wfs_capabilities(xml)
        assert version == "1.1.0"
        assert len(layers) == 2
        # Phase 1057 D-05 / D-09: probe_wfs now includes geometry_type=None,
        # feature_count=None, and kind='vector' in each layer dict.
        assert layers[0] == {
            "name": "ns:roads",
            "title": "Roads",
            "crs": "EPSG:4326",
            "geometry_type": None,
            "feature_count": None,
            "kind": "vector",
        }
        assert layers[1]["name"] == "ns:parcels"
        assert layers[1]["crs"] == "EPSG:3857"

    def test_wfs_2_0_uses_defaultcrs(self):
        xml = """<?xml version="1.0"?>
        <wfs:WFS_Capabilities version="2.0.0"
            xmlns:wfs="http://www.opengis.net/wfs/2.0">
          <wfs:FeatureTypeList>
            <wfs:FeatureType>
              <wfs:Name>rivers</wfs:Name>
              <wfs:Title>Rivers</wfs:Title>
              <wfs:DefaultCRS>urn:ogc:def:crs:EPSG::4326</wfs:DefaultCRS>
            </wfs:FeatureType>
          </wfs:FeatureTypeList>
        </wfs:WFS_Capabilities>
        """
        version, layers = parse_wfs_capabilities(xml)
        assert version == "2.0.0"
        assert len(layers) == 1
        assert layers[0]["crs"] == "urn:ogc:def:crs:EPSG::4326"

    def test_wfs_1_0_uses_bare_srs(self):
        xml = """<?xml version="1.0"?>
        <WFS_Capabilities version="1.0.0">
          <FeatureTypeList>
            <FeatureType>
              <Name>lakes</Name>
              <Title>Lakes</Title>
              <SRS>EPSG:4326</SRS>
            </FeatureType>
          </FeatureTypeList>
        </WFS_Capabilities>
        """
        version, layers = parse_wfs_capabilities(xml)
        assert version == "1.0.0"
        assert len(layers) == 1
        assert layers[0]["crs"] == "EPSG:4326"

    def test_title_falls_back_to_name(self):
        xml = """<?xml version="1.0"?>
        <WFS_Capabilities version="1.1.0">
          <FeatureType>
            <Name>just_a_name</Name>
            <DefaultSRS>EPSG:4326</DefaultSRS>
          </FeatureType>
        </WFS_Capabilities>
        """
        _, layers = parse_wfs_capabilities(xml)
        assert layers[0]["title"] == "just_a_name"

    def test_feature_without_name_is_skipped(self):
        xml = """<?xml version="1.0"?>
        <WFS_Capabilities version="1.1.0">
          <FeatureType>
            <Title>Ghost layer</Title>
            <DefaultSRS>EPSG:4326</DefaultSRS>
          </FeatureType>
          <FeatureType>
            <Name>real_layer</Name>
            <DefaultSRS>EPSG:4326</DefaultSRS>
          </FeatureType>
        </WFS_Capabilities>
        """
        _, layers = parse_wfs_capabilities(xml)
        assert len(layers) == 1
        assert layers[0]["name"] == "real_layer"

    def test_missing_version_reports_unknown(self):
        xml = "<WFS_Capabilities></WFS_Capabilities>"
        version, layers = parse_wfs_capabilities(xml)
        assert version == "unknown"
        assert layers == []

    def test_malformed_xml_raises(self):
        import defusedxml.ElementTree as ET

        with pytest.raises(ET.ParseError):
            parse_wfs_capabilities("<not-xml")


class TestBuildCapabilitiesUrl:
    def _query(self, url: str) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    def test_adds_wfs_params_to_bare_url(self):
        url = build_capabilities_url("https://example.com/wfs")
        q = self._query(url)
        assert q["service"] == "WFS"
        assert q["request"] == "GetCapabilities"

    def test_preserves_existing_query_params(self):
        url = build_capabilities_url(
            "https://example.com/wfs?namespaces=xmlns(ns=http://foo)"
        )
        q = self._query(url)
        assert q["service"] == "WFS"
        assert q["request"] == "GetCapabilities"
        assert "namespaces" in q

    def test_overwrites_conflicting_service_param(self):
        url = build_capabilities_url(
            "https://example.com/wfs?service=WMS&request=GetMap"
        )
        q = self._query(url)
        assert q["service"] == "WFS"
        assert q["request"] == "GetCapabilities"

    def test_preserves_scheme_host_path(self):
        url = build_capabilities_url("https://example.com:8443/geoserver/wfs")
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "example.com:8443"
        assert parsed.path == "/geoserver/wfs"

    def test_a_query_over_the_old_field_count_bound_still_resolves(self):
        """fix(#1770 round 47c): round 47b bound this with `max_num_fields`,
        reasoning `_header_auth_probe` (`probe.py`) catches every
        `ValueError` from an adapter -- true for `probe_wfs`, but not the
        only caller. `origin_probe.py::service_probe_target` calls this for
        the periodic health check with NO surrounding `except ValueError`
        at all, so a 257-param caller URL reached `POST /datasets/{id}/
        source-health/` as a raw 500 instead of a coded refusal -- see
        `test_source_health_1222.py::test_a_many_param_service_url_still_
        probes_not_a_500` for the pin at the actual route. `url`
        is the caller's own submitted service URL, already capped at 2048
        chars by the schema, so it resolves normally at any field count a
        real URL that short can carry.
        """
        from app.platform.service_endpoints import MAX_QUERY_FIELDS

        query = "&".join(f"a{n}=1" for n in range(MAX_QUERY_FIELDS + 1))
        url = build_capabilities_url(f"https://example.com/wfs?{query}")
        q = self._query(url)
        assert q["service"] == "WFS"
        assert q["request"] == "GetCapabilities"
