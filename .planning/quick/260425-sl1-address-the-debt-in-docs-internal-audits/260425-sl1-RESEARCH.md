---
quick_id: 260425-sl1
status: research_complete
researched: 2026-04-26
---

# Research: Backend Test Debt 20260425

## Test runner command

Tests run inside the API container via uv. Single-test pattern:

```bash
docker compose exec -T api uv run pytest <test_path>::<test_name> -xvs
```

Multi-test (use this for verifying fixes don't regress siblings):

```bash
docker compose exec -T api uv run pytest tests/test_ai_chat.py tests/test_chat_streaming.py tests/test_ogc_collection_metadata.py tests/test_ogc_features.py tests/test_search.py tests/test_public_urls.py tests/test_stac_record_output.py
```

Full suite (only run after task is complete; ~minutes):

```bash
docker compose exec api uv run pytest -v --tb=short
# or via Makefile target:
make test
```

`backend/Makefile` does not exist; canonical `make test` target lives in `/Users/ishiland/Code/geolens/Makefile` and wraps `docker compose exec api uv run pytest -v --tb=short`.

## freezegun availability

**Absent.** Confirmed by reading `backend/pyproject.toml` `[dependency-groups].dev`. Neither `freezegun` nor `pytest-freezer` is present.

**Recommendation:** Add `freezegun>=1.5.0` to `backend/pyproject.toml` `[dependency-groups].dev`, alphabetized between `fakeredis` and `httpx`. Use `freezegun` (not `pytest-freezer`) — it's the more widely-used, stable choice and the existing test code uses bare `pytest` decorators rather than pytest-plugin marker style. Then run `docker compose exec api uv lock && docker compose build api` to materialize the install.

Import pattern for the fix:

```python
from freezegun import freeze_time

@pytest.mark.anyio
async def test_search_filter_by_date_range(..., search_datasets):
    with freeze_time("2026-04-26 12:00:00"):
        ...
```

**Important caveat for the executor:** `freezegun` patches Python's `datetime`/`date` modules but does NOT patch Postgres `NOW()`. The `Record.created_at` column uses `server_default=func.now()` (`backend/app/modules/catalog/datasets/domain/models.py:131,134,455`), so the freshly-inserted `search_datasets` records will still get the real wall-clock UTC timestamp from Postgres. Freezegun's role here is to lock `date.today()` so that the `yesterday`/`today`/`tomorrow` arithmetic in the test doesn't drift across the midnight UTC boundary mid-test. Set the freeze instant to "right now" (do NOT freeze to a hardcoded historical date — that would skew yesterday/tomorrow away from the real Postgres wall-clock and re-introduce the failure). Pattern:

```python
from datetime import datetime, timezone
from freezegun import freeze_time

@pytest.mark.anyio
async def test_search_filter_by_date_range(..., search_datasets):
    # Snapshot the real moment, then freeze so today/yesterday/tomorrow are stable
    with freeze_time(datetime.now(timezone.utc)):
        today = date.today()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)
        ...
```

This kills the only realistic failure window (test runs across a midnight boundary). If the executor finds the freezegun install adds >30 LOC of fixture refactor, fall back to xfail per CONTEXT.md.

## Per-failure resolution table

| # | Test | File:Line | Resolution | Concrete change |
|---|------|-----------|------------|-----------------|
| 1 | `test_validate_overwrites_client_table_name` | `backend/tests/test_ai_chat.py:96` | **fix-test** (root cause is obvious; CONTEXT allows discretion) | Unpack tuple: `validated, _basemap = await _validate_chat_layers(...)` |
| 2 | `test_validate_filters_inaccessible_dataset` | `backend/tests/test_ai_chat.py:120` | **fix-test** (same as #1) | Same tuple-unpacking fix |
| 3 | `test_stream_returns_sse_events` | `backend/tests/test_chat_streaming.py:97` | **fix-test** (mock signature mismatch) | Change `return_value=CHAT_BODY["layers"]` to `return_value=(CHAT_BODY["layers"], None)` |
| 4 | `test_non_streaming_fallback` | `backend/tests/test_chat_streaming.py:122` | **fix-test** (same as #3) | Same `return_value=(layers, None)` |
| 5 | `test_tool_progress_events` | `backend/tests/test_chat_streaming.py:148` | **fix-test** (same as #3) | Same |
| 6 | `test_query_data_stage_events` | `backend/tests/test_chat_streaming.py:190` | **fix-test** (same as #3) | Same |
| 7 | `test_show_query_result_action_in_stream` | `backend/tests/test_chat_streaming.py:291` | **fix-test** (same as #3) | Same |
| 8 | `test_per_dataset_collection_has_extent_in_list` | `backend/tests/test_ogc_collection_metadata.py:367` | **fix-test** (limit pagination) | Add `?limit=200` to the GET request: `await client.get("/collections", params={"limit": 200})` |
| 9 | `test_per_dataset_collection_has_root_link_in_list` | `backend/tests/test_ogc_collection_metadata.py:405` | **fix-test** (same as #8) | Same `params={"limit": 200}` |
| 10 | `test_collections_includes_dataset_collections` | `backend/tests/test_ogc_features.py:143` | **fix-test** (same as #8) | Same `params={"limit": 200}` |
| 11 | `test_search_filter_by_date_range` | `backend/tests/test_search.py:395` | **fix-test** with freezegun (per CONTEXT) | Wrap in `with freeze_time(datetime.now(timezone.utc)):`; if install >30 LOC, xfail with cluster 5 reason |
| 12 | `test_load_public_url_overrides_unwraps_json_values` | `backend/tests/test_public_urls.py:211` | **fix-test** (root cause IS obvious; cache global) — see Risks below | Add `public_urls._PUBLIC_URL_CACHE = None` as first line of test body |
| 13 | `test_datetime_null_when_no_temporal` | `backend/tests/test_stac_record_output.py:116` | **fix-test** (per CONTEXT lock) | Rename + assert created_at fallback (see cluster 1 detail) |
| 14 | `test_raster_record_no_stac_extensions` | `backend/tests/test_stac_record_output.py:223` | **fix-code** (real test-vs-spec divergence; STAC keys are leaking) | Add filter to drop `stac_*` keys from raster_meta merge in `dataset_to_ogc_record` |
| 15 | `test_no_bands_without_band_info` | `backend/tests/test_stac_record_output.py:301` | **fix-code** (same site as #14) | Same filter — must also strip `stac_extensions` when `band_info` is None |

## Detailed findings

### Cluster 1 — STAC datetime (1 failure)

**Failure:** `test_datetime_null_when_no_temporal` at `backend/tests/test_stac_record_output.py:116`.

**Run-time evidence:** `AssertionError: assert '2026-04-26T00:40:02.030838Z' is None` — the serializer returns the record's `created_at` ISO-formatted, not `None`.

**Code (intentional behavior):** `backend/app/modules/catalog/search/service.py:1051-1057`:

```python
else:
    # No temporal extent — use created_at as fallback
    stac_datetime = (
        record.created_at.isoformat().replace("+00:00", "Z")
        if record.created_at
        else None
    )
```

**Resolution:** Per CONTEXT.md Cluster 1 LOCKED — keep code, fix test. Rename test to `test_datetime_falls_back_to_created_at_when_no_temporal` and update assertion.

**Exact edit (replace lines 116-122):**

```python
async def test_datetime_falls_back_to_created_at_when_no_temporal(
    self, client, test_db_session
):
    """Record with no temporal_start/end falls back to created_at as STAC datetime.

    See audit 20260425 cluster 1: the serializer at
    backend/app/modules/catalog/search/service.py:1051-1057 deliberately falls
    back to created_at so the item always passes STAC validation. The previous
    expectation of `None` was a misread of STAC 1.0.0 (which permits null but
    we choose defensive validation).
    """
    admin_id = await _get_admin_id(test_db_session)
    dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

    result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
    expected = dataset.record.created_at.isoformat().replace("+00:00", "Z")
    assert result["properties"]["datetime"] == expected
```

### Cluster 2 — STAC compliance (2 failures)

**This is a real code regression, not a test-vs-spec trade-off.** The two failing tests both assert `"stac_extensions" not in result` for raster records. Run-time evidence shows `result` actually contains `stac_extensions` (the assertion fires — so the key IS present). This is the OPPOSITE of cluster 1: cluster 1 was code-correct/test-wrong; cluster 2 is test-correct/code-wrong.

The class is even named `TestStacExtensionsRemoved` — the explicit purpose is to enforce that STAC-specific keys do NOT leak into OGC Records output. Two sibling tests in the same class (`test_vector_record_no_stac_extensions`, `test_raster_record_proj_properties`) PASS, confirming the intent is real and the regression is specific to the raster code path.

**Failures:**

- `test_raster_record_no_stac_extensions` at `backend/tests/test_stac_record_output.py:223` — feeds `raster_meta` with `band_info` populated; assertion `assert "stac_extensions" not in result` fails.
- `test_no_bands_without_band_info` at `backend/tests/test_stac_record_output.py:301` — feeds `raster_meta` with `band_info=None`; same `stac_extensions` leak.

**Resolution:** **fix-code.** The serializer in `backend/app/modules/catalog/search/service.py` (the same `dataset_to_ogc_record` function around line 1065 onwards) is adding `stac_extensions` when `raster_meta` is provided. The executor must:

1. Locate the code site that adds `stac_extensions` (Grep `stac_extensions` in `backend/app/modules/catalog/search/service.py`). The audit doesn't pinpoint the line — researcher couldn't run the full read pass without exceeding context. Search both the raster branch and any shared post-processing block.
2. Remove the `stac_extensions` assignment OR move it into a `_build_stac_assets`-style helper that is only used by genuine STAC endpoints (not OGC Records output).
3. Verify by running:
   ```bash
   docker compose exec -T api uv run pytest tests/test_stac_record_output.py -v
   ```
   All three `TestStacExtensionsRemoved` tests should pass. Also verify `TestStacAssetsRemoved` and `TestNoStacBleedthrough` still pass (same intent class — sibling guards against re-leaking).

**Decision rationale (why fix-code not xfail):**

- Test class name (`TestStacExtensionsRemoved`) makes the intent unambiguous and matches sibling passing tests.
- Same audit lineage (cluster 1 in CONTEXT) called these "STAC trade-off"; the actual evidence shows it's a one-direction leak, not a trade-off.
- The fix surface is a single removal (a key being set where it shouldn't), not a redesign.
- Only ~5 lines of search/edit per finding.

If the executor opens `service.py` and sees the `stac_extensions` site is structurally entangled with the raster_meta merge such that removing it requires >30 LOC of refactor, fall back to xfail with `reason="audit 20260425 cluster 2: stac_extensions leaks into raster OGC record output, see audit"`.

### Cluster 3 — AI chat / chat streaming (7 failures)

**Single shared root cause** — and it's trivially fixable, NOT stubborn cluster-3 territory. The signature of `_validate_chat_layers` in `backend/app/processing/ai/router.py:94-99` was changed at some point to return `tuple[list[ChatMapLayer], str | None]` (validated layers + basemap_style) but the tests were never updated. CONTEXT.md classifies cluster 3 as xfail-by-default; the spirit of the lock ("can't quickly root-cause") suggests fix-test is preferable here. The planner should make the call.

#### Direct calls (cluster 3a) — `test_ai_chat.py`

Both tests call `_validate_chat_layers` directly and treat the return as a list:

- `test_validate_overwrites_client_table_name` at line 96 — `validated = await _validate_chat_layers(...)` then `assert len(validated) == 1` → fails with `assert 2 == 1` (the tuple has length 2: `[ChatMapLayer(...)]` and `'openfreemap-positron'`).
- `test_validate_filters_inaccessible_dataset` at line 120 — same pattern, same failure.

**Exact edit (both tests, line 113 and line 149):**

Change:
```python
validated = await _validate_chat_layers(session, admin, str(map_obj.id), [layer])
```
to:
```python
validated, _basemap = await _validate_chat_layers(session, admin, str(map_obj.id), [layer])
```

#### Mocked calls (cluster 3b) — `test_chat_streaming.py`

All 5 tests mock `_validate_chat_layers` with `return_value=CHAT_BODY["layers"]` (a bare list). The router unpacks: `validated_layers, basemap_style = await _validate_chat_layers(...)` → raises `ValueError: not enough values to unpack (expected 2, got 1)` (test #4 captures this exactly). The pre-flight error handler in the SSE generator at `backend/app/processing/ai/router.py:382-392` catches this and emits an `error` event instead of token events — explaining the `assert 0 >= 1` and `'token' in ['error']` failure shapes.

**Exact edit (5 patch sites in `test_chat_streaming.py`):**

Change every:
```python
patch(
    "app.processing.ai.router._validate_chat_layers",
    new_callable=AsyncMock,
    return_value=CHAT_BODY["layers"],  # or body["layers"]
),
```
to:
```python
patch(
    "app.processing.ai.router._validate_chat_layers",
    new_callable=AsyncMock,
    return_value=(CHAT_BODY["layers"], None),  # or (body["layers"], None)
),
```

Affected sites (each test has one):
- line 102 (`test_stream_returns_sse_events`)
- line 132 (`test_non_streaming_fallback`)
- line 153 (`test_tool_progress_events`)
- line 211 (`test_query_data_stage_events`)
- line 314 (`test_show_query_result_action_in_stream`)

**Fallback to xfail (if planner sticks with CONTEXT lock):**

```python
@pytest.mark.xfail(
    reason="audit 20260425 cluster 3: _validate_chat_layers signature changed to (layers, basemap_style); tests not updated",
    strict=False,
)
```

Add immediately above each `@pytest.mark.anyio` decorator (7 sites total).

### Cluster 4 — OGC catalog (3 failures)

**Root cause:** Suite-pollution failures, but the pollution is benign and the fix is in the test query, not the polluter. The `/collections` endpoint at `backend/app/modules/catalog/search/router.py:980-981` defaults to `limit=50` per-dataset collections. Each test's freshly-created dataset has a fresh UUID and is not guaranteed sort priority. When ≥50 datasets exist before the test runs (the case when `test_search.py` and other dataset-creating tests run first), the new dataset doesn't appear on the first page.

Reproduced by:
```bash
docker compose exec -T api uv run pytest tests/test_search.py tests/test_ogc_collection_metadata.py tests/test_ogc_features.py
# → 3 failures in cluster 4 tests
```

Failure mode: `assert len(per_ds) == 1, f"Expected per-dataset entry for {ds.id}"` → `assert 0 == 1` (the freshly-created dataset is not in the page). Confirmed via direct DB count: `SELECT count(*) FROM catalog.records;` returns 24+ in a polluted DB; the failure mode shows when polluted DB exceeds ~50 datasets via cumulative test runs.

**Failures and exact edits:**

| Test | File:Line of GET | Change |
|------|------------------|--------|
| `test_per_dataset_collection_has_extent_in_list` | `test_ogc_collection_metadata.py:383` | `await client.get("/collections")` → `await client.get("/collections", params={"limit": 200})` |
| `test_per_dataset_collection_has_root_link_in_list` | `test_ogc_collection_metadata.py:418` | Same edit |
| `test_collections_includes_dataset_collections` | `test_ogc_features.py:148` | Same edit |

`200` is the maximum allowed (`Query(50, ge=1, le=200, ...)` at router.py:981). For long-running CI lifetimes this could still pollute past 200, but realistically the test DB is dropped per session; `200` is sufficient buffer.

**Decision rationale (why fix-test not fix-code):** The endpoint behavior (default `limit=50`) is correct OGC and matches OGC API design. Production users explicitly paginate. The tests were assuming an unbounded list; widening their request to `limit=200` is the correct alignment with the API contract. No code regression here.

**Fallback to xfail:**

```python
@pytest.mark.xfail(
    reason="audit 20260425 cluster 4: per-dataset entry not on first /collections page when DB has >50 datasets, see audit",
    strict=False,
)
```

### Cluster 5 — Search date-range (1 failure)

**Test:** `test_search_filter_by_date_range` at `backend/tests/test_search.py:395`.

**Run-time evidence:** Per audit, `assert 0 >= 4` — zero datasets visible in `date_from=yesterday, date_to=tomorrow` window. Researcher could not reproduce in fresh DB (test passes when run alone or with sibling test_search.py tests). Audit timing suggests pollution + UTC midnight boundary timing trigger it.

**Root cause:** Postgres `Record.created_at` has `server_default=func.now()` (`backend/app/modules/catalog/datasets/domain/models.py:131`). Test uses `date.today()` from local Python clock. If test execution straddles a UTC midnight (or there's a clock-skew between Python and Postgres), the date-range arithmetic computed in Python may not bracket the wall-clock instant Postgres uses.

The query at `backend/app/modules/catalog/search/service.py:693-696`:
```python
if filters.date_from:
    stmt = stmt.where(Record.created_at >= filters.date_from)
if filters.date_to:
    stmt = stmt.where(Record.created_at <= filters.date_to)
```

**Exact edit (per CONTEXT lock — use freezegun):**

Add to top of file (line 14, after `import pytest`):
```python
from datetime import datetime, timezone
from freezegun import freeze_time
```

Replace the test body (`backend/tests/test_search.py:395-440`):

```python
@pytest.mark.anyio
async def test_search_filter_by_date_range(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Filter by date_from/date_to narrows to datasets created in that range.

    Freezes wall-clock so today/yesterday/tomorrow are computed from a single
    instant — kills the midnight-UTC boundary race the audit observed.
    """
    # Snapshot the real current moment, then freeze so all date arithmetic
    # below uses the same anchor. Postgres NOW() is unaffected (server-side),
    # so created_at timestamps still match real wall-clock — but yesterday
    # and tomorrow now bracket the freeze instant deterministically.
    with freeze_time(datetime.now(timezone.utc)):
        today = date.today()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        resp = await client.get(
            "/search/datasets/",
            params={
                "date_from": yesterday.isoformat(),
                "date_to": tomorrow.isoformat(),
                "limit": 100,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["numberMatched"] >= 4

        resp2 = await client.get(
            "/search/datasets/",
            params={
                "date_from": "2020-01-01",
                "date_to": "2020-01-31",
                "limit": 100,
            },
            headers=admin_auth_header,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        ids = [f["id"] for f in data2["features"]]
        for ds in search_datasets.values():
            assert str(ds.id) not in ids
```

**Fallback to xfail (if freezegun install or fixture refactor exceeds 30 LOC, per CONTEXT):**

```python
@pytest.mark.xfail(
    reason="audit 20260425 cluster 5: date.today() vs Postgres NOW() boundary race when test straddles midnight UTC, see audit",
    strict=False,
)
```

### Cluster 6 — Test pollution (1 failure)

**Test:** `test_load_public_url_overrides_unwraps_json_values` at `backend/tests/test_public_urls.py:211`.

**Root cause IS obvious** (contradicts CONTEXT cluster 6 LOCKED xfail): `_load_public_url_overrides` in `backend/app/core/public_urls.py:170-196` short-circuits via a module-level cache global `_PUBLIC_URL_CACHE` (line 166) with a 60s TTL. Any earlier test that calls `get_public_urls(db)` indirectly (any HTTP request through the test client that resolves URLs) populates this cache. When `test_load_public_url_overrides_unwraps_json_values` runs after such a test, the cache is hit at line 175-176 and the function returns the cached dict instead of calling `db.execute` on the AsyncMock — so the assertion `overrides == {...expected unwrapped values...}` fails.

This is fixable in **<5 lines**, well under the CONTEXT cluster 6 threshold ("If unclear after a brief look").

**Exact edit (insert at line 213, top of test body):**

```python
@pytest.mark.anyio
async def test_load_public_url_overrides_unwraps_json_values() -> None:
    public_urls._PUBLIC_URL_CACHE = None  # clear cross-test cache pollution
    db = AsyncMock()
    ...
```

(Total addition: 1 line.)

Recommend the planner consider promoting this to a session-autouse fixture in `tests/conftest.py` to prevent re-emergence:

```python
@pytest.fixture(autouse=True)
def _clear_public_url_cache():
    from app.core import public_urls
    public_urls._PUBLIC_URL_CACHE = None
    yield
    public_urls._PUBLIC_URL_CACHE = None
```

But that's a separate quality-of-life change; for THIS task, the in-test one-liner closes the failure.

**Fallback to xfail (if planner sticks with CONTEXT lock):**

```python
@pytest.mark.xfail(
    reason="audit 20260425 cluster 6: stale _PUBLIC_URL_CACHE global from prior test, see backend/app/core/public_urls.py:166",
    strict=False,
)
```

## Risks / gotchas the planner should know

- **CONTEXT lock vs root-cause obviousness:** Three locked decisions (cluster 3 default-xfail, cluster 6 xfail) turn out to have obvious root causes that fix-test cleanly:
  - Cluster 3: 7 tests fixable by adding `, None` to one tuple per test (5-7 line diff total)
  - Cluster 6: 1 test fixable by adding 1 line (`_PUBLIC_URL_CACHE = None`)
  - Per CONTEXT.md, planner has discretion ("can't quickly root-cause"). Recommend overriding both locks → fix-test for cleanliness. xfail accumulates as long-tail debt.
- **Cluster 2 is genuinely fix-code** (not the test-vs-spec trade-off CONTEXT theorized as PARTIAL). Test class name `TestStacExtensionsRemoved` makes intent unambiguous; sibling tests in the same class pass → the failure is a real raster-path regression. The fix is in `backend/app/modules/catalog/search/service.py` (search for `stac_extensions` after the raster_meta block; researcher could not pinpoint exact line without exceeding context).
- **Cluster 5 freezegun caveat:** freezegun does NOT patch Postgres `NOW()`. The fix only works because the test computes `yesterday`/`today`/`tomorrow` in Python from frozen time AFTER Postgres has already inserted rows at real wall-clock UTC. Freeze instant MUST be `datetime.now(timezone.utc)` (or close to it) — not a hardcoded historical date — or yesterday/tomorrow will not bracket the actual `created_at` values and the test will fail in a NEW way.
- **Cluster 4 limit=200 is a ceiling.** The `/collections` route has `Query(50, ge=1, le=200)` — `200` is the max. If session-cumulative test pollution ever exceeds 200 datasets, these three tests will regress. Test DB is dropped per session (`tests/conftest.py:59`) so this is a low risk, but worth noting.
- **Test ordering dependence:** Several "passes alone, fails in suite" failures (cluster 4, 5, 6) demonstrate the test suite has hidden ordering coupling. The audit recommendation to run with `--randomly-seed` is correct but out of scope per CONTEXT. The single-line cache fix in cluster 6 is the only one that directly removes one such coupling.
- **No `freezegun` installed yet.** Adding it requires `uv lock` + container rebuild (`docker compose build api`) before tests can use the import. Planner should sequence: (1) edit pyproject.toml, (2) rebuild api image, (3) only then implement the cluster 5 test edit.
- **`anyio_mode = "auto"` plus `asyncio_mode = "strict"`** (`backend/pyproject.toml:66-67`): tests use `@pytest.mark.anyio`. Don't add `@pytest.mark.asyncio` to fixed tests — convention is bare anyio.
- **The `ChatMapLayer` import in test_chat_streaming.py** uses dict literal layers, not the Pydantic class. The mock returns these dicts and the router treats them as if they were ChatMapLayer instances — works because the rest of the codepath only attribute-accesses and unpacks. Don't refactor to use the schema class; the tuple-fix (`(layers, None)`) is sufficient.
- **Single-test-per-PR risk:** If executor splits this into many commits, the cluster 2 `dataset_to_ogc_record` code edit could regress sibling passing tests in `TestStacAssetsRemoved` and `TestStacExtensionsRemoved::test_vector_record_no_stac_extensions`. Run all of `tests/test_stac_record_output.py` (full file, ~13 tests) after each cluster 2 code change.

## RESEARCH COMPLETE

**File:** `/Users/ishiland/Code/geolens/.planning/quick/260425-sl1-address-the-debt-in-docs-internal-audits/260425-sl1-RESEARCH.md`
