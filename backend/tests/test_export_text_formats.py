"""GeoJSON and CSV exports: collection name, coordinate columns and gzip."""

import csv
import gzip
import io
import json
import os
import shutil
import tempfile
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.processing.export import artifact_cache
from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id


async def _make_table(session, geom_type: str, srid: int, rows: list[tuple]) -> str:  # noqa: E501
    """A GeoLens-shaped table: ``geom`` in ``srid`` plus a generated ``geom_4326``."""
    table = f"exp_gl_{uuid.uuid4().hex[:12]}"
    # An untyped column holds every dimension (Z, M, ZM).
    typmod = "" if geom_type == "Geometry" else f"({geom_type}, {{srid}})"
    await session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, name varchar, "
            f"geom geometry{typmod.format(srid=srid)}, "
            f"geom_4326 geometry{typmod.format(srid=4326)} "
            "GENERATED ALWAYS AS (ST_Transform(geom, 4326)) STORED)"
        )
    )
    for name, wkt in rows:
        await session.execute(
            text(
                f"INSERT INTO data.{table} (name, geom) VALUES "
                f"(:name, CASE WHEN CAST(:wkt AS text) IS NULL THEN NULL "
                f"ELSE ST_Transform(ST_GeomFromText(:wkt, 4326), {srid}) END)"
            ),
            {"name": name, "wkt": wkt},
        )
    await session.commit()
    return table


async def _drop_table(session, table: str) -> None:
    await session.rollback()
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await session.commit()


@pytest.mark.requires_ogr2ogr
@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not available")
class TestGeojsonNameEndToEnd:
    @pytest.mark.anyio
    @pytest.mark.parametrize("title", ["Seed sites", 'Café du Nord – 東京 "quoted"'])
    async def test_collection_name_is_the_dataset_title(
        self, test_db_session, monkeypatch, tmp_path, title
    ):
        from app.processing.export import service as export_service

        monkeypatch.setattr(
            export_service.settings, "upload_staging_dir", str(tmp_path)
        )
        table = await _make_table(
            test_db_session, "Point", 4326, [("a", "POINT (1 2)")]
        )
        try:
            path, _name, _media = await export_service.export_dataset(
                table, title, "geojson", schema="data"
            )
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        finally:
            await _drop_table(test_db_session, table)
        assert document["name"] == title


@pytest.mark.requires_ogr2ogr
@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not available")
class TestCsvCoordinatesEndToEnd:
    _ROWS = [
        ("single", "MULTIPOINT ((-74.5 41.25))"),
        ("pair", "MULTIPOINT ((1 2), (3 4))"),
        ("none", None),
    ]

    async def _export(self, session, monkeypatch, tmp_path, **kwargs):
        from app.processing.export import service as export_service

        monkeypatch.setattr(
            export_service.settings, "upload_staging_dir", str(tmp_path)
        )
        table = await _make_table(session, "MultiPoint", 3857, self._ROWS)
        try:
            path, _name, _media = await export_service.export_dataset(
                table, "Seeds", "csv", schema="data", **kwargs
            )
            with open(path, newline="", encoding="utf-8") as handle:
                return list(csv.reader(handle))
        finally:
            await _drop_table(session, table)

    @pytest.mark.anyio
    @pytest.mark.parametrize("target_srs", [None, "EPSG:3857"])
    async def test_xy_adds_wgs84_columns_after_the_geometry(
        self, test_db_session, monkeypatch, tmp_path, target_srs
    ):
        rows = await self._export(
            test_db_session, monkeypatch, tmp_path, xy=True, target_srs=target_srs
        )
        header = rows[0]
        body = {row[header.index("name")]: row for row in rows[1:]}
        assert "gid" not in header
        lon, lat = header.index("longitude"), header.index("latitude")
        assert lat == lon + 1
        assert "geom" in header[0].lower() or "wkt" in header[0].lower()
        assert header[lon + 2] == "name"
        assert float(body["single"][lon]) == pytest.approx(-74.5)
        assert float(body["single"][lat]) == pytest.approx(41.25)
        assert body["pair"][lon] == body["pair"][lat] == ""
        assert body["none"][lon] == body["none"][lat] == ""

    @pytest.mark.anyio
    async def test_without_xy_the_columns_are_absent(
        self, test_db_session, monkeypatch, tmp_path
    ):
        rows = await self._export(test_db_session, monkeypatch, tmp_path)
        assert "longitude" not in rows[0] and "latitude" not in rows[0]
        assert "name" in rows[0] and "gid" not in rows[0]


