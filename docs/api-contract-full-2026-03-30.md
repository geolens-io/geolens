# API Contract Audit — Full
Generated: 2026-03-30
Stack: FastAPI · Pydantic v2 · SQLAlchemy · PostGIS · pgvector · React Query v5

## Contract Health

| Category           | Audited     | Findings | Blocking |
|--------------------|-------------|----------|----------|
| Schemas            | 24 files    | 17       | 0        |
| Route handlers     | 28 routers  | 30       | 0        |
| OpenAPI spec       | 150+ routes | 36       | 0        |
| React Query        | 14 hooks    | 3        | 0        |
| Breaking changes   | full tree   | 5        | 0        |
| Consistency        | full tree   | ~30      | 0        |

**Overall: no blocking issues.** The API contract is solid — zero Pydantic v1 patterns, zero critical React Query misalignments, zero breaking changes pending. Findings are design improvements and consistency gaps.

---

## Route Inventory

150+ routes across 28 routers. Key domains:

| Domain | Routes | Router files |
|--------|--------|-------------|
| Auth | 10 | `auth/router.py` |
| OAuth | 3 | `auth/oauth/router.py` |
| Datasets | 8 | `datasets/router.py` |
| Datasets Data | 5 | `datasets/router_data.py` |
| Datasets Export | 3 | `datasets/router_export.py` |
| Datasets Metadata | 10 | `datasets/router_metadata.py` |
| Datasets Reupload | 6 | `datasets/router_reupload.py` |
| Datasets VRT | 4 | `datasets/router_vrt.py` |
| Maps | 16 | `maps/router.py` |
| Search | 7 | `search/router.py` |
| Collections | 8 | `collections/router.py` |
| Records | 11 | `records/router.py` |
| Features | 4 | `features/router.py` |
| Ingest | 12 | `ingest/router.py` |
| Export | 1 | `export/router.py` |
| Jobs | 3 | `jobs/router.py` |
| Admin | 16 | `admin/router.py` |
| AI | 8 | `ai/router.py` |
| Settings | 16 | `settings/router.py` |
| Tiles | 4 | `tiles/router.py` |
| Embed Tokens | 4+2 | `embed_tokens/router.py`, `admin_router.py` |
| Config Ops | 4 | `config_ops/router.py` |
| OGC | 5 | `ogc/router.py` |
| STAC | 5+ | `stac/router.py` |
| Services | 2 | `services/router.py` |
| Layers | 3 | `layers/router.py` |
| Health | 1 | `main.py` |
| Audit | 2 | `audit/router.py` |

---

## Breaking Changes

**None pending.** The working tree is clean against `main`.

### Versioning Strategy: [VERSION-MISSING]

No API versioning exists. All routers mount at bare prefixes (`/datasets`, `/maps`, etc.) with no `/v1/` segment and no header-based versioning. The app version `12.3.0` is informational metadata in the OpenAPI spec only.

**Recommendation:** Before the next breaking change to any public-facing endpoint (OGC, STAC, search), introduce URL-based versioning or at minimum document the current surface as v1.

### Schema Evolution Risks

| Risk | Location | Severity |
|------|----------|----------|
| Tile token `kind` discriminated union (`"vector" \| "raster"`) — adding a new type breaks exhaustive client switches | `tiles/schemas.py:7,15` | Medium |
| `record_type` is untyped `str` — new types invisible to clients with type-specific logic | `datasets/schemas.py:133`, `search/schemas.py:56` | Medium |
| `visibility` is raw `str` in responses despite `MapVisibility` and `DatasetVisibility` enums existing | `datasets/schemas.py:114`, `maps/schemas.py:86` | Low-Medium |

---

## Findings by Severity

### High — Missing Response Models (14 routes)

Routes returning JSON without `response_model=` produce incomplete OpenAPI docs and risk leaking internal fields.

