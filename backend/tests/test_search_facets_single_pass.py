"""Facet counts per caller and filter, and one candidate selection per request."""

import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.modules.catalog.collections.models import Collection, CollectionDataset

from tests.factories import create_dataset, create_user, get_user_id

_WEST = "POLYGON((10 10, 11 10, 11 11, 10 11, 10 10))"
_EAST = "POLYGON((50 50, 51 50, 51 51, 50 51, 50 50))"
_WEST_BBOX = "9,9,12,12"


@dataclass(frozen=True)
class _Seed:
    owner: str
    visibility: str
    record_status: str
    record_type: str
    srid: int
    org: str
    keywords: tuple[str, ...]
    extent: str
    collection: str | None


# The visibility rules these rows exercise: anonymous callers see public and
# published; a signed-in caller adds internal, their own private, draft and
# restricted rows; an admin sees everything.
_SEEDS = (
    _Seed("owner", "public", "published", "vector_dataset", 4326, "a", ("alpha",), _WEST, "c1"),
    _Seed("owner", "public", "draft", "raster_dataset", 3857, "a", ("alpha", "beta"), _WEST, None),
    _Seed("owner", "private", "published", "vector_dataset", 4326, "b", ("beta",), _EAST, "c1"),
    _Seed("owner", "internal", "published", "vrt_dataset", 2263, "b", (), _EAST, "c2"),
    _Seed("owner", "restricted", "published", "vector_dataset", 4326, "a", ("gamma",), _WEST, "c2"),
    _Seed("admin", "public", "published", "raster_dataset", 4326, "c", ("alpha",), _EAST, "c1"),
    _Seed("admin", "private", "published", "vector_dataset", 4326, "c", (), _WEST, None),
)  # fmt: skip


def _visible(seed: _Seed, caller: str) -> bool:
    if caller == "admin":
        return True
    if caller == "anonymous":
        return seed.visibility == "public" and seed.record_status == "published"
    own = seed.owner == caller
    if seed.record_status != "published" and not own:
        return False
    return seed.visibility in ("public", "internal") or own


@pytest.fixture
async def seeded(client: AsyncClient, admin_auth_header: dict, test_db_session):
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    other_headers, _ = await create_user(client, admin_auth_header, "viewer")
    slug = f"zqpass{uuid.uuid4().hex[:8]}"
    creators = {"owner": uuid.UUID(owner_id), "admin": admin_id}

    collections = {}
    for name in ("c1", "c2"):
        collection = Collection(name=f"{slug} {name}", created_by=admin_id)
        session.add(collection)
        await session.flush()
        collections[name] = collection

    for index, seed in enumerate(_SEEDS):
        dataset = await create_dataset(
            session,
            created_by=creators[seed.owner],
            name=f"{slug} row {index}",
            visibility=seed.visibility,
            record_status=seed.record_status,
            record_type=seed.record_type,
            srid=seed.srid,
            source_organization=f"{slug}-{seed.org}",
            keywords=[slug, *(f"{slug}-{kw}" for kw in seed.keywords)],
            spatial_extent_wkt=seed.extent,
        )
        if seed.collection is not None:
            session.add(
                CollectionDataset(
                    collection_id=collections[seed.collection].id,
                    dataset_id=dataset.id,
                )
            )
    await session.commit()
    return {
        "slug": slug,
        "collections": collections,
        "headers": {
            "anonymous": {},
            "owner": owner_headers,
            "other": other_headers,
            "admin": admin_auth_header,
        },
    }