@pytest.mark.requires_ogr2ogr
@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not available")
class TestCsvCoordinatesFilters:
    async def _run(self, session, monkeypatch, tmp_path, geom_type, srid, rows, **kw):
        from app.processing.export import service as export_service

        monkeypatch.setattr(
            export_service.settings, "upload_staging_dir", str(tmp_path)
        )
        table = await _make_table(session, geom_type, srid, rows)
        try:
            path, _n, _m = await export_service.export_dataset(
                table,
                "Seeds",
                "csv",
                schema="data",
                xy=True,
                column_info=[{"name": "name", "type": "text"}],
                **kw,
            )
            with open(path, newline="", encoding="utf-8") as handle:
                data = list(csv.reader(handle))
        finally:
            await _drop_table(session, table)
        header = data[0]
        return {
            row[header.index("name")]: (
                row[header.index("longitude")],
                row[header.index("latitude")],
            )
            for row in data[1:]
        }

    _PTS = [
        ("in", "POINT (-75 40)"),
        ("out", "POINT (10 10)"),
        ("east", "POINT (179 0)"),
        ("west", "POINT (-179 0)"),
    ]

    @pytest.mark.anyio
    @pytest.mark.parametrize("srid", [4326, 3857])
    async def test_ordinary_bbox(self, test_db_session, monkeypatch, tmp_path, srid):
        got = await self._run(
            test_db_session,
            monkeypatch,
            tmp_path,
            "Point",
            srid,
            self._PTS,
            bbox=[-80, 30, -70, 50],
        )
        assert set(got) == {"in"}
        assert float(got["in"][0]) == pytest.approx(-75)

    @pytest.mark.anyio
    async def test_antimeridian_bbox(self, test_db_session, monkeypatch, tmp_path):
        got = await self._run(
            test_db_session,
            monkeypatch,
            tmp_path,
            "Point",
            4326,
            self._PTS,
            bbox=[170, -10, -170, 10],
        )
        assert set(got) == {"east", "west"}

    @pytest.mark.anyio
    async def test_bbox_with_where(self, test_db_session, monkeypatch, tmp_path):
        got = await self._run(
            test_db_session,
            monkeypatch,
            tmp_path,
            "Point",
            3857,
            self._PTS,
            bbox=[-180, -90, 180, 90],
            where="name = 'in'",
        )
        assert set(got) == {"in"}

    @pytest.mark.anyio
    async def test_every_point_dimension(self, test_db_session, monkeypatch, tmp_path):
        rows = [
            ("xy", "POINT (1 2)"),
            ("xyz", "POINT Z (1 2 3)"),
            ("xym", "POINT M (1 2 3)"),
            ("xyzm", "POINT ZM (1 2 3 4)"),
            ("mxyz", "MULTIPOINT Z ((1 2 3))"),
            ("mxym", "MULTIPOINT M ((1 2 3))"),
            ("mxyzm", "MULTIPOINT ZM ((1 2 3 4))"),
            ("empty", "POINT EMPTY"),
            ("null", None),
        ]
        got = await self._run(
            test_db_session, monkeypatch, tmp_path, "Geometry", 4326, rows
        )
        for name in ("xy", "xyz", "xym", "xyzm", "mxyz", "mxym", "mxyzm"):
            assert (float(got[name][0]), float(got[name][1])) == (1.0, 2.0), name
        assert got["empty"] == ("", "") and got["null"] == ("", "")


class TestSelectionKey:
    def test_xy_never_shares_an_artifact_with_the_plain_export(self):
        args = dict(
            dataset_id=uuid.uuid4(),
            table_name="t",
            dataset_title="T",
            tile_cache_version=1,
            format_key="csv",
            target_crs=None,
            bbox=None,
            where=None,
            exporter_version="1",
        )
        plain = artifact_cache.selection_key(**args)
        assert artifact_cache.selection_key(**args, xy=False) == plain
        assert artifact_cache.selection_key(**args, xy=True) != plain