| # | Route | File:Line | Fix |
|---|-------|-----------|-----|
| 1 | `GET /{dataset_id}/maps/` | `datasets/router_data.py:152` | Add `response_model=MapListResponse` |
| 2 | `PATCH /{dataset_id}/status` | `datasets/router_data.py:183` | Create `StatusUpdateResponse` schema |
| 3 | `GET /{dataset_id}/relationships/` | `datasets/router_metadata.py:320` | Add `response_model=list[DatasetRelationshipResponse]` |
| 4 | `POST /{dataset_id}/relationships/` | `datasets/router_metadata.py:340` | Add `response_model=DatasetRelationshipResponse` |
| 5 | `DELETE /relationships/{rel_id}/` | `datasets/router_metadata.py:360` | Add `-> Response` return type |
| 6 | `GET /{dataset_id}/features/.../related/` | `datasets/router_metadata.py:376` | Add response_model |
| 7 | `POST /cleanup/stale/` | `jobs/router.py:27` | Create `StaleCleanupResponse` schema |
| 8 | `GET /search/facets` | `search/router.py:412` | Create `FacetCountsResponse` schema |
| 9 | `GET /stac/collections/{id}` | `stac/router.py:306` | Add `response_model=dict` or typed schema |
| 10 | `GET /stac/items/{id}` | `stac/router.py:367` | Add `response_model=dict` or typed schema |
| 11-16 | 9 settings endpoints | `settings/router.py:54,89,188,355,362,372,394,403,411` | Add `response_model=` to each |

### High — Untyped GeoJSON in OpenAPI (8 locations)

Geometry fields typed as `dict | None` produce `{}` in the OpenAPI spec. Clients have no type information.

| # | Schema | File:Line | Field |
|---|--------|-----------|-------|
| 1 | `OGCSingleFeatureResponse.geometry` | `ogc/schemas.py:63` | `dict \| None` |
| 2 | `OGCFeatureItemsResponse.features` | `ogc/schemas.py:53` | `list[dict]` |
| 3 | `GeoJSONFeature.geometry` | `features/schemas.py:13` | `dict \| None` |
| 4 | `FeatureCreate.geometry` | `features/schemas.py:35` | `dict` |
| 5 | `FeatureReplace.geometry` | `features/schemas.py:41` | `dict` |
| 6 | `OGCRecordResponse.geometry` | `search/schemas.py:104` | `dict \| None` |
| 7 | `StacItemCollection.features` | `stac/schemas.py:39` | `list[dict]` |
| 8 | `StacCollectionListResponse.collections` | `stac/schemas.py:47` | `list[dict]` |

**Fix:** Define shared typed GeoJSON schemas:
```python
class GeoJSONGeometry(BaseModel):
    type: str  # "Point", "Polygon", etc.
    coordinates: list

class GeoJSONFeature(BaseModel):
    type: Literal["Feature"]
    geometry: GeoJSONGeometry | None
    properties: dict[str, Any]
```

### High — Missing OpenAPI Tag Declarations (8 tags)

Tags are used in routers but not declared in `_OPENAPI_TAGS` in `main.py`, so they appear ungrouped at the bottom of Swagger UI with no description.

| Tag | Router |
|-----|--------|
| `config-ops` | `config_ops/router.py` |
| `Admin Embed Tokens` | `embed_tokens/admin_router.py` |
| `Embed Tokens` | `embed_tokens/router.py` |
| `Tiles` | `tiles/router.py` |
| `STAC` | `stac/router.py` |
| `Datasets - Export` | `datasets/router_export.py` |
| `Datasets - Data` | `datasets/router_data.py` |
| `Datasets - Metadata` | `datasets/router_metadata.py` |

**Fix:** Add all 8 to `_OPENAPI_TAGS` in `backend/app/main.py`.

### Medium — Missing Field Validators (15 schemas)

Input schemas accepting dangerous/unbounded values at the contract boundary.

