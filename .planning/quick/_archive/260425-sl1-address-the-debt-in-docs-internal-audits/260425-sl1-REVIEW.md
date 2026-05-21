---
phase: 260425-sl1-address-the-debt-in-docs-internal-audits
reviewed: 2026-04-25T00:00:00Z
depth: quick
files_reviewed: 9
files_reviewed_list:
  - backend/app/modules/catalog/search/service.py
  - backend/pyproject.toml
  - backend/tests/test_stac_record_output.py
  - backend/tests/test_ai_chat.py
  - backend/tests/test_chat_streaming.py
  - backend/tests/test_ogc_collection_metadata.py
  - backend/tests/test_ogc_features.py
  - backend/tests/test_search.py
  - backend/tests/test_public_urls.py
findings:
  critical: 2
  warning: 3
  info: 1
  total: 6
status: issues_found
---

# Quick Task 260425-sl1: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** quick
**Files Reviewed:** 9 (uv.lock pin verified separately — freezegun==1.5.5)
**Status:** issues_found

## Summary

Of the six fix clusters, two are correct (cluster 1 STAC datetime fallback, cluster 3 chat tuple unpack), three have issues that range from "didn't actually fix what the audit identified" (cluster 5 freezegun) to "shipped a regression alongside the test fix" (cluster 2 STAC extension), and the rest are partial mitigations.

The most serious finding is **CR-01**: cluster 2 didn't just remove a leak — it removed the *only* code path that declared the `projection` STAC extension on raster items emitted by the STAC API. The `dataset_to_ogc_record` output is consumed by both the OGC Records router AND the STAC router (via `ogc_record_to_stac_item`, which reads `record.get("stac_extensions")`). Raster STAC items now ship `proj:epsg`/`proj:shape`/`gsd` properties without declaring the extension URI — a STAC 1.0 spec violation.

The second is **CR-02**: cluster 5's freezegun usage is a no-op. `with freeze_time(datetime.now(timezone.utc))` evaluates `datetime.now()` *before* the freeze activates, so freezing to "right now" then asking for `date.today()` is identical to calling `date.today()` with no freeze at all. The midnight-UTC race the audit observed is unaddressed.

## Critical Issues

### CR-01: Cluster 2 fix removes STAC projection extension declaration from raster STAC items

**File:** `backend/app/modules/catalog/search/service.py:1219-1223` (removed block)
**Issue:**
The removed block was the only write site that put `stac_extensions` onto the OGC record dict produced by `dataset_to_ogc_record`. That dict is consumed in two places:

