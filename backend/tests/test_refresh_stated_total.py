"""OGC API Features and WFS refreshes are held to the total the service states."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from app.platform.service_items import materialise_oapif_items
from app.processing.ingest.ogr import WfsCountMismatchError, run_ogr2ogr_service
from app.processing.ingest.tasks_reupload import reupload_service

from tests.factories import create_dataset, get_user_id
from tests.test_esri_ogc_features import (
    _OTHER_WFS,
    _SERVICE,
    _counting_only,
    _credential_line,
    _esri,
    _serve,
    _spawn_reading_the_source,
    _three_esri_pages,
)
from tests.test_refresh_gate_1269 import _dispatch_harness, _runs_ordered

pytestmark = pytest.mark.anyio

_REAL_SPAWN = asyncio.create_subprocess_exec


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
    for module in ("app.platform.service_items", "app.platform.arcgis_wfs"):
        monkeypatch.setattr(f"{module}.RECOGNITION_RETRY_DELAYS", (0.0, 0.0))
    for module in ("app.platform.arcgis_wfs", "app.platform.security"):
        monkeypatch.setattr(f"{module}.validate_url_for_ssrf", AsyncMock())


def _esri_pages_stating(total: int) -> dict[int, dict]:
    """The captured chain, with every page stating the whole query's total."""
    pages = _three_esri_pages()
    for page in pages.values():
        page["numberMatched"] = total
    pages[8]["links"] = []
    return pages


def _gdal_staging(monkeypatch, rows: int) -> None:
    """Stand in for ogr2ogr, staging ``rows`` features in its target table."""

    async def _spawn(*argv, **kwargs):
        if argv[0] != "ogr2ogr":
            return await _REAL_SPAWN(*argv, **kwargs)
        schema, table = argv[argv.index("-nln") + 1].split(".")
        from app.core.db import async_session

        async with async_session() as session:
            await session.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}"'))
            await session.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table}" (gid serial PRIMARY KEY, '
                    "name text, geom geometry(Point, 4326))"
                )
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}"."{table}" (name) '
                    f"SELECT 'r' FROM generate_series(1, {int(rows)})"
                )
            )
            await session.commit()

        class _Done:
            returncode = 0

            async def communicate(self):
                return b"", b""

            async def wait(self):
                return 0

        return _Done()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _spawn)


async def _service_dataset(session, *, source_format: str, url: str, layer: str):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=admin_id, source_format=source_format, visibility="public"
    )
    dataset.source_url = url
    restamp(
        dataset,
        SourceBinding.service(source_format, url=url, layer_id=layer, enriched_uri=url),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _refresh(client: AsyncClient, headers: dict, dataset_id) -> None:
    async with _dispatch_harness() as task:
        resp = await client.post(
            f"/datasets/{dataset_id}/refresh", json={}, headers=headers
        )
    assert resp.status_code == 202, resp.text
    with patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()):
        await reupload_service.func(**task.defer_async.call_args.kwargs)


class TestTheWalkSaysWhetherTheServiceStatedItsTotal:
    async def test_a_chain_stating_its_total(self, monkeypatch, tmp_path) -> None:
        _serve(monkeypatch, _esri(_esri_pages_stating(9)))

        extract = await materialise_oapif_items(
            _SERVICE, "0", credential_line=_credential_line(), staging_dir=tmp_path
        )

        assert (extract.total, extract.stated_total) == (9, 9)

    async def test_a_total_summed_from_the_last_pages_remainder(
        self, monkeypatch, tmp_path
    ) -> None:
        _serve(monkeypatch, _esri(_three_esri_pages()))

        extract = await materialise_oapif_items(
            _SERVICE, "0", credential_line=_credential_line(), staging_dir=tmp_path
        )

        assert (extract.total, extract.stated_total) == (9, None)


