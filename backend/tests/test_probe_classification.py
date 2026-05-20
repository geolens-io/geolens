"""Tests for classify_layer_kind helper (Phase 1057, CLASS-07 D-09).

Covers:
  - TestClassifyLayerKind: unit tests for the pure classify_layer_kind function
  - TestProbeOrchestratorNoEnrichment: integration tests verifying that
    detect_service_type no longer calls enrich_ogcapi_layers or enrich_wfs_layers
    (PROBE-05 fix, per D-04 / D-05).
"""

import time

import pytest

from app.modules.catalog.sources.classify import classify_layer_kind


class TestClassifyLayerKind:
    """Pin the D-09 classification rule for classify_layer_kind.

    D-09: layer is 'raster' IFF:
      1. adapter_type == 'stac'
      2. geometry_type lowercased contains 'raster'
      3. layer has coverage_format key
      4. layer has bands key
      5. any link in layer['links'] has type starting with 'image/'
    Everything else (including geometry_type=None) → 'vector'.
    """

    def test_stac_adapter_always_raster(self):
        """D-09 rule 1: STAC adapter is always raster regardless of other fields."""
        result = classify_layer_kind({}, adapter_type="stac")
        assert result == "raster"

    def test_stac_adapter_always_raster_even_with_geometry_type(self):
        """D-09 rule 1: STAC adapter is raster even if geometry_type suggests vector."""
        result = classify_layer_kind(
            {"geometry_type": "MultiPolygon"}, adapter_type="stac"
        )
        assert result == "raster"

    @pytest.mark.parametrize(
        "geometry_type",
        [
            "raster",
            "Raster",
            "RASTER",
            "rasterBand",
            "gridcoverage_raster",
        ],
    )
    def test_geometry_type_containing_raster_is_raster(self, geometry_type: str):
        """D-09 rule 2: geometry_type lowercased containing 'raster' → raster."""
        result = classify_layer_kind(
            {"geometry_type": geometry_type}, adapter_type="ogcapi"
        )
        assert result == "raster"

    @pytest.mark.parametrize(
        "layer_dict",
        [
            {"coverage_format": "image/tiff"},
            {"coverage_format": ""},  # empty string is falsy — stays vector
            {"bands": [{"name": "B1"}]},
            {"bands": 3},
            {
                "links": [
                    {"rel": "item", "type": "image/png"},
                ]
            },
            {
                "links": [
                    {"rel": "data", "type": "application/json"},
                    {"rel": "enclosure", "type": "image/tiff"},
                ]
            },
        ],
    )
    def test_raster_signal_fields_trigger_raster(self, layer_dict: dict):
        """D-09 rules 3-5: coverage_format/bands/image/* mediaType signal → raster.

        Note: empty string coverage_format is falsy so the empty-string case should
        return 'vector'. The parametrize includes it to document the edge case.
        """
        # The empty coverage_format case should return vector (falsy value)
        if layer_dict.get("coverage_format") == "":
            result = classify_layer_kind(layer_dict, adapter_type="ogcapi")
            assert result == "vector"
        else:
            result = classify_layer_kind(layer_dict, adapter_type="ogcapi")
            assert result == "raster"

    def test_null_geometry_type_ogcapi_is_vector(self):
        """D-09: OGC API Features collection with no geometry_type → vector (D-05 post-drop default)."""
        result = classify_layer_kind(
            {"name": "rivers", "title": "Natural Rivers", "crs": None},
            adapter_type="ogcapi",
        )
        assert result == "vector"

    def test_wfs_layer_is_always_vector(self):
        """D-09: WFS layers are always vector by OGC spec."""
        result = classify_layer_kind(
            {"name": "topp:countries", "title": "Countries", "crs": "EPSG:4326"},
            adapter_type="wfs",
        )
        assert result == "vector"

    def test_arcgis_featureserver_layer_is_vector(self):
        """D-09: ArcGIS FeatureServer layer with no raster signals → vector."""
        result = classify_layer_kind(
            {
                "name": "0",
                "title": "Wildfire Points",
                "geometry_type": "esriGeometryPoint",
            },
            adapter_type="arcgis",
        )
        assert result == "vector"

    def test_layerinfo_kind_defaults_to_vector(self):
        """D-09: LayerInfo Pydantic model default for kind is 'vector' (additive backward-compat)."""
        from app.modules.catalog.sources.schemas import LayerInfo

        layer = LayerInfo(name="test_layer")
        assert layer.kind == "vector"

    def test_layerinfo_kind_rejects_invalid_value(self):
        """D-09: LayerInfo.kind is a Literal — only 'vector' and 'raster' are valid."""
        from pydantic import ValidationError

        from app.modules.catalog.sources.schemas import LayerInfo

        with pytest.raises(ValidationError):
            LayerInfo(name="test_layer", kind="invalid")

    def test_non_image_link_type_is_vector(self):
        """D-09: Links with non-image/ type do not trigger raster classification."""
        result = classify_layer_kind(
            {
                "links": [
                    {"rel": "self", "type": "application/json"},
                    {"rel": "items", "type": "application/geo+json"},
                ]
            },
            adapter_type="ogcapi",
        )
        assert result == "vector"

    def test_links_not_a_list_is_handled_defensively(self):
        """D-09: classify_layer_kind handles malformed links defensively (not a list)."""
        # A malformed response with links as a dict instead of a list
        result = classify_layer_kind(
            {"links": {"rel": "self", "type": "image/png"}},
            adapter_type="ogcapi",
        )
        # links is not a list, so the image/* check is skipped → vector
        assert result == "vector"


