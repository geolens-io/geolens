---
phase: quick-260322-irw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/datasets/router.py
  - frontend/src/components/dataset/RelatedRecordsPanel.tsx
  - frontend/src/i18n/locales/en/dataset.json
  - frontend/src/i18n/locales/de/dataset.json
  - frontend/src/i18n/locales/es/dataset.json
  - frontend/src/i18n/locales/fr/dataset.json
  - backend/tests/test_fk_relationships.py
autonomous: true
requirements: [POLISH-01, POLISH-02, POLISH-03]

must_haves:
  truths:
    - "FK relationship endpoints respond without NameError (get_db replaces get_session)"
    - "FK read endpoints enforce dataset visibility (anonymous cannot access private dataset relationships)"
    - "RelatedRecordsPanel renders translated strings in all 4 locales (no hardcoded English)"
    - "RelatedRecordsPanel shows error state when API call fails"
    - "FK relationship CRUD has automated test coverage"
  artifacts:
    - path: "backend/app/datasets/router.py"
      provides: "Fixed FK relationship endpoints with get_db and visibility checks"
      contains: "get_db"
    - path: "frontend/src/components/dataset/RelatedRecordsPanel.tsx"
      provides: "i18n-complete panel with error states"
      contains: "isError"
    - path: "frontend/src/i18n/locales/en/dataset.json"
      provides: "English i18n keys for related records"
      contains: "relatedRecords"
    - path: "backend/tests/test_fk_relationships.py"
      provides: "Test coverage for FK relationship endpoints"
      contains: "test_create_relationship"
  key_links:
    - from: "backend/app/datasets/router.py"
      to: "app.dependencies.get_db"
      via: "Depends(get_db)"
      pattern: "Depends\\(get_db\\)"
    - from: "frontend/src/components/dataset/RelatedRecordsPanel.tsx"
      to: "frontend/src/i18n/locales/*/dataset.json"
      via: "useTranslation('dataset') + t() calls"
      pattern: "t\\('relatedRecords"
---

<objective>
Fix the critical runtime bug and highest-impact polish issues found across 17 shipped quick tasks (03/19-03/22).

Purpose: The FK relationship endpoints are completely broken at runtime (NameError on every request), the RelatedRecordsPanel has no i18n or error handling, and there is zero test coverage for this feature area.

Output: Working FK endpoints with auth, translated and error-handling UI, and test coverage.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/app/datasets/router.py (lines 2164-2230 — FK relationship endpoints)
@backend/app/datasets/schemas.py (lines 370-387 — DatasetRelationshipCreate/Response)
@frontend/src/components/dataset/RelatedRecordsPanel.tsx
@frontend/src/i18n/locales/en/dataset.json
@backend/tests/test_datasets.py (test pattern reference)

<interfaces>
<!-- From backend/app/datasets/router.py imports (already available): -->
```python
from app.dependencies import get_db  # line 101
from app.auth.dependencies import get_optional_user, require_permission  # lines 34-36
from app.auth.visibility import check_dataset_access  # line 41
```

<!-- From backend/app/datasets/schemas.py: -->
```python
class DatasetRelationshipCreate(BaseModel):
    target_dataset_id: uuid.UUID
    source_column: str
    target_column: str = "gid"
    label: str | None = None

class DatasetRelationshipResponse(BaseModel):
    id: uuid.UUID
    source_dataset_id: uuid.UUID
    target_dataset_id: uuid.UUID
    source_column: str
    target_column: str
    relationship_type: str
    label: str | None
    target_dataset_title: str | None = None
```

<!-- i18n: dataset namespace, useTranslation('dataset') pattern used by all other dataset components -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix FK relationship endpoints — get_db, visibility checks</name>
  <files>backend/app/datasets/router.py</files>
  <action>
In `backend/app/datasets/router.py` lines 2164-2230, fix all 4 FK relationship endpoints:

1. **Replace `get_session` with `get_db`** in all 4 endpoints (lines 2172, 2185, 2199, 2219). `get_session` does not exist — the entire rest of the file uses `Depends(get_db)` from `app.dependencies`. This is a critical runtime NameError.

2. **Add visibility checks to the 2 read endpoints:**
   - `list_dataset_relationships` (line 2169): Add `user: User | None = Depends(get_optional_user)` parameter. Before calling `list_relationships`, load the dataset and call `check_dataset_access(db, dataset, dataset_id, user)`. Follow the exact pattern used by `get_dataset_features` (around line 427) — load dataset via `select(Dataset).options(joinedload(Dataset.record)).where(Dataset.id == dataset_id)`, raise 404 if not found, then check access.
   - `get_feature_related_records` (line 2212): Add `user: User | None = Depends(get_optional_user)` parameter. Add the same dataset load + `check_dataset_access` pattern before calling `get_related_records`.

3. **Do NOT change** the write endpoints (`create_dataset_relationship`, `delete_dataset_relationship`) — they already use `require_permission("edit_metadata")` which is sufficient.

All imports (`get_db`, `get_optional_user`, `check_dataset_access`, `User`, `Dataset`, `joinedload`) are already imported at the top of the file.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "from app.datasets.router import router; print('Import OK')" 2>&1 || echo "FAIL"</automated>
  </verify>
  <done>All 4 FK endpoints use get_db. List and query endpoints enforce visibility via check_dataset_access. Write endpoints unchanged.</done>
</task>