class _Recorder:
    """Stands in for the conversion; records its kwargs and writes a fixed body."""

    def __init__(self, root: str, body: bytes) -> None:
        self.root = root
        self.body = body
        self.calls: list[dict] = []

    async def __call__(self, table_name, dataset_name, format_key, **kwargs):
        self.calls.append({"format_key": format_key, **kwargs})
        fmt = FORMAT_MAP[format_key]
        directory = os.path.join(self.root, uuid.uuid4().hex)
        os.makedirs(directory)
        filename = f"{dataset_name}{fmt['ext']}"
        path = os.path.join(directory, filename)
        with open(path, "wb") as handle:
            handle.write(self.body)
        return path, filename, fmt["media"]


@pytest.fixture
def recorder(monkeypatch):
    root = tempfile.mkdtemp(prefix="test_export_text_")
    stub = _Recorder(root, b'{"type":"FeatureCollection","features":[]}\n' * 200)
    monkeypatch.setattr("app.processing.export.selection.export_dataset", stub)
    monkeypatch.setattr(artifact_cache, "_ttl_seconds", lambda: 600)
    yield stub
    shutil.rmtree(root, ignore_errors=True)


def _vary_tokens(response) -> set[str]:
    return {
        token.strip().lower()
        for line in response.headers.get_list("vary")
        for token in line.split(",")
    }


async def _dataset(session, name: str, **kwargs):
    user_id = await get_user_id(session, "admin")
    return await create_dataset(
        session,
        created_by=user_id,
        name=name,
        theme_category=[],
        visibility="public",
        record_type="vector_dataset",
        **kwargs,
    )


class TestXyParameterGate:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("geometry_type", "columns", "fmt", "expected"),
        [
            ("POINT", [{"name": "name", "type": "text"}], "csv", True),
            ("MULTIPOINT", [{"name": "name", "type": "text"}], "csv", True),
            ("POLYGON", [{"name": "name", "type": "text"}], "csv", False),
            (
                "POINT",
                [{"name": "Longitude", "type": "double precision"}],
                "csv",
                False,
            ),
            ("POINT", [{"name": "name", "type": "text"}], "geojson", False),
        ],
    )
    async def test_xy_reaches_the_conversion_only_when_it_applies(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        recorder,
        geometry_type,
        columns,
        fmt,
        expected,
    ):
        dataset = await _dataset(
            test_db_session,
            f"Xy {geometry_type} {fmt} {expected}",
            geometry_type=geometry_type,
            column_info=columns,
        )
        response = await client.get(
            f"/datasets/{dataset.id}/export?format={fmt}&xy=true",
            headers=admin_auth_header,
        )
        assert response.status_code == 200, response.text
        assert recorder.calls[0].get("xy", False) is expected