class TestProbeOrchestratorNoEnrichment:
    """Verify detect_service_type no longer calls ogrinfo enrichment for OGC API / WFS.

    Phase 1057 PROBE-05 fix per D-04 (real root cause: per-layer ogrinfo, not orchestrator)
    and D-05 (drop enrichment from probe phase; lazy-enrich at preview time).
    """

    def _make_response(self, data: dict, url: str = "http://fake.example.com") -> "httpx.Response":
        """Build an httpx.Response with a request attached (required for raise_for_status)."""
        import httpx as _httpx

        request = _httpx.Request("GET", url)
        response = _httpx.Response(200, json=data, request=request)
        return response

    def _make_xml_response(self, xml_text: str, url: str = "http://fake.example.com") -> "httpx.Response":
        """Build an httpx.Response with XML content and a request attached."""
        import httpx as _httpx

        request = _httpx.Request("GET", url)
        response = _httpx.Response(
            200,
            text=xml_text,
            headers={"content-type": "text/xml"},
            request=request,
        )
        return response

    @pytest.mark.anyio
    async def test_ogcapi_probe_completes_fast_without_subprocess(self):
        """PROBE-05: 17-collection OGC API probe completes in <100ms with no subprocess.

        Stubs out HTTP calls so the test is pure in-process. Wall-clock assertion
        confirms no ogrinfo subprocess is invoked (which would add ~3-4s per layer).
        """
        import httpx
        from unittest.mock import AsyncMock, patch

        landing_page = {
            "conformsTo": [
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
            ],
            "links": [],
        }
        collections_data = {
            "collections": [
                {"id": f"layer_{i}", "title": f"Layer {i}"} for i in range(17)
            ]
        }

        # Patch httpx AsyncClient.get to return our stubs
        async def mock_get(url: str, **kwargs):
            if "collections" in url:
                return self._make_response(collections_data, url)
            return self._make_response(landing_page, url)

        with patch(
            "app.modules.catalog.sources.adapters.ogcapi.validate_url_for_ssrf",
            new_callable=AsyncMock,
        ):
            async with httpx.AsyncClient() as client:
                client.get = AsyncMock(side_effect=mock_get)

                from app.modules.catalog.sources.probe import detect_service_type

                start = time.perf_counter()
                result = await detect_service_type("http://fake-ogcapi.example.com", client)
                elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, (
            f"OGC API probe took {elapsed_ms:.1f}ms — expected <100ms. "
            "ogrinfo subprocess may have been invoked."
        )
        assert result.service_type == "OGC API Features"
        assert len(result.layers) == 17

    @pytest.mark.anyio
    async def test_ogcapi_probe_layers_have_null_geometry_and_count(self):
        """PROBE-05 + CLASS-07: OGC API probe layers have geometry_type=None, feature_count=None, kind='vector'."""
        import httpx
        from unittest.mock import AsyncMock, patch

        landing_page = {
            "conformsTo": [
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
            ],
        }
        collections_data = {
            "collections": [
                {"id": "lakes", "title": "Large Lakes"},
                {"id": "rivers", "title": "Natural Rivers"},
            ]
        }

        async def mock_get(url: str, **kwargs):
            if "collections" in url:
                return self._make_response(collections_data, url)
            return self._make_response(landing_page, url)

        with patch(
            "app.modules.catalog.sources.adapters.ogcapi.validate_url_for_ssrf",
            new_callable=AsyncMock,
        ):
            async with httpx.AsyncClient() as client:
                client.get = AsyncMock(side_effect=mock_get)

                from app.modules.catalog.sources.probe import detect_service_type

                result = await detect_service_type("http://fake-ogcapi.example.com", client)

        for layer in result.layers:
            assert layer.geometry_type is None, f"Expected geometry_type=None for {layer.name}"
            assert layer.feature_count is None, f"Expected feature_count=None for {layer.name}"
            assert layer.kind == "vector", f"Expected kind='vector' for {layer.name}"

    @pytest.mark.anyio
    async def test_wfs_probe_layers_have_null_geometry_and_count_with_vector_kind(self):
        """PROBE-05 + CLASS-07: WFS probe layers have geometry_type=None, feature_count=None, kind='vector'."""
        import httpx
        from unittest.mock import AsyncMock

        capabilities_xml = """<?xml version="1.0" encoding="UTF-8"?>
<WFS_Capabilities version="2.0.0" xmlns="http://www.opengis.net/wfs/2.0">
  <FeatureTypeList>
    <FeatureType>
      <Name>topp:countries</Name>
      <Title>Countries of the World</Title>
      <DefaultCRS>EPSG:4326</DefaultCRS>
    </FeatureType>
    <FeatureType>
      <Name>topp:rivers</Name>
      <Title>Major Rivers</Title>
      <DefaultCRS>EPSG:4326</DefaultCRS>
    </FeatureType>
  </FeatureTypeList>
</WFS_Capabilities>"""

        async with httpx.AsyncClient() as client:
            client.get = AsyncMock(
                return_value=self._make_xml_response(
                    capabilities_xml, "http://fake-wfs.example.com/wfs"
                )
            )

            from app.modules.catalog.sources.probe import detect_service_type

            # Use a WFS-looking URL so the fast path is taken
            result = await detect_service_type(
                "http://fake-wfs.example.com/wfs", client
            )

        assert result.service_type.startswith("WFS")
        for layer in result.layers:
            assert layer.geometry_type is None, f"Expected geometry_type=None for {layer.name}"
            assert layer.feature_count is None, f"Expected feature_count=None for {layer.name}"
            assert layer.kind == "vector", f"Expected kind='vector' for {layer.name}"

    @pytest.mark.anyio
    async def test_enrich_ogcapi_layers_not_called(self):
        """PROBE-05 D-05: detect_service_type must NOT call enrich_ogcapi_layers.

        Verifies by structural assertion: enrich_ogcapi_layers is not importable
        from probe.py (it was deleted). If the function exists in the probe module
        namespace it would be patchable; its absence confirms D-05 compliance.
        """
        import app.modules.catalog.sources.probe as probe_module

        assert not hasattr(probe_module, "enrich_ogcapi_layers"), (
            "enrich_ogcapi_layers should not exist in probe.py namespace "
            "(Phase 1057 D-05: deleted from probe phase)"
        )

    @pytest.mark.anyio
    async def test_enrich_arcgis_feature_counts_still_called(self):
        """PROBE-05 D-05: ArcGIS enrichment (HTTP-based, fast) is preserved — not dropped."""
        import httpx
        from unittest.mock import AsyncMock, patch

        arcgis_service_json = {
            "currentVersion": 10.9,
            "serviceDescription": "Test ArcGIS Feature Service",
            "layers": [
                {"id": 0, "name": "Wildfire Points", "type": "Feature Layer"}
            ],
        }

        async def mock_get(url: str, **kwargs):
            return self._make_response(arcgis_service_json, url)

        async with httpx.AsyncClient() as client:
            client.get = AsyncMock(side_effect=mock_get)

            with patch(
                "app.modules.catalog.sources.probe.enrich_arcgis_feature_counts",
                new_callable=AsyncMock,
            ) as mock_arcgis_enrich:
                mock_arcgis_enrich.return_value = [
                    {
                        "name": "Wildfire Points",
                        "title": "Wildfire Points",
                        "geometry_type": "esriGeometryPoint",
                        "feature_count": 49,
                        "type": "layer",
                        "id": 0,
                        "object_id_field": "OBJECTID",
                    }
                ]

                from app.modules.catalog.sources.probe import detect_service_type

                result = await detect_service_type(
                    "https://services.arcgis.com/rest/services/Wildfire/FeatureServer",
                    client,
                )

            mock_arcgis_enrich.assert_called_once()
