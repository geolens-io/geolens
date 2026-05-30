"""Regression tests for EXP-02 + API-01: export access-control matrix and
OGC items trailing-slash route parity.

Pins the Plan 01 (Phase 1157) behavior:
  - EXP-01 positive guard: anonymous export of public+published dataset succeeds
  - EXP-02 deny matrix:
      * anon + public-unpublished (record_status="internal") -> {401,403,404}
      * anon + private -> {401,403,404}
      * anon + restricted -> {401,403,404}
      * non-owner authenticated (viewer, not the admin owner) + private -> {401,403,404}
  - API-01 parity: /collections/{id}/items/ (trailing) == /collections/{id}/items (no-slash)

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
  - Run with: set -a && source ../.env.test && set +a
               uv run pytest tests/test_export_access.py -v
"""

import os
import shutil
import tempfile

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.processing.export.ogr import FORMAT_MAP

from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Mock export service fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_export_service(monkeypatch):
    """Patch app.processing.export.router.export_dataset to avoid ogr2ogr.

    Mirrors test_export_hardening.py:181-220 so the allow-case asserts the
    access-control GATE, not real OGR/GDAL file generation.
    Returns a dummy file; FileResponse handles the rest.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_export_access_")

    async def _fake_export(
        table_name,
        dataset_name,
        format_key,
        *,
        target_srs=None,
        bbox=None,
        where=None,
        column_info=None,
    ):
        if format_key not in FORMAT_MAP:
            raise ValueError(f"Unsupported export format: {format_key}")
        fmt = FORMAT_MAP[format_key]
        ext = fmt["ext"]
        media = fmt["media"]
        if format_key == "shp":
            filename = f"{dataset_name}.zip"
        else:
            filename = f"{dataset_name}{ext}"
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, "wb") as f:
            f.write(b"mock export data")
        return file_path, filename, media

    monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)

    yield _fake_export

    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# EXP-01/EXP-02: export access-control matrix
# ---------------------------------------------------------------------------


async def test_anon_export_public_published_allowed(
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """EXP-01 positive over-gating guard: anonymous export of a public+published
    dataset must return 200 with a non-empty body.

    This guard ensures the EXP-01 gate does not over-restrict legitimate
    anonymous access to public data.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="AnonExportPublicPublishedAllowed",
        visibility="public",
        record_status="published",
    )

    resp = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert resp.status_code == 200, (
        f"Expected 200 for anon export of public+published dataset, "
        f"got {resp.status_code}: {resp.text}"
    )
    assert len(resp.content) > 0, (
        "Expected non-empty body for anon export of public+published dataset"
    )


@pytest.mark.parametrize("fmt", ["gpkg", "geojson", "csv"])
async def test_anon_export_all_formats_public_published_allowed(
    fmt,
    client: AsyncClient,
    test_db_session,
    mock_export_service,
):
    """EXP-01 positive over-gating guard across formats: anonymous export of a
    public+published dataset must return 200 for each supported format.

    Note: shp is excluded because gpkg/geojson/csv cover the gate logic and
    the shp path produces a zip which may interact differently with FileResponse.
    The gate (visibility check) is identical for all formats.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"AnonExportFormatTest_{fmt}",
        visibility="public",
        record_status="published",
    )

    resp = await client.get(f"/datasets/{ds.id}/export?format={fmt}")

    assert resp.status_code == 200, (
        f"Expected 200 for anon export of public+published as {fmt!r}, "
        f"got {resp.status_code}: {resp.text}"
    )


async def test_anon_export_public_unpublished_denied(
    client: AsyncClient,
    test_db_session,
):
    """EXP-02: anonymous export of a public but unpublished (internal) dataset
    must be denied — status in {401, 403, 404}.

    check_dataset_access_or_anonymous raises 404 to hide existence for anon.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="AnonExportPublicUnpublishedDenied",
        visibility="public",
        record_status="internal",  # unpublished
    )

    resp = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for anon export of public+unpublished dataset, "
        f"got {resp.status_code}: {resp.text}"
    )