def _expected(seeded: dict, caller: str, matches) -> dict:
    """The facet payload for the seed rows ``caller`` sees and ``matches`` keeps."""
    slug = seeded["slug"]
    rows = [s for s in _SEEDS if _visible(s, caller) and matches(s)]
    keywords = Counter(slug for _ in rows)
    keywords.update(f"{slug}-{kw}" for s in rows for kw in s.keywords)
    collections = Counter(s.collection for s in rows if s.collection)
    return {
        "record_type": dict(Counter(s.record_type for s in rows)),
        "keywords": dict(keywords),
        "source_organization": dict(Counter(f"{slug}-{s.org}" for s in rows)),
        "srid": dict(Counter(str(s.srid) for s in rows)),
        "collections": {
            (str(seeded["collections"][name].id), f"{slug} {name}"): count
            for name, count in collections.items()
        },
    }


def _actual(payload: dict) -> dict:
    for group in ("keywords", "source_organization", "srid"):
        counts = [item["count"] for item in payload[group]]
        assert counts == sorted(counts, reverse=True), group
    counts = [item["dataset_count"] for item in payload["collections"]]
    assert counts == sorted(counts, reverse=True), "collections"
    return {
        "record_type": payload["record_type"],
        "keywords": {i["value"]: i["count"] for i in payload["keywords"]},
        "source_organization": {
            i["value"]: i["count"] for i in payload["source_organization"]
        },
        "srid": {i["value"]: i["count"] for i in payload["srid"]},
        "collections": {
            (i["id"], i["name"]): i["dataset_count"] for i in payload["collections"]
        },
    }


def _cases(seeded: dict):
    slug = seeded["slug"]
    c1 = str(seeded["collections"]["c1"].id)
    return (
        ({"keywords": [slug]}, lambda s: True),
        ({"q": slug}, lambda s: True),
        ({"keywords": [slug], "bbox": _WEST_BBOX}, lambda s: s.extent == _WEST),
        ({"q": slug, "srid": 4326}, lambda s: s.srid == 4326),
        (
            {"keywords": [f"{slug}-alpha"], "source_organization": f"{slug}-a"},
            lambda s: "alpha" in s.keywords and s.org == "a",
        ),
        (
            {"q": slug, "bbox": _WEST_BBOX, "collection_id": c1},
            lambda s: s.extent == _WEST and s.collection == "c1",
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("caller", ["anonymous", "owner", "other", "admin"])
async def test_facet_counts_per_caller_and_filter(
    client: AsyncClient, seeded: dict, caller: str
):
    """Each facet group counts exactly the rows the caller may see and the filters keep."""
    for params, matches in _cases(seeded):
        resp = await client.get(
            "/search/facets/", params=params, headers=seeded["headers"][caller]
        )
        assert resp.status_code == 200, resp.text
        expected = _expected(seeded, caller, matches)
        # Non-vacuity: every case keeps at least one row for every caller.
        assert expected["record_type"], params
        assert _actual(resp.json()) == expected, params


@contextmanager
def _statements():
    import app.core.db as db_module

    seen: list[str] = []

    def _before(_conn, _cursor, statement, *_args):
        seen.append(statement)

    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield seen
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


@pytest.mark.anyio
async def test_facets_select_candidates_once_per_request(
    client: AsyncClient, seeded: dict
):
    """The visibility, text and spatial filters are evaluated once for all five groups.

    Anonymous, so the visibility predicate names ``records.visibility`` once
    and its count over every statement is the number of candidate selections.
    """
    params = {"q": seeded["slug"], "bbox": _WEST_BBOX}
    with _statements() as seen:
        resp = await client.get("/search/facets/", params=params)
    assert resp.status_code == 200, resp.text
    # Non-vacuity: the request counted rows through every group.
    payload = resp.json()
    assert all(payload[group] for group in payload), payload

    candidate_sql = [s for s in seen if "records.visibility" in s]
    assert len(candidate_sql) == 1, (
        f"candidate selection ran in {len(candidate_sql)} statements"
    )
    statement = candidate_sql[0]
    assert statement.count("records.visibility") == 1, statement
    assert "websearch_to_tsquery" in statement and "ST_Intersects" in statement
    # PostgreSQL evaluates an inlined CTE once per reference.
    assert "AS MATERIALIZED" in statement, statement
