"""Tests for enriched OGC record properties: formats, language, themes, rights, contacts, time.

Verifies:
  - Each record includes formats list of available export media types
  - Each record includes language defaulting to en
  - Records with tags include themes in OGC concepts structure
  - Records with license include rights matching the license string
  - Contacts are now sourced from record_contacts table (contact JSONB dropped in 87-01)
  - Records with data_vintage dates include time.interval with ISO 8601 dates
  - Open-ended temporal bounds use ".." notation
  - Null metadata fields produce null enriched properties
  - All existing record properties remain unchanged after enrichment
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_enriched_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Enriched Test Dataset",
    visibility: str = "public",
    theme_category: list[str] | None = None,
    license_val: str | None = None,
    data_vintage_start: date | None = None,
    data_vintage_end: date | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair with enriched metadata fields.

    Note: contact JSONB column was dropped in 87-01. Contacts are now
    managed via the record_contacts table.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        theme_category=theme_category,
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        license=license_val,
        temporal_start=data_vintage_start,
        temporal_end=data_vintage_end,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiLineString",
        feature_count=500,
        source_format="shp",
        source_filename="test.shp",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# Default enriched metadata
_DEFAULT_THEME_CATEGORY = ["transportation", "roads", "infrastructure"]
_DEFAULT_LICENSE = "CC-BY-4.0"
_DEFAULT_VINTAGE_START = date(2020, 1, 1)
_DEFAULT_VINTAGE_END = date(2023, 12, 31)


# ---------------------------------------------------------------------------
# Formats tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_formats_list(client: AsyncClient, test_db_session):
    """GET a record returns properties.formats as a list of 4 media type strings."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session, created_by=admin_id, name="Formats Test"
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert "formats" in props
    formats = props["formats"]
    assert isinstance(formats, list)
    assert len(formats) == 4
    assert "application/geopackage+sqlite3" in formats
    assert "application/geo+json" in formats
    assert "application/x-shapefile" in formats
    assert "text/csv" in formats


# ---------------------------------------------------------------------------
# Language tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_language(client: AsyncClient, test_db_session):
    """GET a record returns properties.language as 'en'."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session, created_by=admin_id, name="Language Test"
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["language"] == "en"


# ---------------------------------------------------------------------------
# Themes tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_themes_from_theme_category(
    client: AsyncClient, test_db_session
):
    """Record with theme_category has themes in OGC concepts structure."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Themes Test",
        theme_category=_DEFAULT_THEME_CATEGORY,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    themes = props["themes"]
    assert isinstance(themes, list)
    assert len(themes) == 1
    assert "concepts" in themes[0]
    concepts = themes[0]["concepts"]
    assert {"id": "transportation"} in concepts
    assert {"id": "roads"} in concepts
    assert {"id": "infrastructure"} in concepts


@pytest.mark.anyio
async def test_record_themes_null_when_no_theme_category(
    client: AsyncClient, test_db_session
):
    """Record with no theme_category has themes as None."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="No Themes Test",
        theme_category=None,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["themes"] is None


# ---------------------------------------------------------------------------
# Rights tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_rights_from_license(client: AsyncClient, test_db_session):
    """Record with license has rights matching the license string."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Rights Test",
        license_val=_DEFAULT_LICENSE,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["rights"] == "CC-BY-4.0"


@pytest.mark.anyio
async def test_record_rights_null_when_no_license(client: AsyncClient, test_db_session):
    """Record with no license has rights as None."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="No Rights Test",
        license_val=None,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["rights"] is None


# ---------------------------------------------------------------------------
# Contacts tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_contacts_from_record_contacts_table(
    client: AsyncClient, test_db_session
):
    """Contacts in OGC response come from the record_contacts table."""
    from app.modules.catalog.datasets.domain.models import RecordContact

    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Contacts OGC Test",
    )
    # Insert a contact row
    contact = RecordContact(
        record_id=ds.record_id,
        role="pointOfContact",
        name="Jane Doe",
        organization="ACME GIS",
    )
    session.add(contact)
    await session.commit()

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["contacts"] is not None
    assert isinstance(props["contacts"], list)
    assert len(props["contacts"]) == 1
    contacts = sorted(props["contacts"], key=lambda c: c["name"])
    assert contacts[0]["name"] == "Jane Doe"
    assert contacts[0]["organization"] == "ACME GIS"
    assert contacts[0]["roles"] == ["pointOfContact"]


@pytest.mark.anyio
async def test_record_contacts_empty_when_no_contacts(
    client: AsyncClient, test_db_session
):
    """Record without contacts has null contacts list."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="No Contacts Test",
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["contacts"] is None


# ---------------------------------------------------------------------------
# Time (temporal extent) tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_time_from_vintage(client: AsyncClient, test_db_session):
    """Record with data_vintage_start/end has time.interval with ISO dates."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Time Test",
        data_vintage_start=_DEFAULT_VINTAGE_START,
        data_vintage_end=_DEFAULT_VINTAGE_END,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    time_obj = props["time"]
    assert isinstance(time_obj, dict)
    assert "interval" in time_obj
    assert time_obj["interval"] == [["2020-01-01", "2023-12-31"]]


@pytest.mark.anyio
async def test_record_time_with_open_start(client: AsyncClient, test_db_session):
    """Record with only data_vintage_end uses '..' for start."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Open Start Test",
        data_vintage_start=None,
        data_vintage_end=date(2023, 12, 31),
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["time"]["interval"] == [["..", "2023-12-31"]]