| # | Field | File:Line | Fix |
|---|-------|-----------|-----|
| 1 | `email` as bare `str` (5 locations) | `auth/schemas.py:17`, `admin/schemas.py:16,39`, `records/schemas.py:15,25` | Use `EmailStr` |
| 2 | `visibility` as bare `str` (6 locations) | `datasets/schemas.py:47,181`, `ingest/schemas.py:50,74,98,163` | Use `Literal["private","internal","public"]` |
| 3 | `name` with no length constraint | `collections/schemas.py:10`, `maps/schemas.py:30`, `search/schemas.py:140`, `admin/schemas.py:141` | Add `Field(min_length=1, max_length=255)` |
| 4 | `opacity` with no bounds | `maps/schemas.py:18` | Add `Field(ge=0.0, le=1.0)` |
| 5 | `file_size` accepts negatives | `ingest/schemas.py:124` | Add `Field(ge=1)` |
| 6 | `allowed_origins` list unbounded | `embed_tokens/schemas.py:43` | Add `Field(max_length=50)` |
| 7 | `token_ids` list unbounded | `embed_tokens/schemas.py:96` | Add `Field(max_length=100)` |
| 8 | `dataset_ids` list unbounded | `collections/schemas.py:47` | Add `Field(max_length=100)` |
| 9 | `OAuth client_id/secret` accept empty | `auth/oauth/schemas.py:16-17` | Add `Field(min_length=1)` |
| 10 | `CommitRequest.title` no constraint | `ingest/schemas.py:48` | Add `Field(min_length=1, max_length=500)` |

### Medium — Status Code Semantics (5 routes)

Async job endpoints returning 200 instead of 202 Accepted.

| Route | File:Line | Current | Should Be |
|-------|-----------|---------|-----------|
| `POST /{dataset_id}/reupload/commit` | `datasets/router_reupload.py:283` | 200 | 202 |
| `POST /ingest/commit/{job_id}` | `ingest/router.py:418` | 200 | 202 |
| `POST /jobs/{job_id}/retry` | `jobs/router.py:150` | 200 | 202 |
| `DELETE /embed-tokens/{id}/` | `embed_tokens/router.py:144` | 200 (body) | 204 (no body) or keep as-is |
| `DELETE /layers/.../columns/...` | `layers/router.py:133` | 200 (body) | 204 or keep as-is |

### Medium — Trailing Slash Inconsistency (~20+ routes)

The established convention is: **collection endpoints get trailing slashes, single-resource/action endpoints do not**. However, there are widespread deviations in both directions across `datasets/`, `maps/`, `admin/`, `collections/`, and `auth/` routers. Given the documented FastAPI 307 redirect issue, this is a real client concern.

**Key deviations** (sample):
- `datasets/router_data.py`: `/{id}/related/` (slash) vs `/{id}/rows` (no slash) vs `/{id}/status` (no slash)
- `admin/router.py`: `GET /api-keys/` (slash) vs `DELETE /api-keys/{key_id}` (no slash)
- `collections/router.py`: `POST /{id}/datasets` (no slash) vs `GET /` (slash)

**Recommendation:** Dedicate a sweep to normalize all routes to one convention, coordinated with frontend URL updates.

### Medium — Pagination Inconsistency (3 routes)

Established convention: `skip` + `limit` with `Query()` constraints.

| Route | File:Line | Uses | Convention |
|-------|-----------|------|-----------|
| Features list | `features/router.py:64` | `offset`/`limit` | `skip`/`limit` |
| VRT generations | `datasets/router_vrt.py:224` | `offset`/`limit` | `skip`/`limit` |
| Maps list | `maps/router.py:162` | bare `skip=0, limit=20` | `Query(0, ge=0)`, `Query(50, ge=1, le=200)` |

### Medium — Bare List Returns (5 endpoints)

These return bare JSON arrays without envelopes, breaking pagination extensibility:

| Endpoint | File:Line |
|----------|-----------|
| `GET /settings/oauth-providers/` | `settings/router.py:254` |
| `GET /auth/oauth/providers/` | `auth/oauth/router.py:145` |
| `GET /settings/basemaps/` | `settings/router.py:372` |
| `GET /settings/enabled-widgets/` | `settings/router.py:403` |
| `GET /admin/users/names/` | `admin/router.py:113` |

### Low — Missing OpenAPI Examples (5 schema families)

Core consumer-facing schemas lack `json_schema_extra` examples: OGC, STAC, Search, Auth, Dataset response schemas. Swagger UI forms are empty.

