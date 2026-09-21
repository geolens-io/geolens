"""Real GDAL proof that ArcGIS object IDs survive staged GeoJSON transport."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.catalog.sources.preview import build_gdal_source
from app.platform.gdal_env import gdal_service_safe_env

pytestmark = pytest.mark.anyio


_SOURCE_IDS = (7, 9_223_372_036_854_775_000)


@contextmanager
def _arcgis_fixture_server(
    source_ids: tuple[int, ...] = _SOURCE_IDS,
) -> Iterator[tuple[str, list[tuple[int, ...]]]]:
    """Serve only the query responses the ESRIJSON GDAL driver needs."""
    requests: list[tuple[int, ...]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            parsed = urlparse(self.path)
            if parsed.path != "/FeatureServer/0/query":
                self.send_error(404)
                return
            values = parse_qs(parsed.query).get("objectIds", [""])[0]
            requested = tuple(int(value) for value in values.split(",") if value)
            requests.append(requested)
            features = [
                {
                    "attributes": {
                        "OBJECTID": source_id,
                        "average": 97.0,
                        "name": f"row-{source_id}",
                    },
                    "geometry": {"x": float(index), "y": float(index)},
                }
                for index, source_id in enumerate(source_ids)
                if source_id in requested
            ]
            if parse_qs(parsed.query).get("f") == ["geojson"]:
                payload = {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": feature["attributes"],
                            "geometry": {
                                "type": "Point",
                                "coordinates": [
                                    feature["geometry"]["x"],
                                    feature["geometry"]["y"],
                                ],
                            },
                        }
                        for feature in features
                    ],
                }
            else:
                payload = {
                    "objectIdFieldName": "OBJECTID",
                    "geometryType": "esriGeometryPoint",
                    "spatialReference": {"wkid": 4326},
                    "fields": [
                        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                        {"name": "average", "type": "esriFieldTypeDouble"},
                        {"name": "name", "type": "esriFieldTypeString"},
                    ],
                    "features": features,
                }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/FeatureServer", requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


async def test_gdal_preserves_sparse_64_bit_arcgis_object_ids(tmp_path) -> None:
    """GDAL preserves the source OID attribute used by staged coverage checks."""
    output_path = tmp_path / "arcgis-ids.geojson"
    with _arcgis_fixture_server() as (base_url, requests):
        gdal_source, layer_name = build_gdal_source(
            "ArcGIS FeatureServer",
            base_url,
            "",
            "0",
            order_field="OBJECTID",
            object_ids=_SOURCE_IDS,
        )
        assert gdal_source.startswith("GeoJSON:")
        process = await asyncio.create_subprocess_exec(
            "ogr2ogr",
            "-f",
            "GeoJSON",
            str(output_path),
            gdal_source,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=gdal_service_safe_env(),
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        assert process.returncode == 0, stderr.decode()
        assert requests == [tuple(_SOURCE_IDS)]

    output = json.loads(output_path.read_text())
    staged_ids = sorted(
        feature["properties"]["OBJECTID"] for feature in output["features"]
    )
    assert staged_ids == list(_SOURCE_IDS)


async def test_gdal_keeps_arcgis_declared_float_fields_for_32_bit_ids(tmp_path) -> None:
    """ESRIJSON avoids turning an all-integral Double column into Integer."""
    source_ids = (7, 8)
    output_path = tmp_path / "arcgis-types.geojson"
    with _arcgis_fixture_server(source_ids) as (base_url, requests):
        gdal_source, layer_name = build_gdal_source(
            "ArcGIS FeatureServer",
            base_url,
            "",
            "0",
            order_field="OBJECTID",
            object_ids=source_ids,
        )
        assert gdal_source.startswith("ESRIJSON:")
        process = await asyncio.create_subprocess_exec(
            "ogr2ogr",
            "-f",
            "GeoJSON",
            str(output_path),
            gdal_source,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=gdal_service_safe_env(),
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        assert process.returncode == 0, stderr.decode()
        assert requests == [source_ids]

    output = json.loads(output_path.read_text())
    assert all(
        isinstance(feature["properties"]["average"], float)
        for feature in output["features"]
    )
