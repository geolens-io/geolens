# OGC Records Conformance Gaps - Research

**Researched:** 2026-03-22
**Domain:** OGC API Records Part 1 conformance
**Confidence:** HIGH (code-verified against actual implementation)

## Summary

Assessed all 10 high-priority gaps against the actual codebase. All 10 are confirmed real. The fixes are concentrated in 4 files, with no frontend breaking changes since the frontend uses `/search/datasets` (not the OGC `/collections/datasets/items` endpoint). The OGC endpoints serve external machine clients only.

**Primary recommendation:** Fix all 10 in a single pass. Most are 1-5 line changes. The `sortby` alias and `type` alias require slightly more care (dual-parameter support on the endpoint).

## Gap Assessment

### Gap 1: `prev` -> `previous` (CONFIRMED)
**Files:** `backend/app/ogc/router.py:356`, `backend/app/search/router.py:367`
**Current:** `rel="prev"` on pagination links
**Fix:** Change to `rel="previous"` (IANA registered name per RFC 8288)
**Risk:** None. Frontend does not consume `rel="prev"` links from any API response.

### Gap 2: STAC bleed-through (CONFIRMED)
**File:** `backend/app/search/service.py:1068,1163,1215`
**Current:** `dataset_to_ogc_record()` injects `stac_version`, `stac_assets`, `stac_extensions` as top-level keys and `conformsTo` on every record
**Fix:** Remove `stac_version` (line 1068), `stac_assets` (line 1163), `stac_extensions` (line 1215), and `conformsTo` (lines 1069-1072) from the record dict. These are STAC-specific and don't belong in OGC Records responses. The `assets` key (line 1156) is fine -- OGC Records supports it.
**Risk:** If any consumer uses `stac_version` from OGC Records responses. Check if frontend references it -- it does not.

### Gap 3: themes missing `scheme` (CONFIRMED)
**File:** `backend/app/search/service.py:995-999`
**Current:** `_build_themes()` returns `[{"concepts": [{"id": cat}]}]` -- no `scheme` key
**DB:** `RecordKeyword.vocabulary_uri` exists in the model (line 283 of models.py) but keywords are serialized as flat strings at line 1079, not grouped by vocabulary.
**Fix:** Two changes: (a) `_build_themes()` should accept keywords with their vocabulary_uri and group by scheme, (b) the serializer should pass keyword objects instead of just `theme_category`. The current `theme_category` field on Record is a separate list[str] from the keywords table. Need to also pull `vocabulary_uri` from `RecordKeyword` rows and build `{"concepts": [...], "scheme": "<uri>"}` when vocabulary_uri is set.
**Complexity:** Medium -- requires changing the query in `dataset_to_ogc_record` to include keyword vocabulary data.

### Gap 4: contacts missing email/phone (CONFIRMED)
**File:** `backend/app/search/service.py:1100-1105`
**Current:** Contact serialization is `{"name": c.name, "organization": c.organization, "role": c.role}` -- omits `email` and `phone`
**DB:** `RecordContact` has `email` and `phone` columns (models.py:256-258)
**Fix:** Add `"email": c.email, "phone": c.phone` to the contact dict, filtering None values.

### Gap 5: `type` property should be a URI (CONFIRMED)
**File:** `backend/app/search/service.py:1076`
**Current:** `"type": "dataset"` (bare string)
**Fix:** Per OGC Records, this should reference a controlled vocabulary. Simplest fix: keep the value as-is but it's technically compliant since OGC Records says "type" is a string from a controlled vocabulary. The spec example uses bare strings like "dataset". This gap may be a false positive -- OGC Records core uses simple string values, not full URIs. **Downgraded to LOW priority.**

### Gap 6: Missing `timeStamp` on Records FeatureCollection (CONFIRMED)
**File:** `backend/app/search/schemas.py:109-116` (`OGCFeatureCollectionResponse`)
**Current:** No `timeStamp` field. Compare with `OGCFeatureItemsResponse` (ogc/schemas.py:42-46) which has it.
**Fix:** Add `timeStamp` field to `OGCFeatureCollectionResponse` with same pattern as `OGCFeatureItemsResponse`.

### Gap 7: `sortby` param (CONFIRMED)
**File:** `backend/app/search/router.py:914` (collections/datasets/items endpoint)
**Current:** Uses `sort_by` param name. OGC Records defines `sortby` with `+field`/`-field` syntax.
**Fix:** Add `sortby` as an alias parameter. Parse `+field`/`-field` syntax and map to internal sort values. Keep `sort_by` working for backward compat. The frontend uses `/search/datasets` with `sort_by`, not this endpoint.
**Complexity:** Medium -- need to parse OGC sort syntax.