### Low — Structured Error Detail (2 routes)

`datasets/router.py:481` and `maps/router.py:314` return `detail` as a dict (`{"message": ..., "datasets": ...}`) instead of the established `detail: string` convention. Not a bug — arguably better — but inconsistent.

### Low — Duplicate Schema

`admin/schemas.py:144-148` defines `AdminApiKeyCreateResponse` identical to `auth/schemas.py:58-63` `ApiKeyCreateResponse`. Deduplicate by importing from `auth/schemas.py`.

### Low — Dead Schema Field

`search/schemas.py:27` — `SearchParams.bbox_parsed: list[float] | None` is unused (bbox is parsed inline in the router). Remove the field.

---

## React Query Alignment

**Zero critical issues.** The frontend hooks are well-aligned with the backend:

- All hook URLs match real backend routes (including trailing slash handling)
- HTTP methods match (PATCH for partial updates, PUT for full replacements)
- Query keys are consistent via centralized `queryKeys` factory
- Error shape is correct (`body.detail` matching FastAPI convention)
- Mutation invalidation is thorough

**Minor notes:**
- `useReuploadCommit`, `useCommitImport`, `useCreateVrt` lack `onSuccess` invalidation — by design, since they start background jobs and the job polling hook handles cache refresh.
- `datasets.detail` uses different root key (`['dataset', id]`) from `datasets.all` (`['datasets']`) — documented and all mutations correctly handle both.

---

## Consistency Reference Card

The canonical conventions established for this API:

| Convention | Standard | Notes |
|-----------|----------|-------|
| **Path casing** | kebab-case | `api-keys`, `embed-tokens`, `config-ops` |
| **Path segments** | Plural nouns | `/datasets`, `/maps`, `/collections` |
| **ID params** | `{resource_name_id}` | `dataset_id`, `map_id`, `collection_id` |
| **Pagination** | `skip` + `limit` with `Query()` | `skip: int = Query(0, ge=0)`, `limit: int = Query(50, ge=1, le=200)` |
| **List envelope** | `{items_key: [], total: int}` | Key matches resource name (`datasets`, `maps`, etc.) |
| **Error format** | `{"detail": "string"}` | FastAPI default `HTTPException` |
| **Timestamps** | ISO 8601 UTC | Pydantic v2 default serialization |
| **Coordinate order** | `[longitude, latitude]` | GeoJSON standard; `ST_MakePoint(lng, lat)` |
| **Bbox format** | `minx,miny,maxx,maxy` | = `west,south,east,north` (WGS84) |
| **Auth header** | `Authorization: Bearer {token}` | Fallback: `X-Api-Key` header > `?api_key=` query > JWT |
| **Status codes** | 200 GET/PATCH, 201 POST, 202 async, 204 DELETE | Use `status.HTTP_*` constants |
| **Trailing slashes** | Mixed (needs normalization) | Collection endpoints: slash; resource/action: no slash |
| **Pydantic version** | v2 (fully migrated) | `ConfigDict`, `field_validator`, `model_dump` |

---

## Recommended Fix Priority

### Batch 1 — Single-file, high-impact
1. Add 8 missing tags to `_OPENAPI_TAGS` in `main.py` (fixes Swagger grouping for ~30 routes)
2. Add `Field()` validators to 15 input schemas (boundary validation)

### Batch 2 — Response model gaps
3. Add `response_model=` to 14 routes missing them
4. Create 4-5 small response schemas for bare dict returns

### Batch 3 — Semantic correctness
5. Change 3 async job routes from 200 to 202
6. Normalize pagination params (`offset` → `skip`, add `Query()` constraints)

### Batch 4 — Contract quality (coordinate with frontend)
7. Trailing slash normalization sweep
8. Define typed GeoJSON schemas for 8 geometry fields
9. Wrap 5 bare list endpoints in envelopes

### Batch 5 — Long-term
10. Introduce API versioning strategy before next breaking change
11. Add `json_schema_extra` examples to core schemas
12. Constrain `record_type` and `visibility` response fields with Literal types
