---
phase: 1057-service-url-reliability
review_date: 2026-05-19
depth: standard
files_reviewed: 14
files_reviewed_list:
  - backend/app/modules/catalog/sources/adapters/ogcapi.py
  - backend/app/modules/catalog/sources/adapters/wfs.py
  - backend/app/modules/catalog/sources/classify.py
  - backend/app/modules/catalog/sources/crs_uri.py
  - backend/app/modules/catalog/sources/probe.py
  - backend/app/modules/catalog/sources/schemas.py
  - backend/app/processing/ingest/ogr.py
  - backend/tests/test_crs_uri_parsing.py
  - backend/tests/test_probe_classification.py
  - backend/tests/test_services_wfs_pure.py
  - frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx
  - frontend/src/components/import/ImportMetadataForm.tsx
  - frontend/src/components/import/ServiceUrlForm.tsx
  - frontend/src/types/api.ts
status: clean
critical: 0
warning: 3
info: 3
---

# Phase 1057: Code Review Report

**Reviewed:** 2026-05-19T00:00:00Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 1057 delivers three well-scoped fixes: `-nlt GEOMETRY` for the WFS abstract-type ingest failure (Plan 01), ogrinfo enrichment removal + `kind` classification (Plan 02), and URI/URN CRS parsing (Plan 03). The core logic is sound — regex anchoring in `crs_uri.py` is tight, the D-09 classification rule is faithfully implemented, and the enrichment deletion is clean with no dangling imports. No critical issues found. Three warnings and three info items identified below.

## Warnings

### WR-01: `_build_arcgis_response` omits `classify_layer_kind`, silently hardcodes `kind='vector'` for all ArcGIS layers

**File:** `backend/app/modules/catalog/sources/probe.py:85-109`