class TestGzipRepresentation:
    @pytest.fixture
    async def dataset(self, test_db_session, recorder):
        return await _dataset(
            test_db_session,
            "Gzip Source",
            geometry_type="POINT",
            column_info=[{"name": "name", "type": "text"}],
        )

    @staticmethod
    def _url(dataset, fmt="geojson") -> str:
        return f"/datasets/{dataset.id}/export?format={fmt}"

    @pytest.mark.anyio
    @pytest.mark.parametrize("warm", [False, True])
    async def test_gzip_offer_gets_a_gzip_body_under_its_own_tag(
        self, client, admin_auth_header, dataset, recorder, warm
    ):
        url = self._url(dataset)
        plain_headers = {**admin_auth_header, "Accept-Encoding": "identity"}
        if warm:
            await client.get(url, headers=plain_headers)
        zipped = await client.get(
            url, headers={**admin_auth_header, "Accept-Encoding": "gzip, br"}
        )
        assert zipped.headers["content-encoding"] == "gzip"
        assert zipped.content == recorder.body
        assert "accept-encoding" in _vary_tokens(zipped)
        assert zipped.headers["accept-ranges"] == "none"

        plain = await client.get(url, headers=plain_headers)
        assert "content-encoding" not in plain.headers
        assert plain.content == recorder.body
        assert "accept-encoding" in _vary_tokens(plain)
        assert plain.headers["etag"] != zipped.headers["etag"]
        assert zipped.headers["etag"].startswith("W/")

    @pytest.mark.anyio
    async def test_gzip_bytes_are_gzip(
        self, client, admin_auth_header, dataset, recorder
    ):
        async with client.stream(
            "GET",
            self._url(dataset),
            headers={**admin_auth_header, "Accept-Encoding": "gzip"},
        ) as response:
            raw = b"".join([chunk async for chunk in response.aiter_raw()])
        assert gzip.GzipFile(fileobj=io.BytesIO(raw)).read() == recorder.body
        assert len(raw) < len(recorder.body)

    @pytest.mark.anyio
    @pytest.mark.parametrize("warm", [False, True])
    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    @pytest.mark.parametrize("holds", ["identity", "gzip"])
    async def test_a_tag_of_the_other_representation_gets_the_body(
        self, client, admin_auth_header, dataset, warm, method, holds
    ):
        url = self._url(dataset)
        identity = {**admin_auth_header, "Accept-Encoding": "identity"}
        zipped = {**admin_auth_header, "Accept-Encoding": "gzip"}
        if warm:
            await client.get(url, headers=identity)
        held = await client.get(
            url, headers=identity if holds == "identity" else zipped
        )
        asks = zipped if holds == "identity" else identity
        other = await client.request(
            method, url, headers={**asks, "If-None-Match": held.headers["etag"]}
        )
        assert other.status_code == 200
        same = await client.request(
            method,
            url,
            headers={
                **(identity if holds == "identity" else zipped),
                "If-None-Match": held.headers["etag"],
            },
        )
        assert same.status_code == 304
        assert same.headers["etag"] == held.headers["etag"]
        assert "accept-encoding" in _vary_tokens(same)

    @pytest.mark.anyio
    async def test_if_match_gets_the_identity_representation(
        self, client, admin_auth_header, dataset
    ):
        url = self._url(dataset)
        identity = await client.get(
            url, headers={**admin_auth_header, "Accept-Encoding": "identity"}
        )
        response = await client.get(
            url,
            headers={
                **admin_auth_header,
                "Accept-Encoding": "gzip",
                "If-Match": identity.headers["etag"],
            },
        )
        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.headers["etag"] == identity.headers["etag"]

    @pytest.mark.anyio
    async def test_range_gets_identity_bytes(
        self, client, admin_auth_header, dataset, recorder
    ):
        url = self._url(dataset)
        await client.get(url, headers={**admin_auth_header, "Accept-Encoding": "gzip"})
        sliced = await client.get(
            url,
            headers={
                **admin_auth_header,
                "Accept-Encoding": "gzip",
                "Range": "bytes=0-9",
            },
        )
        assert sliced.status_code == 206
        assert "content-encoding" not in sliced.headers
        assert sliced.content == recorder.body[:10]
        assert sliced.headers["content-range"] == f"bytes 0-9/{len(recorder.body)}"
        assert "accept-encoding" in _vary_tokens(sliced)

    @pytest.mark.anyio
    @pytest.mark.parametrize("warm", [False, True])
    async def test_head_agrees_with_get(self, client, admin_auth_header, dataset, warm):
        url = self._url(dataset)
        if warm:
            await client.get(url, headers=admin_auth_header)
        for encoding in ("gzip", "identity"):
            headers = {**admin_auth_header, "Accept-Encoding": encoding}
            head = await client.head(url, headers=headers)
            get = await client.get(url, headers=headers)
            for name in ("content-encoding", "accept-ranges"):
                assert head.headers.get(name) == get.headers.get(name), name
            assert _vary_tokens(head) == _vary_tokens(get)
            assert "accept-encoding" in _vary_tokens(head)
            if warm:
                assert head.headers["etag"] == get.headers["etag"]

    @pytest.mark.anyio
    @pytest.mark.parametrize("offer", ["gzip;q=0", "br, deflate", "identity"])
    async def test_no_gzip_offer_stays_identity(
        self, client, admin_auth_header, dataset, offer
    ):
        response = await client.get(
            self._url(dataset),
            headers={**admin_auth_header, "Accept-Encoding": offer},
        )
        assert "content-encoding" not in response.headers
        assert response.headers["content-length"]

    @pytest.mark.anyio
    async def test_csv_is_compressed_and_gpkg_is_not(
        self, client, admin_auth_header, dataset, recorder
    ):
        headers = {**admin_auth_header, "Accept-Encoding": "gzip"}
        csv_response = await client.get(self._url(dataset, "csv"), headers=headers)
        gpkg_response = await client.get(self._url(dataset, "gpkg"), headers=headers)
        assert csv_response.headers["content-encoding"] == "gzip"
        assert "content-encoding" not in gpkg_response.headers
