"""A WFS service preview reads one page of the layer and stays inside its time budget."""

import asyncio
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.modules.catalog.sources import preview
from app.modules.catalog.sources.preview import (
    ServicePreviewTimeoutError,
    run_service_preview,
)
from app.platform import egress_proxy

pytestmark = pytest.mark.anyio


class _AnsweringOgrinfo:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b'{"layers": []}', b""


async def _preview_argv(monkeypatch, gdal_source: str) -> list[str]:
    """The ogrinfo argv `run_service_preview` spawns for ``gdal_source``."""
    seen: list[str] = []

    async def spawn(*argv, **_kwargs):
        seen.extend(argv)
        return _AnsweringOgrinfo()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(preview, "recognise_esri_oapif", AsyncMock(return_value=None))
    await run_service_preview(gdal_source, "layer")
    return seen


@pytest.mark.parametrize(
    "gdal_source",
    [
        "OAPIF:https://example.test/ogc",
        "ESRIJSON:https://example.test/arcgis/rest/services/x/FeatureServer/0/query",
    ],
)
async def test_non_wfs_preview_argv_is_unchanged(monkeypatch, gdal_source):
    """Only a WFS source drops the extent; other sources keep their argv."""
    assert await _preview_argv(monkeypatch, gdal_source) == [
        "ogrinfo",
        "-json",
        "-features",
        "-limit",
        "5",
        "--config",
        "GDAL_HTTP_TIMEOUT",
        "60",
        gdal_source,
        "layer",
    ]


async def test_wfs_preview_argv_asks_for_no_extent(monkeypatch):
    """A WFS preview passes -noextent, so ogrinfo never pages the layer for one."""
    assert await _preview_argv(monkeypatch, "WFS:https://example.test/wfs") == [
        "ogrinfo",
        "-json",
        "-features",
        "-limit",
        "5",
        "-noextent",
        "--config",
        "GDAL_HTTP_TIMEOUT",
        "60",
        "WFS:https://example.test/wfs",
        "layer",
    ]


class _SilentOgrinfo:
    returncode: int | None = None

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return -9


async def test_a_preview_timeout_raises_the_timeout_error(monkeypatch):
    """ogrinfo outliving the budget raises ServicePreviewTimeoutError."""

    async def spawn(*_args, **_kwargs):
        return _SilentOgrinfo()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(preview, "_SUBPROCESS_FLOOR_SECONDS", 0.05)

    with pytest.raises(ServicePreviewTimeoutError):
        await run_service_preview(
            "WFS:https://wfs.example.test/ows", "layer", timeout=0.05
        )


def _ogrinfo_takes_noextent() -> bool:
    if shutil.which("ogrinfo") is None:
        return False
    out = subprocess.run(
        ["ogrinfo", "--version"], capture_output=True, text=True, check=False
    ).stdout
    match = re.search(r"GDAL (\d+)\.(\d+)", out)
    return bool(match) and (int(match[1]), int(match[2])) >= (3, 9)


needs_ogrinfo = pytest.mark.skipif(
    not _ogrinfo_takes_noextent(), reason="needs ogrinfo -limit (GDAL 3.9+)"
)

_HOST = "wfs.example.test"
_LAYER = "app:parcels"
_TOTAL = 1000

_CAPABILITIES = """<?xml version="1.0" encoding="UTF-8"?>
<wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1">
 <ows:OperationsMetadata>
  <ows:Constraint name="ImplementsResultPaging">
   <ows:NoValues/><ows:DefaultValue>TRUE</ows:DefaultValue>
  </ows:Constraint>
 </ows:OperationsMetadata>
 <wfs:FeatureTypeList><wfs:FeatureType>
  <wfs:Name xmlns:app="http://example.test/app">app:parcels</wfs:Name>
  <wfs:Title>Parcels</wfs:Title>
  <wfs:DefaultCRS>urn:ogc:def:crs:EPSG::28992</wfs:DefaultCRS>
  <ows:WGS84BoundingBox><ows:LowerCorner>3 50</ows:LowerCorner>
  <ows:UpperCorner>7 54</ows:UpperCorner></ows:WGS84BoundingBox>
 </wfs:FeatureType></wfs:FeatureTypeList>
</wfs:WFS_Capabilities>"""

_SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:app="http://example.test/app"
 targetNamespace="http://example.test/app" elementFormDefault="qualified">
 <xsd:import namespace="http://www.opengis.net/gml/3.2"
  schemaLocation="http://schemas.opengis.net/gml/3.2.1/gml.xsd"/>
 <xsd:element name="parcels" type="app:parcelsType"
  substitutionGroup="gml:AbstractFeature"/>
 <xsd:complexType name="parcelsType"><xsd:complexContent>
  <xsd:extension base="gml:AbstractFeatureType"><xsd:sequence>
   <xsd:element name="name" type="xsd:string" minOccurs="0"/>
   <xsd:element name="geom" type="gml:PointPropertyType" minOccurs="0"/>
  </xsd:sequence></xsd:extension>
 </xsd:complexContent></xsd:complexType>
</xsd:schema>"""

_MEMBER = """ <wfs:member><app:parcels gml:id="parcels.{n}"><app:name>p{n}</app:name>
  <app:geom><gml:Point srsName="urn:ogc:def:crs:EPSG::28992">
  <gml:pos>{x} 450000</gml:pos></gml:Point></app:geom>
 </app:parcels></wfs:member>"""

_HITS = f"""<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
 numberMatched="{_TOTAL}" numberReturned="0"/>"""


def _page(start: int, count: int) -> str:
    numbers = range(start, min(start + count, _TOTAL))
    members = "\n".join(_MEMBER.format(n=n, x=100000 + n) for n in numbers)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
        'xmlns:gml="http://www.opengis.net/gml/3.2" '
        'xmlns:app="http://example.test/app" '
        f'numberMatched="{_TOTAL}" numberReturned="{len(numbers)}">\n'
        f"{members}\n</wfs:FeatureCollection>"
    )


@contextmanager
def _paged_wfs() -> Iterator[tuple[int, list[dict[str, str]]]]:
    """A paging WFS 2.0 service on loopback; yields its port and its GetFeature params."""
    get_features: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            query = parse_qs(urlsplit(self.path).query)
            params = {key.lower(): values[0] for key, values in query.items()}
            operation = params.get("request", "").lower()
            if operation == "getcapabilities":
                body = _CAPABILITIES
            elif operation == "describefeaturetype":
                body = _SCHEMA
            elif operation == "getfeature":
                get_features.append(params)
                if params.get("resulttype", "").lower() == "hits":
                    body = _HITS
                else:
                    body = _page(
                        int(params.get("startindex", 0)),
                        int(params.get("count", _TOTAL)),
                    )
            else:
                self.send_error(400)
                return
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, get_features
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@needs_ogrinfo
async def test_a_wfs_preview_reads_one_page_and_counts_by_hits(monkeypatch):
    """A layer of many pages previews from its first page; the count comes from hits."""
    real = egress_proxy._resolve_all_and_validate

    async def resolve(host: str, port: int | None) -> list[str]:
        if host == _HOST:
            return ["127.0.0.1"]
        return await real(host, port)

    monkeypatch.setattr(egress_proxy, "_resolve_all_and_validate", resolve)

    with _paged_wfs() as (port, get_features):
        result = await run_service_preview(
            f"WFS:http://{_HOST}:{port}/wfs", _LAYER, timeout=60.0
        )

    assert [row["name"] for row in result["sample_rows"]] == [
        "p0",
        "p1",
        "p2",
        "p3",
        "p4",
    ]
    assert result["feature_count"] == _TOTAL
    pages = {
        params.get("startindex")
        for params in get_features
        if params.get("resulttype", "").lower() != "hits"
    }
    assert pages == {"0"}
