"""GDAL reading a local upload sends no HTTP request, whatever URL the file names."""

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import threading
import zipfile

import pytest

from app.platform.gdal_env import gdal_vector_safe_env
from app.processing.ingest.gdal_drivers import local_input_driver_args
from app.processing.ingest.ogr import _resolve_source_path, run_ogrinfo

pytestmark = pytest.mark.skipif(
    shutil.which("ogrinfo") is None or shutil.which("ogr2ogr") is None,
    reason="needs the GDAL command line tools",
)


class _Listener:
    """A loopback HTTP server that records every request line it receives."""

    def __init__(self):
        self.hits: list[str] = []
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _record(self):
                listener.hits.append(self.requestline)
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_HEAD = do_POST = do_CONNECT = _record  # noqa: N815

            def log_message(self, *args):
                pass

        socketserver.TCPServer.allow_reuse_address = True
        self._server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def listener(monkeypatch):
    """The listener, with the parent environment routing GDAL to it either way.

    An inherited proxy points at the listener and ``NO_PROXY`` exempts it, so a
    request GDAL makes reaches it directly or through the proxy, and counts.
    """
    server = _Listener()
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(key, server.url)
    monkeypatch.setenv("GDAL_HTTP_PROXY", server.url)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    try:
        yield server
    finally:
        server.close()


def _geojson(crs_type: str, href: str) -> str:
    key = "url" if crs_type == "url" else "href"
    return json.dumps(
        {
            "type": "FeatureCollection",
            "crs": {"type": crs_type, "properties": {key: href, "type": "proj4"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"a": 1},
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                }
            ],
        }
    )


_GML = """<?xml version="1.0" encoding="UTF-8"?>
<ogr:FeatureCollection xmlns:ogr="http://ogr.maptools.org/"
    xmlns:gml="http://www.opengis.net/gml"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://ogr.maptools.org/ upload.xsd">
  <gml:featureMember>
    <ogr:probe fid="probe.0">
      <ogr:geometryProperty><gml:Point><gml:coordinates>1,2</gml:coordinates></gml:Point></ogr:geometryProperty>
      <ogr:a>1</ogr:a>
    </ogr:probe>
  </gml:featureMember>
</ogr:FeatureCollection>
"""

_XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:ogr="http://ogr.maptools.org/" xmlns:gml="http://www.opengis.net/gml"
    targetNamespace="http://ogr.maptools.org/" elementFormDefault="qualified">
  <xs:include schemaLocation="{href}"/>
  <xs:element name="probe" type="ogr:probe_Type" substitutionGroup="gml:_Feature"/>
  <xs:complexType name="probe_Type">
    <xs:complexContent><xs:extension base="gml:AbstractFeatureType"><xs:sequence>
      <xs:element name="geometryProperty" type="gml:PointPropertyType"/>
      <xs:element name="a" type="xs:integer"/>
    </xs:sequence></xs:extension></xs:complexContent>
  </xs:complexType>
</xs:schema>
"""


def _upload(tmp_path, kind: str, base: str) -> str:
    """A staged upload of ``kind`` that names a URL under ``base``."""
    if kind in ("link", "url"):
        path = tmp_path / "upload.geojson"
        path.write_text(_geojson(kind, f"{base}/crs-{kind}"))
    elif kind == "zip-member":
        path = tmp_path / "upload.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("inner.geojson", _geojson("link", f"{base}/crs-member"))
    else:
        path = tmp_path / "upload.gml"
        path.write_text(_GML)
        (tmp_path / "upload.xsd").write_text(_XSD.format(href=f"{base}/include.xsd"))
    return str(path)


def _ogr2ogr(path: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """ogr2ogr with the argv shape the ingest uses, to a throwaway output."""
    return subprocess.run(
        [
            "ogr2ogr",
            "-f",
            "GeoJSON",
            "/vsistdout/",
            *local_input_driver_args(path),
            _resolve_source_path(path),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


_KINDS = ["link", "url", "zip-member", "gml-include"]


@pytest.mark.parametrize("kind", _KINDS)
def test_the_driver_allowlist_alone_lets_the_request_out(tmp_path, listener, kind):
    """The control: without the env clamp the file does reach the listener."""
    path = _upload(tmp_path, kind, listener.url)
    env = {**os.environ}
    env.pop("GDAL_SKIP", None)
    _ogr2ogr(path, env)
    assert listener.hits, (
        "the request this file guards against did not happen, so a pass below "
        "would prove nothing"
    )


@pytest.mark.parametrize("kind", _KINDS)
def test_ingest_ogr2ogr_sends_no_request(tmp_path, listener, kind):
    path = _upload(tmp_path, kind, listener.url)
    result = _ogr2ogr(path, gdal_vector_safe_env())
    assert listener.hits == []
    assert result.returncode == 0, result.stderr


@pytest.mark.anyio
@pytest.mark.parametrize("kind", _KINDS)
async def test_upload_preview_sends_no_request(tmp_path, listener, kind):
    path = _upload(tmp_path, kind, listener.url)
    await run_ogrinfo(path)
    assert listener.hits == []


def test_a_gdal_config_file_cannot_switch_it_back_on(tmp_path, listener, monkeypatch):
    """A config file that tells GDAL to ignore the environment isn't read."""
    rc = tmp_path / "gdalrc"
    rc.write_text("[directives]\nignore-env-vars=yes\n")
    monkeypatch.setenv("GDAL_CONFIG_FILE", str(rc))
    path = _upload(tmp_path, "link", listener.url)
    _ogr2ogr(path, gdal_vector_safe_env())
    assert listener.hits == []