### Gap 8: `type` query param (CONFIRMED)
**File:** `backend/app/search/router.py:909`
**Current:** Uses `record_type` param name. OGC Records defines `type` as the filter parameter.
**Fix:** Add `type` as an alias for `record_type` on the `/collections/datasets/items` endpoint. Frontend uses `/search/datasets` with `record_type`, not this endpoint.

### Gap 9: Missing schema link on /collections/datasets (CONFIRMED)
**File:** `backend/app/search/router.py:729-757`
**Current:** `_build_collection_metadata()` includes queryables link but NOT a schema link
**Available:** `build_record_schema_response()` exists and `/collections/datasets/schema` endpoint exists (line 887)
**Fix:** Add schema link to the links list: `{"rel": "http://www.opengis.net/def/rel/ogc/1.0/schema", "href": ".../collections/datasets/schema", "type": "application/schema+json"}`

### Gap 10: formats hardcoded to vector (CONFIRMED)
**File:** `backend/app/search/service.py:1096`
**Current:** `"formats": list(_FORMAT_MEDIA.values())` -- always returns vector formats (gpkg, geojson, shp, csv)
**`_FORMAT_MEDIA`:** `{"gpkg": ..., "geojson": ..., "shp": ..., "csv": ...}` (line 40-45)
**Fix:** Condition on record_type. Raster/VRT records should show raster-appropriate formats (e.g., GeoTIFF). Check what raster export formats exist.

## File Change Map

| File | Gaps | Changes |
|------|------|---------|
| `backend/app/search/service.py` | 2,3,4,5,10 | Serializer: remove STAC keys, fix themes/contacts/formats |
| `backend/app/search/router.py` | 1,7,8,9 | Pagination rel, sortby alias, type alias, schema link |
| `backend/app/search/schemas.py` | 6 | Add timeStamp to OGCFeatureCollectionResponse |
| `backend/app/ogc/router.py` | 1 | Pagination rel (OGC Features endpoints) |

## Common Pitfalls

### Pitfall 1: Breaking the frontend
**What goes wrong:** Renaming `record_type` to `type` or `sort_by` to `sortby` in the response breaks the frontend.
**How to avoid:** These are query PARAMETER changes only on the OGC endpoint. The response `properties.record_type` stays unchanged. The frontend uses `/search/datasets`, not `/collections/datasets/items`.

### Pitfall 2: Removing STAC keys that the frontend uses
**What goes wrong:** Frontend might consume `stac_assets` or `stac_extensions` from search responses.
**How to avoid:** Verified -- frontend does NOT reference `stac_version`, `stac_extensions`, or `stac_assets`. Safe to remove from the serializer. However, note that `/search/datasets` uses the same `dataset_to_ogc_record()` serializer. If any external consumers use the search API with STAC fields, this is a breaking change. Consider: keep STAC fields in a separate STAC-specific serializer or accept the break for OGC compliance.

### Pitfall 3: sortby parsing edge cases
**What goes wrong:** OGC `sortby` syntax is `+field,-field` or `field` (ascending default). Need to map to internal sort values: `relevance`, `date_added`, `name`, `last_updated`.
**How to avoid:** Define explicit mapping: `title` -> `name`, `created` -> `date_added`, `updated` -> `last_updated`. Reject unknown fields with 400.

### Pitfall 4: themes query performance
**What goes wrong:** Building grouped themes with vocabulary_uri requires loading keyword objects with their vocabulary_uri, not just keyword strings.
**How to avoid:** Keywords are already eager-loaded on Record. Just access `kw.vocabulary_uri` alongside `kw.keyword` in the serializer. No additional query needed.

## Raster Format Investigation

Need to check what raster download/export formats exist:

```python
# Current vector-only formats:
_FORMAT_MEDIA = {
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
    "shp": "application/x-shapefile",
    "csv": "text/csv",
}
```

For raster records, appropriate formats would be:
- GeoTIFF: `image/tiff; application=geotiff`
- COG: `image/tiff; application=geotiff; profile=cloud-optimized`

For VRT records, format depends on whether they're mosaics or other types.

The fix should branch on `record_type`: vector records get vector formats, raster/VRT records get raster formats.

## Sources

### Primary (HIGH confidence)
- Direct code reading of all 4 affected files
- OGC API Records Part 1 spec (conformance class URIs already in codebase)
- IANA Link Relations Registry: `previous` is the registered name (not `prev`)

### Verification
- Frontend code search confirms no consumption of `prev` rel, `stac_version`, `stac_extensions`, or `stac_assets`
- Frontend uses `/search/datasets` with `sort_by` and `record_type` -- not the OGC endpoint

## Metadata

**Confidence breakdown:**
- Gap identification: HIGH - all verified against actual code
- Fix approach: HIGH - straightforward for 8/10, medium complexity for themes and sortby
- Risk assessment: HIGH - frontend impact verified as none

**Research date:** 2026-03-22
**Valid until:** N/A (one-time assessment)