<task type="auto">
  <name>Task 2: Fix RelatedRecordsPanel i18n and error handling</name>
  <files>
    frontend/src/components/dataset/RelatedRecordsPanel.tsx,
    frontend/src/i18n/locales/en/dataset.json,
    frontend/src/i18n/locales/de/dataset.json,
    frontend/src/i18n/locales/es/dataset.json,
    frontend/src/i18n/locales/fr/dataset.json
  </files>
  <action>
**RelatedRecordsPanel.tsx:**

1. Change `useTranslation()` to `useTranslation('dataset')` — all other dataset components use this namespace.

2. Replace all hardcoded English strings with `t()` calls:
   - Line 33: `'Related Records'` fallback → `t('relatedRecords.title')`
   - Line 54: `'No related records'` → `t('relatedRecords.noRecords')`
   - Lines 81-82: `'Showing {n} of {m} records'` → `t('relatedRecords.showingCount', { shown: data.rows.length, total: data.approximate_total })`
   - Line 118: `t('dataset.relatedRecords', { defaultValue: 'Related Records' })` → `t('relatedRecords.title')` (now in correct namespace)

3. Add error state handling to BOTH queries:
   - In `RelatedRecordsPanel` (outer component, line 96): Destructure `isError` from the relationships query. After the loading check, add an error state that renders a subtle inline error message using `t('relatedRecords.error')`.
   - In `RelatedSection` (inner component, line 27): Destructure `isError` from the related records query. After the loading skeleton block, add an error state rendering `t('relatedRecords.loadError')` as muted text.

**Locale files — add to ALL 4 dataset.json files:**

Add a `relatedRecords` object (near the existing `relatedDatasets` key) with these keys:

English (en):
```json
"relatedRecords": {
  "title": "Related Records",
  "noRecords": "No related records",
  "showingCount": "Showing {{shown}} of {{total}} records",
  "error": "Failed to load relationships",
  "loadError": "Failed to load related records"
}
```

German (de):
```json
"relatedRecords": {
  "title": "Verknuepfte Datensaetze",
  "noRecords": "Keine verknuepften Datensaetze",
  "showingCount": "{{shown}} von {{total}} Datensaetzen",
  "error": "Beziehungen konnten nicht geladen werden",
  "loadError": "Verknuepfte Datensaetze konnten nicht geladen werden"
}
```

Spanish (es):
```json
"relatedRecords": {
  "title": "Registros relacionados",
  "noRecords": "Sin registros relacionados",
  "showingCount": "Mostrando {{shown}} de {{total}} registros",
  "error": "Error al cargar relaciones",
  "loadError": "Error al cargar registros relacionados"
}
```

French (fr):
```json
"relatedRecords": {
  "title": "Enregistrements associes",
  "noRecords": "Aucun enregistrement associe",
  "showingCount": "{{shown}} sur {{total}} enregistrements",
  "error": "Echec du chargement des relations",
  "loadError": "Echec du chargement des enregistrements associes"
}
```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -20</automated>
  </verify>
  <done>RelatedRecordsPanel uses dataset namespace, all strings are translated in 4 locales, both queries show error states on failure.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Add FK relationship endpoint test coverage</name>
  <files>backend/tests/test_fk_relationships.py</files>
  <behavior>
    - test_create_relationship: POST creates a relationship between two datasets, returns 201 with correct schema
    - test_list_relationships: GET returns array of relationships for a dataset
    - test_delete_relationship: DELETE removes a relationship, returns 204
    - test_list_relationships_private_dataset_anonymous: anonymous user gets 403/404 for private dataset relationships
    - test_create_relationship_requires_auth: unauthenticated POST returns 401/403
    - test_delete_nonexistent_relationship: DELETE unknown UUID returns 404
  </behavior>
  <action>
Create `backend/tests/test_fk_relationships.py` following the existing pattern in `test_datasets.py`:
- Use `httpx.AsyncClient` with `ASGITransport` against the real app
- Use the same helper pattern: `_get_user_id`, `_create_dataset` to set up test fixtures
- Create two datasets (source and target) for relationship testing
- Test CRUD lifecycle: create, list, delete
- Test auth enforcement: anonymous cannot list private dataset relationships, unauthenticated cannot create/delete
- Test 404 on delete of nonexistent relationship

Use `pytest.mark.asyncio` and the existing `conftest.py` session fixture pattern. Import `app.main:app` for the ASGI transport.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -m pytest tests/test_fk_relationships.py -x -v 2>&1 | tail -30</automated>
  </verify>
  <done>6+ tests covering FK relationship CRUD, auth enforcement, and error cases. All tests pass.</done>
</task>

</tasks>

<verification>
1. Backend FK endpoints respond without errors: `cd backend && python -c "from app.datasets.router import router"`
2. Frontend compiles: `cd frontend && npx tsc --noEmit`
3. FK relationship tests pass: `cd backend && python -m pytest tests/test_fk_relationships.py -x -v`
4. No regressions in existing dataset tests: `cd backend && python -m pytest tests/test_datasets.py -x`
</verification>

<success_criteria>
- All 4 FK endpoints use `get_db` instead of non-existent `get_session`
- Read endpoints enforce visibility via `check_dataset_access`
- RelatedRecordsPanel has zero hardcoded English strings
- All 4 locale files have `relatedRecords` keys
- Both query hooks handle `isError` with user-facing messages
- test_fk_relationships.py exists with 6+ passing tests
</success_criteria>

<output>
After completion, create `.planning/quick/260322-irw-polishing-what-s-shipped-review-all-the-/260322-irw-SUMMARY.md`
</output>