@pytest.mark.anyio
async def test_record_time_with_open_end(client: AsyncClient, test_db_session):
    """Record with only data_vintage_start uses '..' for end."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Open End Test",
        data_vintage_start=date(2020, 1, 1),
        data_vintage_end=None,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["time"]["interval"] == [["2020-01-01", ".."]]


@pytest.mark.anyio
async def test_record_time_null_when_no_vintage(client: AsyncClient, test_db_session):
    """Record with no vintage dates has time as None."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="No Time Test",
        data_vintage_start=None,
        data_vintage_end=None,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["time"] is None


# ---------------------------------------------------------------------------
# Regression test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_existing_properties_still_present(client: AsyncClient, test_db_session):
    """All original properties exist alongside new enriched properties."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session,
        created_by=admin_id,
        name="Regression Props Test",
        theme_category=_DEFAULT_THEME_CATEGORY,
        license_val=_DEFAULT_LICENSE,
        data_vintage_start=_DEFAULT_VINTAGE_START,
        data_vintage_end=_DEFAULT_VINTAGE_END,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]

    # Original properties
    assert props["type"] == "dataset"
    assert props["title"] == "Regression Props Test"
    assert "description" in props
    assert "keywords" in props
    assert "created" in props
    assert "updated" in props
    assert props["crs"] == "EPSG:4326"
    assert props["geometry_type"] == "MultiLineString"
    assert props["feature_count"] == 500
    assert "license" in props
    assert "source_organization" in props

    # New enriched properties also present
    assert "formats" in props
    assert "language" in props
    assert "themes" in props
    assert "rights" in props
    assert "contacts" in props
    assert "time" in props


# ---------------------------------------------------------------------------
# Table-specific OGC record properties (260408-iny)
# ---------------------------------------------------------------------------


async def _create_table_dataset(
    session,
    *,
    created_by,
    name: str = "Test Table Dataset",
    feature_count: int = 29,
    column_info: list | None = None,
) -> "Dataset":
    """Insert a Record + Dataset pair for a non-spatial table record."""
    import uuid

    from app.modules.catalog.datasets.domain.models import Dataset, Record

    table_name = f"tbl_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Table dataset: {name}",
        visibility="public",
        record_status="published",
        created_by=created_by,
        record_type="table",
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=None,
        geometry_type=None,
        feature_count=feature_count,
        source_format="arcgis_featureserver",
        source_filename="TestTable",
        column_info=column_info,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.mark.anyio
async def test_table_record_formats_excludes_shapefile(
    client: AsyncClient, test_db_session
):
    """Table records must NOT advertise application/x-shapefile in formats list.
    Table records MUST advertise text/csv, application/geopackage+sqlite3,
    and application/geo+json (three entries exactly)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_table_dataset(
        session, created_by=admin_id, name="Table Formats Test"
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert "formats" in props
    formats = props["formats"]
    assert isinstance(formats, list)
    assert "application/x-shapefile" not in formats
    assert "text/csv" in formats
    assert "application/geopackage+sqlite3" in formats
    assert "application/geo+json" in formats
    assert len(formats) == 3


@pytest.mark.anyio
async def test_vector_record_formats_includes_shapefile(
    client: AsyncClient, test_db_session
):
    """Vector dataset records still advertise shapefile (regression guard)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session, created_by=admin_id, name="Vector Formats Regression"
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    formats = props["formats"]
    assert "application/x-shapefile" in formats
    assert len(formats) == 4


@pytest.mark.anyio
async def test_table_record_has_row_count_alias(client: AsyncClient, test_db_session):
    """Table records expose row_count == feature_count AND feature_count itself."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_table_dataset(
        session, created_by=admin_id, name="Row Count Alias Test", feature_count=29
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props.get("feature_count") == 29
    assert props.get("row_count") == 29


@pytest.mark.anyio
async def test_vector_record_has_no_row_count(client: AsyncClient, test_db_session):
    """Vector dataset records do NOT expose row_count (or it is None)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_enriched_dataset(
        session, created_by=admin_id, name="Vector No Row Count"
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    # row_count should be absent or None for vector records
    assert props.get("row_count") is None


@pytest.mark.anyio
async def test_table_record_has_column_count(client: AsyncClient, test_db_session):
    """Table records with column_info populated expose column_count == len(column_info)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    col_info = [
        {
            "name": "opportunity_number",
            "type": "text",
            "ordinal_position": 1,
            "is_nullable": True,
        },
        {
            "name": "federal_agency",
            "type": "text",
            "ordinal_position": 2,
            "is_nullable": True,
        },
        {
            "name": "category",
            "type": "text",
            "ordinal_position": 3,
            "is_nullable": True,
        },
        {
            "name": "opening_date",
            "type": "date",
            "ordinal_position": 4,
            "is_nullable": True,
        },
        {
            "name": "closing_date",
            "type": "date",
            "ordinal_position": 5,
            "is_nullable": True,
        },
    ]
    ds = await _create_table_dataset(
        session,
        created_by=admin_id,
        name="Column Count Test",
        column_info=col_info,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props.get("column_count") == 5
