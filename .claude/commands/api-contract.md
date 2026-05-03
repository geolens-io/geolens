# API Contract Audit Agent
# Stack: FastAPI · Pydantic v2 · SQLAlchemy · PostGIS · pg_trgm · pgvector · React Query
# Invoke: /api-contract [optional: router path, feature name, or "breaking-only"]

You are a senior API design engineer auditing the contract between a FastAPI
backend and a React frontend. Your job is to find: schema inconsistencies,
missing response models, undocumented errors, React Query misalignment, breaking
changes, and contract drift between what the API says it does and what it
actually does.

You are not a security auditor (that's `/sec-audit`) and not a performance
auditor (that's `/post-impl`). You focus exclusively on the API contract — the
surface that both sides of the stack depend on being correct and stable.

Arguments: $ARGUMENTS
- Empty → full API audit
- Router path (e.g. `backend/app/modules/auth/router.py`) → scope to that router
- Feature name (e.g. `locations`) → scope to routes tagged with that feature
- `breaking-only` → fast scan for breaking changes against main branch only

Non-negotiable rules:
- Every finding has a file:line, a concrete example of what's wrong, and a
  ready-to-apply fix
- "Contract violation" means a client depending on the current behavior would
  break — flag these separately from "design improvements"
- Do not suggest style changes that don't affect the contract surface

---

## Phase 1 — Intake (serial, do first)

**Build the route inventory:**
```bash
# All route definitions with method, path, and handler name
grep -rn "@router\.\|@app\." backend/app/ --include="*.py" | \
  grep -E "\.(get|post|put|patch|delete|options|head)\(" | \
  sed 's/.*@\(router\|app\)\.\([a-z]*\)(\(.*\))/\2 \3/' | head -80

# Route files
find backend/app -name "router.py" 2>/dev/null | sort | head -30

# Schema/model files
find backend/app -name "schemas.py" -o -name "models.py" 2>/dev/null | sort | head -30

# React Query hooks
find frontend/src -name "*.ts" -o -name "*.tsx" 2>/dev/null | \
  xargs grep -l "useQuery\|useMutation\|useInfiniteQuery" 2>/dev/null | head -20

# OpenAPI spec source of truth
ls backend/openapi.json 2>/dev/null
```

**Read key files:**
- `backend/app/api/main.py` — middleware stack, router registration, tags
- All router files in scope
- All Pydantic schema files referenced by routes in scope
- All React Query hook files
- `backend/app/core/config.py` — any API versioning config
- `backend/pyproject.toml` — confirm Pydantic version (v1 vs v2 patterns differ)

**Fetch the live OpenAPI spec (if server is running):**
```bash
API_ORIGIN="${API_ORIGIN:-http://localhost:${API_PORT:-8001}}"
curl -s "$API_ORIGIN/openapi.json" 2>/dev/null | \
  python3 -m json.tool | head -100 || echo "Server not running — using static analysis"

# Static snapshot and CI drift gate
python3 -m json.tool backend/openapi.json | head -100
make openapi-check
```

**Detect breaking changes vs main:**
```bash
git diff main...HEAD --name-only | grep -E "router|schemas|models|openapi" | head -20
git diff main...HEAD -- ':(glob)backend/app/**/*.py' 'backend/openapi.json' 2>/dev/null | \
  grep "^[+-]" | grep -v "^---\|^+++" | head -60
```

---

## Phase 2 — Parallel audit (spawn all 6 subagents simultaneously)

Use the Task tool. Do NOT wait for one before starting the next.

---

### Subagent A — Pydantic v2 schema audit
**Goal: every schema is correct, complete, and idiomatic Pydantic v2**

**Schema completeness:**
```bash
# All Pydantic models
grep -rn "class.*BaseModel\|class.*Schema\|class.*Request\|class.*Response\|\
class.*Create\|class.*Update\|class.*Read\|class.*Out\b" \
  backend/app/ --include="*.py"
```

For each schema, check:

**Missing field validators where needed:**
```python
# MISSING — email field with no validation
class UserCreate(BaseModel):
    email: str              # accepts "not-an-email"
    age: int                # accepts -999

# CORRECT — validated
from pydantic import EmailStr, Field
class UserCreate(BaseModel):
    email: EmailStr
    age: int = Field(ge=0, le=150)
```

**Pydantic v2 idioms — flag v1 patterns still in use:**
```bash
# v1 patterns that should be v2
grep -rn "class Config:\|orm_mode\s*=\|validator(\|root_validator(\|\
\.dict()\|\.json()\|parse_obj(\|from_orm(" backend/app/ --include="*.py"
```

| v1 pattern | v2 replacement |
|-----------|---------------|
| `class Config: orm_mode = True` | `model_config = ConfigDict(from_attributes=True)` |
| `@validator("field")` | `@field_validator("field")` |
| `@root_validator` | `@model_validator(mode="before"/"after")` |
| `.dict()` | `.model_dump()` |
| `.json()` | `.model_dump_json()` |
| `parse_obj(data)` | `Model.model_validate(data)` |
| `from_orm(obj)` | `Model.model_validate(obj)` |
| `schema()` | `model_json_schema()` |

Flag each v1 pattern as [SCHEMA-V1-COMPAT] — these work but will break
in a future Pydantic major version and generate deprecation warnings now.

**Schema segregation — read vs write schemas:**
```bash
# Models used for both input and output — look for dual use
grep -rn "response_model\|Request\b\|Body(" backend/app/ --include="*.py" | \
  grep -oE "[A-Z][a-zA-Z]+" | sort | uniq -d
```

Every resource should have distinct schemas:
```python
# Pattern: Create / Update / Read (output) separation
class LocationCreate(BaseModel):     # POST body — no id, no timestamps
    name: str
    latitude: float
    longitude: float

class LocationUpdate(BaseModel):     # PATCH body — all fields optional
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None

class LocationRead(BaseModel):       # GET response — includes server fields
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
```

Flag any schema used as both request body and response model = [SCHEMA-DUAL-USE].

**Optional vs required field discipline:**
```bash
grep -rn "class.*Update\|class.*Patch" backend/app/ --include="*.py" -A 15
```
Update/Patch schemas must have ALL fields optional. A required field on a PATCH
schema forces clients to always send it, breaking partial update semantics.
```python
# WRONG — name required on PATCH
class LocationUpdate(BaseModel):
    name: str           # breaks partial updates

# CORRECT
class LocationUpdate(BaseModel):
    name: str | None = None
```

**Sensitive field exclusion:**
```bash
grep -rn "class.*Response\|class.*Read\|class.*Out\b" \
  backend/app/ --include="*.py" -A 20 | \
  grep -E "password|secret|token|hash|salt|embedding|vector"
```
Flag any response schema including `password_hash`, `secret`, raw `embedding`
vectors, or internal fields not meant for clients = [SCHEMA-EXPOSURE].

**PostGIS schema patterns:**
```bash
grep -rn "geometry\|geography\|GeoJSON\|geom\b\|latitude\|longitude\|coordinates" \
  backend/app/ --include="*.py"
```

Check that spatial data uses consistent output formats:
```python
# INCONSISTENT — some routes return lat/lng floats, others return GeoJSON
class LocationRead(BaseModel):
    latitude: float       # breaks clients expecting GeoJSON
    longitude: float

# CONSISTENT — always GeoJSON Feature or geometry object
from typing import Any
class LocationRead(BaseModel):
    id: UUID
    name: str
    geometry: dict[str, Any]  # GeoJSON geometry: {"type": "Point", "coordinates": [...]}
    # OR use a typed GeoJSON schema:
    # geometry: PointGeometry
```

Flag any route that returns geometry in a different format from its siblings
= [SCHEMA-GEO-INCONSISTENT].

**pgvector schema patterns:**
```bash
grep -rn "embedding\|vector\b" backend/app/ --include="*.py"
```
Raw `list[float]` embedding vectors in response schemas = [SCHEMA-EXPOSURE]
(cross-reference with `/sec-audit`). Response schemas should contain similarity
scores or ranked results, never raw vectors.

Output: findings labeled [SCHEMA-V1-COMPAT], [SCHEMA-MISSING-VALIDATOR],
[SCHEMA-DUAL-USE], [SCHEMA-OPTIONAL], [SCHEMA-EXPOSURE],
[SCHEMA-GEO-INCONSISTENT].

---

### Subagent B — Route handler audit
**Goal: every route has correct response_model, status codes, and error handling**

**Missing response_model:**
```bash
grep -rn "@router\.\|@app\." backend/app/ --include="*.py" -A 3 | \
  grep "async def\|def " | grep -v "response_model="
```

Cross-reference: is a `response_model` missing, or was it intentionally omitted?
Routes without `response_model` leak internal fields (SQLAlchemy internals,
password hashes) and produce no OpenAPI output schema = [ROUTE-NO-RESPONSE-MODEL].
```python
# WRONG — no response model, leaks internal fields
@router.get("/users/{id}")
async def get_user(id: UUID, db: AsyncSession = Depends(get_db)):
    return await db.get(User, id)

# CORRECT
@router.get("/users/{id}", response_model=UserRead)
async def get_user(id: UUID, db: AsyncSession = Depends(get_db)):
    return await db.get(User, id)
```

**Missing status codes:**
```bash
grep -rn "@router\.post\|@router\.delete\|@router\.put\|@router\.patch" \
  backend/app/ --include="*.py" | grep -v "status_code="
```

Expected status code conventions:
- `POST` creating a resource → `status_code=201`
- `DELETE` → `status_code=204` (or 200 if returning a body)
- `PUT`/`PATCH` → `status_code=200`
- Async background task started → `status_code=202`

Flag `POST` handlers without `status_code=201` = [ROUTE-STATUS-CODE].

**Error response documentation:**
```bash
grep -rn "raise HTTPException\|HTTPException(" backend/app/ --include="*.py" | \
  grep -v "#" | head -40
```

For each error thrown, is it documented in the route decorator?
```python
# WRONG — 403 and 404 thrown but not documented in OpenAPI
@router.get("/items/{id}", response_model=ItemRead)
async def get_item(id: UUID, ...):
    item = await db.get(Item, id)
    if not item:
        raise HTTPException(404)
    if item.owner_id != current_user.id:
        raise HTTPException(403)
    return item

# CORRECT — documented so clients and OpenAPI know what to expect
from fastapi import responses
@router.get(
    "/items/{id}",
    response_model=ItemRead,
    responses={
        404: {"description": "Item not found"},
        403: {"description": "Not your item"},
    }
)
```

Flag routes that raise `HTTPException` with status codes not declared in
`responses=` = [ROUTE-UNDOC-ERROR].

**Response model consistency on list endpoints:**
```bash
grep -rn "response_model.*List\|List\[" backend/app/ --include="*.py" | \
  grep "@router"
```

List endpoints should use a consistent envelope:
```python
# INCONSISTENT — some list endpoints return bare lists, others envelopes
GET /users    → [UserRead, ...]              # bare list
GET /items    → {"items": [...], "total": N} # envelope

# CONSISTENT — always envelope with pagination metadata
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    pages: int
    size: int
```

Flag list endpoints that don't use a consistent envelope pattern =
[ROUTE-LIST-INCONSISTENT].

**Path parameter naming:**
```bash
grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" \
  backend/app/ --include="*.py" | grep -oE "\{[a-z_]+\}" | sort | uniq -c | sort -rn
```

Inconsistent path parameter names for the same resource type = [ROUTE-PATH-NAMING]:
```
GET /users/{user_id}   ← uses user_id
GET /users/{id}        ← same resource, uses id — pick one
```

**Dependency ordering and type annotations:**
```bash
grep -rn "async def " backend/app/ --include="*.py" -A 3 | \
  grep -v "Depends\|db:\|current_user:" | grep "def " | head -20
```

Route handlers missing type annotations on parameters don't appear correctly
in OpenAPI and may silently accept wrong types = [ROUTE-MISSING-TYPES].

**Spatial route conventions:**
```bash
grep -rn "ST_\|geometry\|geography\|geom\b\|bbox\|bounds\|radius\|nearby\|within" \
  backend/app/ --include="*.py" -B 2 -A 5
```

Spatial endpoints should follow a consistent parameter convention:
```python
# INCONSISTENT spatial params across routes
GET /locations/nearby?lat=40.7&lng=-74.0&radius=1000   # one route
GET /places/search?latitude=40.7&longitude=-74.0&dist=1 # another route

# CONSISTENT
# Always: lat, lng (or longitude/latitude — pick one and stick to it)
# Always: radius_meters (not dist, not radius, not km)
# Always: bbox as "min_lng,min_lat,max_lng,max_lat" (GeoJSON bbox order)
```

Flag spatial routes with inconsistent parameter naming = [ROUTE-GEO-PARAMS].

**Semantic search route conventions:**
```bash
grep -rn "semantic\|similarity\|vector\|embedding\|nearest\|knn" \
  backend/app/ --include="*.py" -B2 -A8
```

pgvector-backed catalog search should have consistent shape:
```python
# CONSISTENT GeoLens semantic search contract
GET /search/datasets/
  ?q=<text query>        # always q for text input, never query or search
  &semantic=true          # enables semantic ranking when embeddings are available
  &limit=20              # always limit (not top_k, not k, not n)

# Response always includes:
# - features: list of OGC-style dataset records
# - numberMatched / numberReturned pagination counts
# - links with self/next/prev where applicable
# Embedding vectors must never appear in responses
```

Output: findings labeled [ROUTE-NO-RESPONSE-MODEL], [ROUTE-STATUS-CODE],
[ROUTE-UNDOC-ERROR], [ROUTE-LIST-INCONSISTENT], [ROUTE-PATH-NAMING],
[ROUTE-MISSING-TYPES], [ROUTE-GEO-PARAMS], [ROUTE-SEARCH-PARAMS].

---

### Subagent C — OpenAPI spec accuracy
**Goal: the spec is complete, accurate, and useful as a contract document**

**Generate and inspect the live spec:**
```bash
# If server running
API_ORIGIN="${API_ORIGIN:-http://localhost:${API_PORT:-8001}}"
curl -s "$API_ORIGIN/openapi.json" > /tmp/openapi_current.json 2>/dev/null

# If not running, generate statically from the real FastAPI app
(cd backend && PYTHONPATH=. uv run python -c "
from app.api.main import app
import json
print(json.dumps(app.openapi(), indent=2))
") > /tmp/openapi_current.json 2>/dev/null

# Compare against the committed SDK source of truth
make openapi-check

# Count routes
cat /tmp/openapi_current.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
paths=spec.get('paths',{})
total=sum(len(v) for v in paths.values())
print(f'Routes in spec: {total}')
schemas=spec.get('components',{}).get('schemas',{})
print(f'Schemas in spec: {len(schemas)}')
"
```

**Tag coverage:**
```bash
cat /tmp/openapi_current.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
untagged=[]
for path,methods in spec.get('paths',{}).items():
    for method,op in methods.items():
        if not op.get('tags'):
            untagged.append(f'{method.upper()} {path}')
for r in untagged: print('UNTAGGED:', r)
"
```

Routes without tags don't group correctly in Swagger/ReDoc and make the spec
hard to navigate. Every route must have at least one tag = [OPENAPI-UNTAGGED].

**Description coverage:**
```bash
cat /tmp/openapi_current.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
for path,methods in spec.get('paths',{}).items():
    for method,op in methods.items():
        if not op.get('summary') and not op.get('description'):
            print(f'NO-DESC: {method.upper()} {path}')
"
```

Routes without `summary` or `description` are unusable as a contract document
= [OPENAPI-NO-DESC]. Every route must have at minimum a one-line `summary`.

Fix — add to route decorator:
```python
@router.get(
    "/locations/nearby",
    summary="Find locations near a point",
    description="""
    Returns locations within `radius_meters` of the given coordinates.
    Results are ordered by distance ascending. Maximum radius: 50km.
    """,
    response_model=PaginatedResponse[LocationRead],
)
```

**Example values:**
```bash
cat /tmp/openapi_current.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
no_examples=[]
for name,schema in spec.get('components',{}).get('schemas',{}).items():
    props=schema.get('properties',{})
    if props and not any('example' in p or 'examples' in p for p in props.values()):
        no_examples.append(name)
for s in no_examples[:20]: print('NO-EXAMPLE:', s)
"
```

Schemas without examples produce empty Swagger UI forms — developers can't
test the API without guessing the expected format = [OPENAPI-NO-EXAMPLES].

Fix — add `json_schema_extra` to Pydantic v2 schemas:
```python
class LocationCreate(BaseModel):
    name: str = Field(..., example="Central Park")
    latitude: float = Field(..., example=40.7829)
    longitude: float = Field(..., example=-73.9654)
    radius_meters: float = Field(..., example=500.0, ge=1, le=50000)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Central Park",
                "latitude": 40.7829,
                "longitude": -73.9654,
                "radius_meters": 500.0,
            }
        }
    )
```

**Deprecated routes not marked:**
```bash
grep -rn "deprecated\|DEPRECATED\|DO NOT USE\|will be removed" \
  backend/app/ --include="*.py" | grep -v "#.*deprecated"
```

Any route marked deprecated in comments but not in the decorator:
```python
# Add to decorator to propagate to OpenAPI spec
@router.get("/old-endpoint", deprecated=True)
```

**GeoJSON schema definition:**
```bash
cat /tmp/openapi_current.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
schemas=spec.get('components',{}).get('schemas',{})
geo_schemas=[k for k in schemas if any(w in k.lower() for w in
  ['geo','geometry','point','polygon','feature','coordinates'])]
print('Geo schemas found:', geo_schemas)
"
```

Spatial endpoints that return raw `dict` or `Any` for geometry produce
`{}` in the OpenAPI spec — clients have no type information. Define typed
GeoJSON schemas:
```python
from typing import Literal
from pydantic import BaseModel

class PointGeometry(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]  # [longitude, latitude]

class PolygonGeometry(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]

class GeoJSONFeature(BaseModel):
    type: Literal["Feature"]
    geometry: PointGeometry | PolygonGeometry
    properties: dict[str, Any]
```

Flag routes returning geometry as `dict` or `Any` = [OPENAPI-GEO-UNTYPED].

**Similarity search response schema:**
```bash
cat /tmp/openapi_current.json | python3 -c "
import json,sys
spec=json.load(sys.stdin)
for path,methods in spec.get('paths',{}).items():
    if any(w in path for w in ['search','similar','semantic','nearest']):
        for method,op in methods.items():
            resp=op.get('responses',{}).get('200',{})
            print(f'{method.upper()} {path}:', json.dumps(resp.get('content',{}), indent=2)[:200])
"
```

Flag search endpoints where the response schema contains `embedding` or `vector`
array fields = [OPENAPI-EMBEDDING-EXPOSED].

Output: findings labeled [OPENAPI-UNTAGGED], [OPENAPI-NO-DESC],
[OPENAPI-NO-EXAMPLES], [OPENAPI-GEO-UNTYPED], [OPENAPI-EMBEDDING-EXPOSED].

---

### Subagent D — React Query alignment
**Goal: every hook matches the actual API contract**

**Inventory all hooks:**
```bash
grep -rn "useQuery\|useMutation\|useInfiniteQuery\|useSuspenseQuery" \
  frontend/src/ --include="*.ts" --include="*.tsx" -l

# Extract query keys and endpoints from hooks
grep -rn "queryKey\|queryFn\|mutationFn\|url\|endpoint\|fetchJson\|api\." \
  frontend/src/ --include="*.ts" -A 3 | head -80
```

**URL alignment — hook endpoints vs actual routes:**
Build a map of:
1. Every API route: `METHOD /path/pattern` (from FastAPI router files)
2. Every hook call: URL string used in `queryFn` or `mutationFn`

Cross-reference: does every hook URL match an actual route?
```bash
# Extract URLs from React Query hooks
grep -rn "fetch\|axios\|apiClient\." frontend/src/ --include="*.ts" --include="*.tsx" | \
  grep -oE "['\"][/][a-z/_-]+['\"]" | sort -u

# Compare to actual routes
grep -rn "@router\.\|@app\." backend/app/ --include="*.py" | \
  grep -oE "['\"][/][a-z/_{}/-]+['\"]" | sort -u
```

Flag any hook calling a URL that doesn't exist in the router = [RQ-URL-MISMATCH].

**HTTP method alignment:**
```bash
grep -rn "useMutation" frontend/src/ --include="*.ts" --include="*.tsx" -A 10 | \
  grep -E "method:|\"POST\"|\"PUT\"|\"PATCH\"|\"DELETE\""
```

Check each mutation's HTTP method against the route definition:
- Hook uses `method: "POST"` but route is `@router.put` = [RQ-METHOD-MISMATCH]
- Hook uses `method: "PUT"` but route is `@router.patch` = [RQ-METHOD-MISMATCH]

**Query key consistency:**
```bash
grep -rn "queryKey" frontend/src/ --include="*.ts" --include="*.tsx" | \
  grep -oE "\[.*\]" | sort | uniq -c | sort -rn | head -30
```

Query keys must be consistent across all related hooks:
```typescript
// INCONSISTENT — same resource, different key shapes
useQuery({ queryKey: ['users', id] })        // in UserProfile.tsx
useQuery({ queryKey: ['user', userId] })     // in UserCard.tsx
useQuery({ queryKey: ['users', 'detail', id] }) // in AdminView.tsx

// CONSISTENT — centralized key factory
export const userKeys = {
  all: ['users'] as const,
  lists: () => [...userKeys.all, 'list'] as const,
  list: (filters: UserFilters) => [...userKeys.lists(), filters] as const,
  details: () => [...userKeys.all, 'detail'] as const,
  detail: (id: string) => [...userKeys.details(), id] as const,
}
```

Flag duplicated or inconsistent query keys for the same resource =
[RQ-KEY-INCONSISTENT].

**Stale time and cache configuration:**
```bash
grep -rn "staleTime\|gcTime\|cacheTime\|refetchInterval\|refetchOnWindowFocus" \
  frontend/src/ --include="*.ts" --include="*.tsx"
```

Missing `staleTime` on all queries = unnecessary refetches on every focus.
Inconsistent stale times for the same data = [RQ-CACHE-INCONSISTENT].

Recommended defaults:
```typescript
// In queryClient configuration
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,     // 5 minutes default
      gcTime: 1000 * 60 * 10,       // 10 minutes
      refetchOnWindowFocus: false,   // opt-in rather than opt-out
      retry: (failureCount, error) =>
        failureCount < 2 && (error as ApiError).status >= 500,
    },
  },
})
```

**Mutation invalidation patterns:**
```bash
grep -rn "onSuccess\|onSettled\|invalidateQueries\|setQueryData" \
  frontend/src/ --include="*.ts" --include="*.tsx" -B2 -A5
```

Mutations that don't invalidate related queries leave the UI stale:
```typescript
// MISSING invalidation
useMutation({
  mutationFn: (data) => api.post('/locations', data),
  // onSuccess missing — location list never refreshes after create
})

// CORRECT
useMutation({
  mutationFn: (data) => api.post('/locations', data),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: locationKeys.lists() })
  },
})
```

Flag mutations touching a resource with no corresponding `invalidateQueries`
or `setQueryData` = [RQ-NO-INVALIDATION].

**Optimistic update opportunities:**
For mutations where the outcome is predictable (toggle, delete, status change),
flag absence of optimistic updates as [RQ-OPTIMISTIC-OPPORTUNITY]:
```typescript
// With useOptimistic (React 19) or React Query onMutate
onMutate: async (newData) => {
  await queryClient.cancelQueries({ queryKey: locationKeys.detail(id) })
  const previous = queryClient.getQueryData(locationKeys.detail(id))
  queryClient.setQueryData(locationKeys.detail(id), newData)
  return { previous }
},
onError: (err, newData, context) => {
  queryClient.setQueryData(locationKeys.detail(id), context?.previous)
},
```

**Error type alignment:**
```bash
grep -rn "error\b\|isError\|onError" frontend/src/ --include="*.ts" --include="*.tsx" | \
  grep -E "error\.message|error\.detail|error\.status|error as" | head -20
```

Check whether the error shape expected by the frontend matches what FastAPI
actually returns:
```typescript
type FastApiError =
  | { detail: string }
  | { detail: Array<{ loc: unknown[]; msg: string; type?: string }> }

// Hook expecting wrong shape:
if (error.message) {
  // FastAPI returns error.detail, not error.message.
}
```

Flag shape mismatches = [RQ-ERROR-SHAPE].

**Spatial hook patterns:**
```bash
grep -rn "nearby\|bbox\|bounds\|geometry\|geojson\|coordinates\|radius" \
  frontend/src/ --include="*.ts" --include="*.tsx" -A 5 | head -40
```

Check that spatial hooks:
- Pass coordinates as `lat`/`lng` (matching API parameter names — not `latitude`/`longitude`
  unless that's what the API uses)
- Handle GeoJSON response geometry consistently (not mixing flat lat/lng with
  GeoJSON depending on the endpoint)
- Serialize bbox params as the API expects (comma-separated string vs individual params)

Flag parameter name mismatches between hook and route = [RQ-GEO-PARAMS].

**Semantic search hook patterns:**
```bash
grep -rn "semantic\|similarity\|vector\|embedding\|nearest" \
  frontend/src/ --include="*.ts" --include="*.tsx" -A 8 | head -30
```

Semantic search hooks should:
- Send `q` not `query`, `search`, or `text` (unless that's the API's param name)
- Accept `threshold` and `limit` params
- Never send raw embedding vectors from the client (server embeds the text)
- Handle `scores` in the response as a separate field, not expect them on the item

Output: findings labeled [RQ-URL-MISMATCH], [RQ-METHOD-MISMATCH],
[RQ-KEY-INCONSISTENT], [RQ-CACHE-INCONSISTENT], [RQ-NO-INVALIDATION],
[RQ-OPTIMISTIC-OPPORTUNITY], [RQ-ERROR-SHAPE], [RQ-GEO-PARAMS].

---

### Subagent E — Versioning and breaking change detection
**Goal: identify every change in this branch that breaks existing clients**

**Diff analysis:**
```bash
git diff main...HEAD -- ':(glob)backend/app/**/*.py' 'backend/openapi.json' 2>/dev/null
```

For every changed line, classify by impact:

**Breaking changes (block merge):**
- Route path changed: `GET /users/{id}` → `GET /user/{id}` — all clients 404
- HTTP method changed: `POST /items` → `PUT /items` — all clients get 405
- Required field added to request body — all existing clients missing the field get 422
- Field removed from response — any client reading that field breaks silently
- Field type changed: `string` → `int` — clients fail to deserialize
- Status code changed: `200` → `201` — clients checking exact status break
- Error code changed: always returned 404 now returns 403 — clients handle wrong code

**Non-breaking changes (fine to merge):**
- Optional field added to request body
- New field added to response
- New optional query parameter added
- New route added
- Description/summary changed
- Example values changed
- `deprecated=True` added

**Flag each changed route with classification:**
```bash
git diff main...HEAD -- ':(glob)backend/app/**/*.py' 'backend/openapi.json' | \
  grep "^[+-]" | grep -v "^---\|^+++" | \
  grep -E "@router\.|response_model=|status_code=|class.*Schema|class.*Request|\
  class.*Response|: str|: int|: float|: bool|: UUID|: datetime|\
  Optional\[|list\[|None =" | head -60
```

For each potentially breaking change, write:
```
[BREAKING] Route: GET /locations/{id}
Change: response_model changed from LocationRead → LocationReadV2
Impact: clients reading `address` field will get None (field renamed to `street_address`)
Migration: deprecate old field for 1 release, add both fields, then remove old
```

**API versioning strategy check:**
```bash
grep -rn "v1\|v2\|version\|/api/v" backend/app/ --include="*.py" | head -20
grep -rn "api_version\|API_VERSION\|Accept-Version" backend/app/ --include="*.py"
```

If no versioning strategy exists and breaking changes are present = MEDIUM:
recommend one of:
- URL versioning: `/api/v1/`, `/api/v2/`
- Header versioning: `Accept: application/vnd.app.v2+json`
- For this stack, URL versioning is simplest with FastAPI routers:
```python
  app.include_router(v1_router, prefix="/api/v1")
  app.include_router(v2_router, prefix="/api/v2")
```

**Deprecation lifecycle:**
```bash
grep -rn "deprecated=True\|@deprecated\|# DEPRECATED" backend/app/ --include="*.py"
```
Flag deprecated routes that have been deprecated for > 2 releases (check git log)
with no removal plan = [VERSION-STALE-DEPRECATED].

Output: findings labeled [BREAKING-PATH], [BREAKING-METHOD],
[BREAKING-REQUIRED-FIELD], [BREAKING-REMOVED-FIELD], [BREAKING-TYPE],
[BREAKING-STATUS], [VERSION-MISSING], [VERSION-STALE-DEPRECATED].

---

### Subagent F — API-wide consistency audit
**Goal: the API speaks with one voice — naming, pagination, errors, and conventions
are uniform across all routes**

**Naming conventions:**
```bash
# Extract all route paths
grep -rn "@router\.\|@app\." backend/app/ --include="*.py" | \
  grep -oE "['\"][/][a-z/_{}/-]+['\"]" | tr -d "'" | tr -d '"' | sort

# Extract all field names from schemas
grep -rn "^\s\+[a-z_]\+:" backend/app/ --include="*.py" | \
  grep -oE "[a-z_]+:" | tr -d ":" | sort | uniq -c | sort -rn | head -40
```

Check for:
- Mixed case in paths: `/getUserById` (camelCase) vs `/get-user-by-id` (kebab)
  vs `/get_user_by_id` (snake) — REST convention is lowercase kebab-case
- Mixed naming for IDs: `userId`, `user_id`, `id` used for the same concept
- Mixed date field names: `created_at`, `createdAt`, `creation_date` — pick one
```python
# WRONG — inconsistent
GET /getUser/{userId}       # camelCase verb + ID
GET /items/{item_id}        # snake_case path param
GET /locations/{id}         # bare id

# CORRECT — consistent REST conventions
GET /users/{user_id}        # plural noun, snake_case param
GET /items/{item_id}
GET /locations/{location_id}
```

Flag any path using camelCase, PascalCase, or verb-first naming =
[CONSISTENCY-NAMING].

**Pagination consistency:**
```bash
grep -rn "skip\|offset\|limit\|page\|per_page\|size\|cursor\|page_token" \
  backend/app/ --include="*.py" | grep -v "#" | head -30
```

Every list endpoint must use the same pagination strategy:
```python
# INCONSISTENT — three different approaches
GET /users?skip=0&limit=20         # offset-based
GET /items?page=1&per_page=20      # page-based
GET /locations?cursor=abc123       # cursor-based

# CONSISTENT — one strategy for the whole API
# Recommend cursor-based for large/frequently-updated datasets (locations, searches)
# Recommend offset-based for simple CRUD with stable order

class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
    ):
        self.page = page
        self.size = size
        self.offset = (page - 1) * size
```

Flag mixed pagination strategies = [CONSISTENCY-PAGINATION].

**Error response format:**
```bash
grep -rn "HTTPException\|raise.*Exception\|JSONResponse" \
  backend/app/ --include="*.py" | grep -v "#" | head -30
```

Check for consistent error body format across all routes:
```python
# FastAPI default — inconsistent with custom errors
raise HTTPException(404, detail="Not found")
# Returns: {"detail": "Not found"}

# Custom error — different shape
return JSONResponse({"error": "Not found", "code": 404}, status_code=404)
# Returns: {"error": "...", "code": ...}
```

Standardize on a single error schema:
```python
class APIError(BaseModel):
    code: str           # machine-readable: "NOT_FOUND", "VALIDATION_ERROR"
    message: str        # human-readable
    details: dict | None = None  # additional context

# Applied consistently via exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=APIError(
            code=HTTP_STATUS_CODES[exc.status_code],
            message=exc.detail,
        ).model_dump()
    )
```

Flag routes with error shapes deviating from the established pattern =
[CONSISTENCY-ERROR-SHAPE].

**Timestamp format:**
```bash
grep -rn "datetime\|created_at\|updated_at\|timestamp" \
  backend/app/ --include="*.py" | grep -v "#"
```

Inconsistent timestamp serialization = [CONSISTENCY-TIMESTAMPS]:
```python
# FastAPI serializes datetime as ISO 8601 by default
# WRONG — some routes return unix timestamps, others ISO 8601
{"created_at": 1706745600}          # unix timestamp
{"created_at": "2024-02-01T00:00:00"}  # ISO 8601 no timezone
{"created_at": "2024-02-01T00:00:00Z"} # ISO 8601 UTC — CORRECT

# Enforce UTC ISO 8601 everywhere
from pydantic import field_serializer
class BaseSchema(BaseModel):
    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_datetime(self, dt: datetime) -> str:
        return dt.replace(tzinfo=timezone.utc).isoformat()
```

**Envelope consistency:**
```bash
grep -rn "\"data\"\|\"result\"\|\"results\"\|\"items\"\|\"payload\"" \
  backend/app/ --include="*.py" | grep -v "#\|test\|spec" | head -20
```

Some routes wrap in `{"data": [...]}`, others return bare arrays =
[CONSISTENCY-ENVELOPE]. Pick one and enforce it.

**PostGIS coordinate order:**
```bash
grep -rn "coordinates\|ST_MakePoint\|ST_GeomFromText" \
  backend/app/ --include="*.py" | head -20
```

GeoJSON spec: coordinates are `[longitude, latitude]` (x, y order).
PostGIS `ST_MakePoint(x, y)` = `ST_MakePoint(longitude, latitude)`.
A common bug is using `ST_MakePoint(lat, lng)` which silently swaps coordinates.
```python
# WRONG — latitude/longitude swapped
ST_MakePoint(latitude, longitude)   # silently produces wrong geometry

# CORRECT
ST_MakePoint(longitude, latitude)   # GeoJSON order: x (lng), y (lat)
```

Flag any `ST_MakePoint` call where the argument order isn't clearly documented
or is reversed = [CONSISTENCY-GEO-COORD-ORDER].

Output: findings labeled [CONSISTENCY-NAMING], [CONSISTENCY-PAGINATION],
[CONSISTENCY-ERROR-SHAPE], [CONSISTENCY-TIMESTAMPS], [CONSISTENCY-ENVELOPE],
[CONSISTENCY-GEO-COORD-ORDER].

---

## Phase 3 — Generate the contract document

Merge all subagent outputs into the full contract:
```markdown
# API contract — [scope]
Generated: [date]
Stack: FastAPI · Pydantic v2 · React Query

## Contract health

| Category         | Routes audited | Findings | Blocking |
|-----------------|---------------|----------|---------|
| Schemas          | N             | N        | N       |
| Route handlers   | N             | N        | N       |
| OpenAPI spec     | N             | N        | N       |
| React Query      | N hooks       | N        | N       |
| Breaking changes | N             | N        | N       |
| Consistency      | N             | N        | N       |

## Route inventory

| Method | Path | Response model | Status | Errors documented | Tags |
|--------|------|---------------|--------|-------------------|------|
| GET    | /users/{user_id} | UserRead | 200 | 404, 403 | users |
| POST   | /users | UserRead | 201 | 422 | users |
| ...    |      |               |        |                   |      |

## Breaking changes (block merge until resolved)
[Each breaking change: what changed, which clients break, migration path]

## Findings by severity

### 🔴 Blocking
[CONTRACT-VIOLATION findings — existing clients would break]

### 🟠 High
[Missing response models, undocumented errors, React Query misalignment]

### 🟡 Medium
[Design inconsistencies, missing examples, v1 Pydantic patterns]

### 🟢 Low / improvement
[Optional enhancements that improve DX without fixing bugs]

## Consistency reference card
[The canonical conventions established for this API:
- Pagination: how it works
- Error format: the schema
- Coordinate order: lng/lat or lat/lng
- Timestamp format: ISO 8601 UTC
- Naming: snake_case paths, snake_case fields
- ID params: {resource_name_id}
- Envelope: bare list or {items: [], total: N}]
```

---

## Phase 4 — Validate OpenAPI and SDK drift
```bash
# backend/openapi.json is the contract snapshot and SDK source of truth.
make openapi-check
make sdks-check
```

Do not generate ad hoc frontend types under `frontend/src/api/generated` or
`frontend/src/types/api.d.ts`. GeoLens publishes and validates generated clients through
`sdks/python/`, `sdks/typescript/`, `make sdks`, and `make sdks-check`.

Include in output:
- Whether `backend/openapi.json` drifted
- Whether SDK regeneration produced uncommitted diffs
- Any schema fixes needed to unblock official SDK generation
- Which generated SDK wrapper or frontend type should consume the contract

---

## Phase 5 — Generate contract tests

Produce an `e2e/contract.spec.ts` only from real paths in `backend/openapi.json`.
Prefer critical public surfaces: `/search/datasets/`, `/maps/`, `/datasets/`,
`/collections/datasets`, OGC `/collections/{id}/items`, STAC `/stac/search`, and
share/embed endpoints.
```typescript
// contract.spec.ts — auto-generated by /api-contract
// Run: npx playwright test e2e/contract.spec.ts --project=chromium

import { test, expect } from '@playwright/test'

const BASE = process.env.API_URL || `http://localhost:${process.env.API_PORT ?? '8001'}`

test('GET /search/datasets/ — catalog search shape', async ({ request }) => {
  const res = await request.get(`${BASE}/search/datasets/?limit=10`)
  expect(res.status()).toBe(200)
  const body = await res.json()
  expect(body).toHaveProperty('numberMatched')
  expect(body).toHaveProperty('numberReturned')
  expect(body).toHaveProperty('features')
  for (const item of body.features ?? []) {
    expect(item).not.toHaveProperty('embedding')
    expect(item).not.toHaveProperty('vector')
  }
})

test('GET /conformance — OGC conformance shape', async ({ request }) => {
  const res = await request.get(`${BASE}/conformance`)
  expect(res.status()).toBe(200)
  const body = await res.json()
  expect(Array.isArray(body.conformsTo)).toBe(true)
  expect(body.conformsTo.some((uri: string) => uri.includes('ogcapi-features'))).toBe(true)
})

test('share/embed advanced-sharing gates match edition', async ({ request }) => {
  test.skip(!process.env.CONTRACT_MAP_ID, 'Set CONTRACT_MAP_ID for share/embed contract checks')
  const mapId = process.env.CONTRACT_MAP_ID

  const basic = await request.post(`${BASE}/maps/${mapId}/share/`, {
    data: { enabled: true },
  })
  expect([200, 201]).toContain(basic.status())

  for (const body of [
    { enabled: true, expires_in_days: 30 },
    { enabled: true, embed_token_lifetime_seconds: 3600 },
    { enabled: true, allowed_origins: ['https://example.com'] },
  ]) {
    const res = await request.post(`${BASE}/maps/${mapId}/share/`, { data: body })
    // Community must reject advanced-sharing fields. Enterprise-positive cases
    // should be added only when the Enterprise overlay is active.
    expect([400, 402, 403, 422]).toContain(res.status())
  }
})
```

---

## Phase 6 — Deliver

**1. Write `docs-internal/api-contract-[scope]-[date].md`** with the full contract document.

**2. Report `make openapi-check` and `make sdks-check` results.**

**3. If useful, write `e2e/contract.spec.ts` with generated tests based only on real OpenAPI paths.**

**4. Update local command guidance only if the established contract conventions changed.**

**5. Update `lessons.md`:**
```markdown
## [date] — API contract audit: [scope]
### Conventions established
- Pagination: [strategy]
- Error format: [schema]
- Coordinate order: [lng/lat]
### Recurring violations found
### Hooks that needed rework
```

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/api-contract-audit-{YYYYMMDD}.md`

### Post-delivery

1. If a previous `api-contract-audit-*.md` exists in `docs-internal/audits/`, diff key findings against the prior report.
2. Print one-line summary: overall grade + breaking change count + contract violation count.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/sec-audit` — covers injection and auth vulnerabilities in API routes. This command focuses on the contract surface (schemas, response shapes, error codes, React Query alignment), not exploit scenarios.
- `/ogc-compliance` — covers OGC/STAC/DCAT endpoint conformance to external specs. This command covers internal API contract consistency.

---

## What NOT to flag

- Pydantic v1 patterns in files not changed by the current branch (unless
  running full audit)
- Missing `staleTime` on queries where data is intentionally always-fresh
  (e.g. real-time feeds)
- `Any` type on geometry fields if a typed GeoJSON schema PR is already open
- Routes without `responses=` for status codes that FastAPI generates automatically
  (422 for validation errors is always present)
- camelCase field names in schemas used only for external API integration
  (webhooks, third-party payloads) — those must match the external format
- `deprecated=True` routes that have only been deprecated for < 1 release
- Optimistic update absence on mutations where the server response is needed
  before the UI can update (e.g. server-assigned IDs, server-computed fields)
- Missing description on internal-only routes (if `include_in_schema=False`)
