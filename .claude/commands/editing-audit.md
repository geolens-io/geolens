# /editing-audit - Feature & Schema Editing Audit

Audit GeoLens editing workflows for feature attributes, feature geometry, dataset metadata drafts, schema/structure edits, permission boundaries, cache invalidation, map-builder compatibility, and test coverage. Every finding must say what edit can be made, where it persists, and what downstream surface can drift.

**Usage:** `/editing-audit` (full audit) or `/editing-audit <scope>` where scope is `features`, `geometry`, `schema`, `metadata`, `permissions`, `ui`, or `tests`

Arguments: $ARGUMENTS

---

## INTAKE (Serial - do this first)

### Step 0: Determine scope

```bash
SCOPE="${ARGUMENTS:-full}"
echo "Scope: $SCOPE"
```

Scope routing:
- `features` or `geometry`: run Feature Editing Contract, authorization, persistence, and tests.
- `schema`: run Schema and Structure Editing plus downstream invalidation checks.
- `metadata`: run metadata draft, publication, `WorkflowExtension`, and cache invalidation checks.
- `permissions`: focus on `PermissionExtension`, dataset grants, roles, and cross-user edit denial.
- `ui`: focus on frontend editing controls, disabled states, dirty-state handling, and builder compatibility.
- `tests`: focus on backend/frontend/E2E coverage only.
- `full`: run every section.

State the resolved scope in the report and mark skipped sections explicitly.

### Step 1: Inventory editing surfaces

```bash
# Backend editing and dataset data/metadata surface
find backend/app/modules/catalog/features backend/app/modules/catalog/datasets -type f -name "*.py" 2>/dev/null | sort
grep -rn "patch\|put\|delete\|update\|edit\|schema\|column\|geometry" backend/app/modules/catalog/ --include="*.py" 2>/dev/null

# Frontend editing surface
find frontend/src/api frontend/src/components/dataset frontend/src/hooks -type f 2>/dev/null | sort | grep -Ei "feature|edit|schema|metadata|attribute|draft|dataset"
grep -rn "useFeatureEditing\|useDraftEditing\|SchemaEditor\|AttributeTable\|PendingEditsBar" frontend/src/ --include="*.ts" --include="*.tsx" 2>/dev/null

# Tests
find backend/tests frontend/src e2e -type f 2>/dev/null | sort | grep -Ei "feature|schema|edit|metadata|attribute|dataset-detail"
```

### Step 2: Read canonical source files

```bash
for f in \
  backend/app/modules/catalog/features/router.py \
  backend/app/modules/catalog/features/service.py \
  backend/app/modules/catalog/features/schemas.py \
  backend/app/modules/catalog/datasets/api/router_data.py \
  backend/app/modules/catalog/datasets/api/router_metadata.py \
  backend/app/modules/catalog/datasets/domain/schemas.py \
  backend/app/modules/catalog/datasets/domain/service_metadata.py \
  backend/app/modules/catalog/datasets/domain/service_query.py \
  backend/app/modules/catalog/datasets/domain/column_stats.py \
  backend/app/modules/catalog/datasets/domain/_sql_safety.py \
  backend/app/modules/catalog/authorization.py \
  backend/app/modules/auth/dependencies.py \
  backend/app/platform/extensions/protocols.py \
  backend/app/platform/extensions/defaults.py; do
  echo "=== $f ==="
  cat "$f" 2>/dev/null
done

for f in \
  frontend/src/api/features.ts \
  frontend/src/api/datasets.ts \
  frontend/src/components/dataset/AttributeTable.tsx \
  frontend/src/components/dataset/SchemaEditor.tsx \
  frontend/src/components/dataset/SchemaDiffView.tsx \
  frontend/src/components/dataset/PendingEditsBar.tsx \
  frontend/src/components/dataset/hooks/use-feature-editing.ts \
  frontend/src/components/dataset/hooks/use-draft-editing.ts; do
  echo "=== $f ==="
  cat "$f" 2>/dev/null
done
```

### Step 3: Optional live checks