class TestOnlyAWFSLayersWholeTotalIsReturned:
    async def _read(self, monkeypatch, url: str, version: str, stated: str, staged):
        _serve(
            monkeypatch,
            _counting_only(version, "topp:pts", advertised=version, stated=stated),
        )
        _spawn_reading_the_source(monkeypatch)
        monkeypatch.setattr(
            "app.processing.ingest.ogr.staged_row_count",
            AsyncMock(return_value=staged),
        )
        return await run_ogr2ogr_service(
            f"WFS:{url}", "topp:pts", "t", "PG:dbname=x", "wfs", schema="data"
        )

    @pytest.mark.parametrize(
        ("query", "version", "stated", "staged", "total"),
        [
            ("", "2.0.0", "25", 25, 25),
            ("", "2.0.0", "25", 30, None),
            ("?COUNT=25", "2.0.0", "25", 25, None),
            ("?STARTINDEX=10", "2.0.0", "25", 25, None),
            ("?MAXFEATURES=25", "1.1.0", "5000", 25, None),
        ],
        ids=["equal", "more", "count", "startindex", "1.1-maxfeatures"],
    )
    async def test_the_total_returned(
        self, monkeypatch, query, version, stated, staged, total
    ) -> None:
        url = f"{_OTHER_WFS}{query}"
        assert await self._read(monkeypatch, url, version, stated, staged) == total

    async def test_a_shortfall_still_fails(self, monkeypatch) -> None:
        with pytest.raises(WfsCountMismatchError, match="returned 10 of 25"):
            await self._read(monkeypatch, _OTHER_WFS, "2.0.0", "25", 10)


@pytest.mark.parametrize(
    ("query", "version", "stated", "rows", "status", "code"),
    [
        ("", "2.0.0", "5", 5, "succeeded", None),
        ("", "2.0.0", "5", 7, "blocked", "review_required"),
        ("", "2.0.0", "unknown", 5, "blocked", "review_required"),
        ("?COUNT=5", "2.0.0", "5", 5, "blocked", "review_required"),
        ("?MAXFEATURES=25", "1.1.0", "5000", 25, "blocked", "review_required"),
    ],
    ids=["equal", "more", "none", "2.0-count", "1.1-maxfeatures"],
)
async def test_a_wfs_refresh(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    query,
    version,
    stated,
    rows,
    status,
    code,
) -> None:
    dataset = await _service_dataset(
        test_db_session, source_format="wfs", url=_OTHER_WFS + query, layer="topp:pts"
    )
    _serve(
        monkeypatch,
        _counting_only(version, "topp:pts", advertised=version, stated=stated),
    )
    _gdal_staging(monkeypatch, rows)

    await _refresh(client, admin_auth_header, dataset.id)

    (run,) = await _runs_ordered(test_db_session, dataset.id)
    assert (run.status, run.error_code) == (status, code)
    if status == "blocked":
        assert run.verification["review_reasons"] == ["source_count_unavailable"]
    else:
        assert run.verification["source_count"] == 5
        assert run.verification["review_reasons"] == []


async def test_a_wfs_refresh_shortfall_fails_as_an_import_does(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
) -> None:
    dataset = await _service_dataset(
        test_db_session, source_format="wfs", url=_OTHER_WFS, layer="topp:pts"
    )
    _serve(monkeypatch, _counting_only("2.0.0", "topp:pts", stated="5"))
    _gdal_staging(monkeypatch, 3)

    with pytest.raises(WfsCountMismatchError):
        await _refresh(client, admin_auth_header, dataset.id)

    (run,) = await _runs_ordered(test_db_session, dataset.id)
    assert (run.status, run.error_code) == ("failed", "wfs_short")


@pytest.mark.parametrize(
    ("pages", "rows", "status", "code"),
    [
        (_esri_pages_stating, 9, "succeeded", None),
        (_esri_pages_stating, 8, "failed", "source_count_mismatch"),
        (lambda _total: _three_esri_pages(), 9, "blocked", "review_required"),
    ],
    ids=["equal", "different", "summed-not-stated"],
)
async def test_an_ogc_api_features_refresh(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    pages,
    rows,
    status,
    code,
) -> None:
    dataset = await _service_dataset(
        test_db_session,
        source_format="ogcapi_features",
        url=_SERVICE,
        layer="0",
    )
    _serve(monkeypatch, _esri(pages(9)))
    _gdal_staging(monkeypatch, rows)

    await _refresh(client, admin_auth_header, dataset.id)

    (run,) = await _runs_ordered(test_db_session, dataset.id)
    assert (run.status, run.error_code) == (status, code)
    if status == "blocked":
        assert run.verification["review_reasons"] == ["source_count_unavailable"]
    else:
        assert run.verification["source_count"] == 9