**Issue:** `_build_arcgis_response` constructs `LayerInfo` objects without passing `kind`, relying entirely on the Pydantic field default `'vector'`. The D-09 raster signals (coverage_format, bands, image/* links) in the raw ArcGIS layer dict are never evaluated. This is inconsistent with the OGC API path (which calls `classify_layer_kind`). While ArcGIS FeatureServer layers are nearly always vector, this silently skips the classification contract introduced by CLASS-07.

**Fix:** Call `classify_layer_kind` when building ArcGIS `LayerInfo`, consistent with the OGC API adapter:

```python
from app.modules.catalog.sources.classify import classify_layer_kind

layers = [
    LayerInfo(
        name=layer["name"],
        title=layer.get("title"),
        geometry_type=layer.get("geometry_type"),
        feature_count=layer.get("feature_count"),
        layer_type=layer.get("type", "layer"),
        layer_id=layer.get("id"),
        object_id_field=layer.get("object_id_field"),
        kind=classify_layer_kind(layer, adapter_type="arcgis"),
    )
    for layer in enriched_layers
]
```

---

### WR-02: `test_large_epsg_code_returns_int` assertion is vacuously true — does not pin actual behavior

**File:** `backend/tests/test_crs_uri_parsing.py:108-118`

**Issue:** The assertion `assert result is None or isinstance(result, int)` passes whether the function returns `None` or any integer. The implementation `int("99999999999999999999")` unambiguously returns the large integer (Python has arbitrary-precision integers and the regex `\d+` matches the full string). The test should assert the concrete return value. As written, the test would also pass if `parse_crs_uri` returned `None` for any reason, hiding a regression.

**Fix:** Pin the actual return value:

```python
result = parse_crs_uri("http://www.opengis.net/def/crs/EPSG/0/99999999999999999999")
assert result == 99999999999999999999
```

The docstring note about "None is also acceptable if executor chose a cap" contradicts the implementation — the regex allows any `\d+` with no cap. Remove the ambiguity by asserting the concrete value.

---

### WR-03: `test_populates_x_y_dropdowns_with_numeric_columns_only` test body has no assertions — dead test

**File:** `frontend/src/components/import/__tests__/ImportMetadataForm.test.tsx:389-401`

**Issue:** The test renders the component with a `null`-detection fixture but the body ends with a comment explaining what needs to happen ("We need to switch mode to manual first") without actually doing it. The test has zero assertions and passes unconditionally — it cannot catch regressions in the numeric-column filter logic.

**Fix:** Complete the test by switching to manual mode and asserting column options:

```tsx
it('populates x/y dropdowns with numeric columns only', async () => {
  const user = userEvent.setup();
  render(
    <ImportMetadataForm
      {...defaultProps}
      previewColumns={sampleColumns}
      detectedGeometryColumns={{ x_column: null, y_column: null, wkt_column: null }}
    />,
  );

  const modeSelect = screen.getByLabelText('metadata.geometryMode');
  await user.selectOptions(modeSelect, 'manual');

  const xSelect = screen.getByLabelText('metadata.xColumn');
  const options = within(xSelect).getAllByRole('option').map((o) => (o as HTMLOptionElement).value);
  expect(options).toContain('Latitude');
  expect(options).toContain('Longitude');
  expect(options).not.toContain('name');  // String type excluded
});
```

---

## Info

### IN-01: Redundant `_looks_like_arcgis` call in `detect_service_type` slow path

**File:** `backend/app/modules/catalog/sources/probe.py:138`

**Issue:** Line 138 re-evaluates `not _looks_like_arcgis(url)` even though the condition is only reached when line 124's `if _looks_like_arcgis(url)` was either false or its fast-path fell through. The guard `if not _looks_like_arcgis(url) and _looks_like_wfs(url)` is logically correct (prevents double-probing a URL that looks like both ArcGIS and WFS) but calls `_looks_like_arcgis` twice. The function is cheap (string contains) so this is not a correctness issue, just unnecessary duplication.

**Fix:** Extract the result to a local variable at the top of `detect_service_type`:

```python
looks_arcgis = _looks_like_arcgis(url)
looks_wfs = _looks_like_wfs(url)
```

---

### IN-02: `classify_layer_kind` docstring names `mediaType` but code reads `type` key — comment mismatch

**File:** `backend/app/modules/catalog/sources/classify.py:67`

**Issue:** The comment on line 67 says "# Rule 5: Any link with a mediaType starting with 'image/'." but the implementation at line 72 reads `link.get("type", "")`. In OGC API link objects, the media type is carried in the `type` field (not `mediaType`), so the implementation is correct. The comment uses the semantic name from D-09 rather than the JSON key, which is misleading for future readers.

**Fix:** Correct the comment to match the key:

```python
# Rule 5: Any link with a 'type' field starting with 'image/' (OGC API link media type).
```

---

### IN-03: `test_enrich_ogcapi_layers_not_called` marked `@pytest.mark.anyio` but is synchronous

**File:** `backend/tests/test_probe_classification.py:317-330`

**Issue:** The test function is declared `async def` with no `await` inside. The `@pytest.mark.anyio` marker causes anyio to schedule it as a coroutine, but since it does no I/O, the only effect is unnecessary anyio overhead. This is a style inconsistency — synchronous structural assertions should use `def`, not `async def`.

**Fix:** Drop the `@pytest.mark.anyio` marker and the `async` keyword:

```python
def test_enrich_ogcapi_layers_not_called(self):
    import app.modules.catalog.sources.probe as probe_module
    assert not hasattr(probe_module, "enrich_ogcapi_layers"), ...
```

---

_Reviewed: 2026-05-19T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Fixes Applied

All 6 findings fixed inline (2026-05-19). Each committed atomically.

| Finding | Commit | Description |
|---------|--------|-------------|
| WR-01 | cdb25362 | Added `classify_layer_kind(layer, adapter_type="arcgis")` to `_build_arcgis_response`; imported `classify_layer_kind` in `probe.py` |
| WR-02 | 80bfb694 | Replaced vacuous `result is None or isinstance(result, int)` with `result == 99999999999999999999`; removed contradicting docstring note |
| WR-03 | 299097d5 | Completed dead test: switch to manual mode, assert numeric columns present (id, Latitude, Longitude) and string columns excluded (name, wkt) |
| IN-01 | 5c7f9572 | Extracted `looks_arcgis = _looks_like_arcgis(url)` and `looks_wfs = _looks_like_wfs(url)` locals at `detect_service_type` start; replaced three call sites |
| IN-02 | 0da9aa96 | Changed comment from `mediaType` to `'type' field` to match actual `link.get("type")` code |
| IN-03 | c0ba7c3b | Dropped `@pytest.mark.anyio` decorator and `async` keyword from `test_enrich_ogcapi_layers_not_called` |

Post-fix test results: backend 65/65 pass (`test_crs_uri_parsing`, `test_probe_classification`, `test_ingest_service_geometry_type`, `test_services_wfs_pure`); frontend 27/27 pass (`ImportMetadataForm`).