1. **OGC Records router** — where the test `test_raster_record_no_stac_extensions` correctly asserts `stac_extensions` is absent (OGC Records spec doesn't define this key). Removing the leak here is the right call.
2. **STAC router** at `backend/app/standards/stac/router.py:179-216` — `_dataset_to_stac_item` calls `dataset_to_ogc_record(...)` then passes the result to `ogc_record_to_stac_item`. The STAC serializer at `backend/app/standards/stac/serializer.py:133-134` reads `record.get("stac_extensions")` and copies it onto the STAC item.

After this change, raster STAC items emitted at `/api/stac/...` still contain `proj:epsg`, `proj:shape`, and `gsd` properties (lines 1201-1215 are untouched), but no longer declare the projection extension URI. Per STAC 1.0, items that use extension-namespaced fields MUST declare the extension URL in `stac_extensions`. PySTAC validators and stricter STAC clients will reject these items.

The unit test at `backend/tests/test_stac_serializer.py:179-186` (`test_stac_extensions_included`) shows the serializer correctly *propagates* `stac_extensions` when present — the regression is upstream, in the OGC record producer no longer setting it.

**Fix:**
Decouple OGC vs STAC output. Two viable options:

```python
# Option A: keep the leak source intact, strip stac_extensions in the OGC Records path only.
# In backend/app/modules/catalog/search/service.py — restore the removed block.
# Then in the OGC Records emitter (router.py around the FeatureCollection assembly),
# pop stac_extensions before returning to OGC clients:
ogc_record.pop("stac_extensions", None)

# Option B: have _dataset_to_stac_item add stac_extensions itself for raster/vrt items
# in backend/app/standards/stac/router.py:_dataset_to_stac_item, after building ogc_record:
record_type = getattr(dataset.record, "record_type", "vector_dataset") or "vector_dataset"
if raster_meta and record_type in ("raster_dataset", "vrt_dataset"):
    has_proj = (
        raster_meta.get("epsg") is not None
        or (raster_meta.get("width") and raster_meta.get("height"))
    )
    if has_proj:
        ogc_record.setdefault("stac_extensions", []).append(
            "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
        )
```

Option B is cleaner because the OGC record builder has no remaining business setting STAC-extension URIs. Add a STAC-side regression test in `test_stac_integration.py` that asserts `proj:epsg in item["properties"]` implies `any("projection" in u for u in item["stac_extensions"])`.

---

### CR-02: Cluster 5 freezegun usage does not actually freeze anything

**File:** `backend/tests/test_search.py:414-416`
**Issue:**
```python
with freeze_time(datetime.now(timezone.utc)):
    today = date.today()
yesterday = today - timedelta(days=1)
tomorrow = today + timedelta(days=1)
```
`datetime.now(timezone.utc)` is evaluated **before** the `with` block enters and freeze is applied. So the freeze instant is "real wall-clock at expression evaluation," and `date.today()` inside the block returns the local date for that instant — identical to calling `date.today()` with no freeze. The midnight-UTC boundary race the audit identified is unaddressed: at 23:59:59.9 UTC this still produces a `today` that may be off-by-one relative to Postgres NOW() captured 0.2s later.

The doctring's own claim ("kills the midnight-UTC boundary race") is contradicted by the implementation. The test file even acknowledges in the docstring that "Postgres NOW() is unaffected (server-side), so created_at timestamps match real wall-clock; yesterday and tomorrow now bracket the freeze instant deterministically" — but the freeze instant is never set to anything stable, so the bracket is just as race-prone as before.

**Fix:**
Use `datetime.now(timezone.utc).date()` directly so `today` is derived from the same UTC clock that Postgres `NOW()` uses, and widen the bracket by one day on each side to absorb any clock skew:

```python
# Use UTC date (not local date) to match Postgres NOW() server-side timezone
today_utc = datetime.now(timezone.utc).date()
yesterday = today_utc - timedelta(days=1)
tomorrow = today_utc + timedelta(days=1)
```

If the goal really is to use `freeze_time`, the freeze-point must be a stable literal (e.g. `freeze_time("2026-04-25T12:00:00Z")`) AND the test fixtures need to insert rows whose `created_at` is set inside the freeze (which won't work with Postgres `server_default=NOW()` — server side is unfrozen). So freeze_time is the wrong tool here; remove the import and the `with` block.

## Warnings

### WR-01: Cluster 2 leaves dead code (`has_proj` flag) behind

**File:** `backend/app/modules/catalog/search/service.py:1199, 1202, 1208`
**Issue:**
Removing the `if has_proj:` block deleted the only consumer of the `has_proj` local variable, but the assignments `has_proj = False` (line 1199) and `has_proj = True` (lines 1202, 1208) remain. The flag is now dead code that misleads future readers into thinking it's still consumed.
**Fix:**
After fixing CR-01 by relocating the extension-URI logic, either keep `has_proj` (if the STAC side needs it) or delete all three assignments:

```python
if raster_meta and record_type in ("raster_dataset", "vrt_dataset"):
    if raster_meta.get("epsg") is not None:
        ogc_record["properties"]["proj:epsg"] = raster_meta["epsg"]
    if raster_meta.get("width") and raster_meta.get("height"):
        ogc_record["properties"]["proj:shape"] = [
            raster_meta["height"],
            raster_meta["width"],
        ]
    # ... rest unchanged
```

---

### WR-02: Cluster 6 fix mutates module global with no teardown — pollutes other tests

**File:** `backend/tests/test_public_urls.py:213`
**Issue:**
```python
public_urls._PUBLIC_URL_CACHE = None
```
The fix sets the cache to `None` at the start of the test (correctly addressing the audit's pollution-in failure mode), but then runs `_load_public_url_overrides(db)` which sets `_PUBLIC_URL_CACHE = (now, overrides)` at line 195 of `app/core/public_urls.py`. After the test completes, the cache is left populated with the *test's* `AsyncMock` data:

```python
{
    PUBLIC_APP_URL_KEY: "https://catalog.example.com",
    PUBLIC_API_URL_KEY: "https://catalog.example.com/api",
    LEGACY_PUBLIC_API_URL_KEY: None,
}
```

This persists for ~60 seconds (`_PUBLIC_URL_CACHE_TTL`). Any subsequent test in the same pytest session that triggers `get_public_urls()` via an HTTP call (which is essentially every integration test, since every URL-building helper goes through this path) will see these stale overrides instead of the real DB-backed values — pollution-out. The test fixed inbound pollution but introduced outbound pollution.

`conftest.py` has no fixture that resets `_PUBLIC_URL_CACHE`, and the only other test file touching public_urls (`test_settings_router.py`) bypasses the cache by patching `get_public_app_url` directly, so the leakage might be invisible at the suite level depending on test ordering.

**Fix:**
Wrap the mutation in a try/finally or use a fixture that resets after:

```python
@pytest.mark.anyio
async def test_load_public_url_overrides_unwraps_json_values() -> None:
    public_urls._PUBLIC_URL_CACHE = None
    try:
        db = AsyncMock()
        # ... existing test body ...
    finally:
        public_urls._PUBLIC_URL_CACHE = None
```

Better: lift it into an autouse module-scoped fixture so all tests in this file get clean cache behavior:

```python
@pytest.fixture(autouse=True)
def _reset_public_url_cache():
    public_urls._PUBLIC_URL_CACHE = None
    yield
    public_urls._PUBLIC_URL_CACHE = None
```

Best: move the same fixture to `conftest.py` so the rest of the suite is also protected from the inbound pollution that originally caused the audit's `cluster 6` failure (the audit itself notes "earlier tests are leaving DB/cache state that breaks this one" — the *cause* is unfixed).

---

### WR-03: Cluster 4 `limit=200` is a brittle ceiling, not a fix

**File:** `backend/tests/test_ogc_collection_metadata.py:383, 418`; `backend/tests/test_ogc_features.py:148`
**Issue:**
The `/collections` endpoint (`backend/app/modules/catalog/search/router.py:980-982`) caps `limit` at 200 (`Query(50, ge=1, le=200)`). The fix sets `limit=200` — the maximum allowed. The test DB persists across the pytest session (`backend/tests/conftest.py:328-346` documents this as known tech debt), and the suite has 50+ files that create datasets without `clean_tables` cleanup. As soon as the test DB accumulates more than ~200 datasets, the per-dataset entry being asserted (e.g. `str(public_dataset.id)`) may fall off the page and the test fails again — same failure mode the audit caught, just delayed.

The audit cluster 4 root cause was test-DB pagination overflow; the fix should query the per-dataset entry deterministically, not raise the ceiling.

**Fix:**
Either (a) query the specific dataset directly via `/collections/{ds.id}` and assert the per-dataset entry's shape there (simpler, deterministic), or (b) page through `/collections` collecting all entries:

```python
# Option (a) — deterministic, single request:
resp = await client.get(f"/collections/{ds.id}")
assert resp.status_code == 200
entry = resp.json()
# ... existing assertions on entry["extent"], entry["links"], etc.
```

For `test_collections_includes_dataset_collections` where the assertion is "this id appears in the list," either pass a `q` filter (if the endpoint supports one) or page through with `offset` until found.

## Info

### IN-01: Cluster 1 test name is now misleading

**File:** `backend/tests/test_stac_record_output.py:116`
**Issue:**
The test was renamed from `test_datetime_null_when_no_temporal` to `test_datetime_falls_back_to_created_at_when_no_temporal` (good — describes new behavior), but the surrounding class is still `TestStacDatetime` and the file's module docstring at line 1-13 says it verifies "properties.datetime follows STAC 1.0.0 rules". STAC 1.0.0 does permit `datetime` to be null when no temporal info exists, so the docstring is slightly misleading now that we've chosen the defensive validation path over strict STAC compliance.
**Fix:**
Update the module docstring at line 4 to reflect the actual contract:

```python
"""Integration tests for record output fields.

Verifies:
  - properties.datetime follows STAC 1.0.0 rules with a defensive fallback
    to created_at when no temporal info exists (audit 20260425 cluster 1)
  - STAC-specific keys (stac_version, stac_extensions, stac_assets) are NOT
    present in OGC Records responses
  - ...
"""
```

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