```bash
# Discover current OpenAPI paths related to editing
API_ORIGIN="${API_ORIGIN:-http://localhost:${API_PORT:-8001}}"
curl -s "$API_ORIGIN/openapi.json" 2>/dev/null | python3 -c "
import json, sys
spec = json.load(sys.stdin)
for p in sorted(spec.get('paths', {})):
    if any(k in p.lower() for k in ('feature', 'metadata', 'schema', 'data')):
        methods = sorted(spec['paths'][p])
        print(p, methods)
" 2>/dev/null || echo "NO_RUNNING_INSTANCE"

# Run related browser smoke if available
curl -sf http://localhost:8080/health >/dev/null 2>&1 && npx playwright test e2e/dataset-detail.spec.ts --project=chromium
```

---

## AUDIT CHECKS

### 1. Feature editing contract

Verify:
- create/update/delete operations authorize by dataset and role, not just feature id
- edit/export/dataset-access decisions pass through `PermissionExtension` seams where applicable, with safe Community defaults
- metadata/status publication transitions pass through `WorkflowExtension` seams where applicable
- feature ids/gids are stable across pagination, sorting, filtering, and reupload
- attribute edits validate unknown fields, read-only fields, nullability, enum/options, and type coercion
- geometry edits validate GeoJSON shape, SRID, dimensionality, bounds, empty geometries, and invalid rings
- updates are transactional and return the persisted feature, not the optimistic request body

Flag as P0 when one user can edit another user's dataset, geometry can be corrupted, or partial edits persist after failure.

### 2. Schema and structure editing

Check:
- column add/rename/drop/type-change actions are explicitly supported or clearly blocked
- identifier quoting protects dynamic table and column operations
- destructive edits require confirmation and explain data loss
- schema diffs include old name/type/nullability/default and new name/type/nullability/default
- schema changes refresh column stats, search metadata, validation state, builder property dropdowns, and API schemas
- unsupported edits fail before mutating data

If schema editing is UI-only or metadata-only, verify the UI copy and API names make that boundary impossible to misunderstand.

### 3. Metadata draft editing

Check:
- draft state, pending edits, save, discard, conflict, and validation errors are deterministic
- save operations are scoped to editable fields and cannot overwrite server-owned fields
- concurrent edits have either version checks or clear last-write-wins behavior
- changes invalidate React Query caches for detail, search, records, maps, and related panels

### 4. Downstream synchronization

Editing must keep these surfaces coherent:
- dataset detail tabs and attribute table
- map builder layers, filters, labels, popup config, and data-driven styles
- public viewer/share/embed read-only behavior
- search, OGC API Features/Records, STAC, DCAT, and export responses
- extents, geometry type, feature count, quality score, and validation status
- audit logs and version/change history

Flag stale downstream data as P1 when users can save an edit and immediately see conflicting truth elsewhere.

### 5. Frontend UX and accessibility

Verify:
- edit affordances are visible only when permitted and disabled states explain why
- keyboard users can enter, change, save, cancel, and recover from errors
- optimistic updates roll back on API failure
- bulk/inline editing controls do not lose focus or edits on pagination/filter changes
- validation errors are field-specific and screen-reader discoverable

### 6. Test coverage

Require focused tests for:
- authorized edit success and unauthorized/readonly rejection
- bad geometry, unknown field, wrong type, nullability, and reserved-column failures
- schema diff and destructive edit confirmation behavior
- React Query invalidation after save/discard
- E2E persistence: edit -> reload -> dataset detail/map builder/export reflects change

Missing persistence or permission tests for real editing endpoints are P1.

---

## DELIVERY

Write full reports to `docs-internal/audits/editing-audit-{YYYYMMDD}.md`.

Report structure:
- Findings first, sorted P0/P1/P2
- Editing capability matrix: feature, geometry, schema, metadata
- Downstream drift risks
- Missing tests
- Remediation plan with owner files

---

## RELATIONSHIP TO OTHER COMMANDS

- `/builder-audit` checks map styling and builder behavior. This command checks saved data/editing semantics.
- `/api-contract` checks backend/frontend schema drift. This command checks edit-specific persistence and validation.
- `/test-audit` checks test health. This command identifies the editing test scenarios that must exist.