async def test_anon_export_private_denied(
    client: AsyncClient,
    test_db_session,
):
    """EXP-02: anonymous export of a private+published dataset must be denied —
    status in {401, 403, 404}.

    check_dataset_access_or_anonymous raises 404 to hide existence for anon
    on non-public datasets.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="AnonExportPrivateDenied",
        visibility="private",
        record_status="published",
    )

    resp = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for anon export of private dataset, "
        f"got {resp.status_code}: {resp.text}"
    )


async def test_anon_export_restricted_denied(
    client: AsyncClient,
    test_db_session,
):
    """EXP-02: anonymous export of a restricted+published dataset must be denied —
    status in {401, 403, 404}.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="AnonExportRestrictedDenied",
        visibility="restricted",
        record_status="published",
    )

    resp = await client.get(f"/datasets/{ds.id}/export?format=geojson")

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for anon export of restricted dataset, "
        f"got {resp.status_code}: {resp.text}"
    )


async def test_non_owner_export_private_denied(
    client: AsyncClient,
    test_db_session,
    viewer_auth_header: dict,
):
    """EXP-02: authenticated non-owner (viewer) export of a private dataset
    must be denied — status in {401, 403, 404}.

    The dataset is owned by admin; the viewer is a distinct user who is NOT
    the owner and does NOT have admin privileges to override visibility.
    check_dataset_access raises 404 for authenticated non-owner denials.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="NonOwnerExportPrivateDenied",
        visibility="private",
        record_status="published",
    )

    # Viewer is a non-owner: authenticated but NOT the admin owner.
    resp = await client.get(
        f"/datasets/{ds.id}/export?format=geojson",
        headers=viewer_auth_header,
    )

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for non-owner (viewer) export of private dataset, "
        f"got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# API-01: trailing-slash parity on /collections/{id}/items
# ---------------------------------------------------------------------------


async def test_collection_items_trailing_slash_matches_no_slash(
    client: AsyncClient,
    test_db_session,
):
    """API-01: GET /collections/{id}/items/ (trailing slash) must resolve to
    the same status as /collections/{id}/items (no slash).

    Pins the Plan 01 dual-shape stacked-decorator alias on get_collection_items
    against regression. A public+published dataset with a real data table is
    used so the OGC items endpoint can serve rows and return 200 on both shapes.

    Asserts:
      (a) neither shape returns 404
      (b) both shapes return identical status codes
      (c) the canonical (no-slash) form returns 200
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="OGCItemsTrailingSlashParity",
        visibility="public",
        record_status="published",
        geometry_type="Point",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )

    # Create the actual PostGIS data table so get_features() can query it.
    # The OGC items endpoint queries data.{table_name} directly; without
    # the table, the handler raises a 500 (UndefinedTableError).
    table_name = ds.table_name
    try:
        await test_db_session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  name TEXT,"
                f"  geom GEOMETRY(Point, 3857),"
                f"  geom_4326 GEOMETRY(Point, 4326)"
                f")"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES ("
                f"  'test_point',"
                f"  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
                f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
                f")"
            )
        )
        await test_db_session.commit()

        url_noslash = f"/collections/{ds.id}/items"
        url_slash = f"/collections/{ds.id}/items/"

        resp_noslash = await client.get(url_noslash)
        resp_slash = await client.get(url_slash)

        assert resp_noslash.status_code == 200, (
            f"Canonical no-slash form {url_noslash!r} must return 200, "
            f"got {resp_noslash.status_code}: {resp_noslash.text[:200]}"
        )
        assert resp_slash.status_code != 404, (
            f"Trailing-slash form {url_slash!r} must not return 404 (alias not registered?), "
            f"got {resp_slash.status_code}: {resp_slash.text[:200]}"
        )
        assert resp_slash.status_code == resp_noslash.status_code, (
            f"Trailing-slash {url_slash!r} returned {resp_slash.status_code} "
            f"but no-slash {url_noslash!r} returned {resp_noslash.status_code} — "
            f"alias resolves to a different handler or status"
        )
    finally:
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{table_name}")
        )
        await test_db_session.commit()
