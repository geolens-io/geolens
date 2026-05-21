---
phase: quick-260323-ees
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/ogc/schemas.py
  - backend/app/ogc/router.py
  - backend/app/search/router.py
  - backend/tests/test_ogc_features.py
autonomous: true
requirements: [OGC-COMPAT-01, OGC-COMPAT-02, OGC-COMPAT-03]

must_haves:
  truths:
    - "OGCLink JSON output omits fields with null values instead of emitting title:null"
    - "/collections response includes self and root links in top-level links array"
    - "/collections/{id}/items self link includes current query parameters (limit, offset, bbox)"
  artifacts:
    - path: "backend/app/ogc/schemas.py"
      provides: "OGCLink model with exclude-none serializer"
      contains: "model_serializer"
    - path: "backend/app/search/router.py"
      provides: "Collections response with populated top-level links"
      contains: "rel.*self"
    - path: "backend/app/ogc/router.py"
      provides: "Items self link with query parameters"
      contains: "offset.*limit"
  key_links:
    - from: "backend/app/ogc/schemas.py"
      to: "all OGC JSON responses"
      via: "OGCLink.model_dump(mode='json') now excludes None"
      pattern: "model_serializer"
    - from: "backend/app/search/router.py"
      to: "/collections endpoint"
      via: "OGCCollectionsResponse links populated"
      pattern: "OGCRecordLink.*self"
---

<objective>
Fix three OGC API Features conformance issues that break QGIS compatibility: null values in link objects, missing top-level links on /collections, and incomplete self links on /items.

Purpose: QGIS cannot load layers from GeoLens OGC endpoints due to non-conformant JSON responses.
Output: Corrected OGC schemas and router logic, verified by existing + new tests.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@backend/app/ogc/schemas.py
@backend/app/ogc/router.py
@backend/app/search/router.py
@backend/tests/test_ogc_features.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix OGCLink null serialization</name>
  <files>backend/app/ogc/schemas.py</files>
  <action>
Add a Pydantic `model_serializer` to the `OGCLink` class that excludes keys with None values from JSON output.

Use `@model_serializer` decorator (from pydantic):
```python
from pydantic import BaseModel, model_serializer

class OGCLink(BaseModel):
    href: str
    rel: str
    type: str
    title: str | None = None

    @model_serializer
    def serialize_model(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}
```

This ensures `model_dump(mode="json")` produces `{"href": "...", "rel": "...", "type": "..."}` without `"title": null` when title is not set.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "from app.ogc.schemas import OGCLink; link = OGCLink(href='/test', rel='self', type='application/json'); d = link.model_dump(mode='json'); assert 'title' not in d, f'title should be absent: {d}'; link2 = OGCLink(href='/test', rel='self', type='application/json', title='My Link'); d2 = link2.model_dump(mode='json'); assert d2['title'] == 'My Link', f'title should be present: {d2}'; print('OK')"</automated>
  </verify>
  <done>OGCLink serialization omits None-valued fields; title present only when explicitly set.</done>
</task>

<task type="auto">
  <name>Task 2: Add top-level links to /collections and fix items self link</name>
  <files>backend/app/search/router.py, backend/app/ogc/router.py</files>
  <action>
**Part A: /collections top-level links** (backend/app/search/router.py)

In the function that builds the OGCCollectionsResponse (around line 869), populate the `links` field before returning. Find the `return OGCCollectionsResponse(collections=...)` call and change it to:

```python
return OGCCollectionsResponse(
    collections=[catalog_collection] + dataset_collections,
    links=[
        OGCRecordLink(
            rel="self",
            href=build_url("/collections", base_url=public_api_url),
            type="application/json",
        ),
        OGCRecordLink(
            rel="root",
            href=build_url("/", base_url=public_api_url),
            type="application/json",
        ),
    ],
)
```

Ensure `build_url` is imported (it should already be imported from `app.ogc.utils`). If not, add the import.

**Part B: Items self link with query params** (backend/app/ogc/router.py)

In the items endpoint (around line 322-328), update the `self` link to include current query parameters. Build a query string from the current limit, offset, and bbox values:

```python
# Build self link with current query params
self_params = f"?limit={limit}&offset={offset}"
if bbox:
    self_params += f"&bbox={bbox}"
links = [
    OGCLink(
        rel="self",
        href=build_url(base_path, base_url=public_api_url) + self_params,
        type="application/geo+json",
    ),
    ...
]
```

Only include bbox in the self link query string if the bbox parameter was provided by the caller.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/test_ogc_features.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>/collections response has self+root links; /items self link reflects current limit/offset/bbox query params.</done>
</task>

<task type="auto">
  <name>Task 3: Add conformance tests for the three fixes</name>
  <files>backend/tests/test_ogc_features.py</files>
  <action>
Add three new test functions to `backend/tests/test_ogc_features.py`:

1. **test_link_objects_omit_null_fields** - Verify that link objects in `/collections/{id}` response do not contain any keys with null values. Iterate all links, assert no value is None.

2. **test_collections_has_top_level_links** - Verify `GET /collections` response includes top-level `links` array with at least `self` and `root` rels. Assert `links` is a non-empty list, extract rels, check both present.

3. **test_items_self_link_includes_query_params** - Verify `GET /collections/{id}/items?limit=2` has a self link whose href contains `limit=2` and `offset=0`. Also test with bbox: `GET /collections/{id}/items?limit=2&bbox=-75,40,-73,41` and verify self link href contains the bbox value.

All three tests use the existing `public_dataset` fixture and follow the existing test patterns in the file.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/test_ogc_features.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>All existing + 3 new OGC Features tests pass, confirming null exclusion, top-level links, and self link query params.</done>
</task>

</tasks>

<verification>
Run full OGC test suite to confirm no regressions:
```bash
cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/test_ogc_features.py backend/tests/test_ogc_records_conformance.py -x -q
```
</verification>

<success_criteria>
- OGCLink JSON output never contains null-valued keys
- GET /collections returns links array with self and root entries
- GET /collections/{id}/items self link includes limit/offset/bbox query params
- All OGC Features tests pass (existing + 3 new)
</success_criteria>

<output>
After completion, create `.planning/quick/260323-ees-verify-ogc-api-features-endpoints-workin/260323-ees-SUMMARY.md`
</output>
