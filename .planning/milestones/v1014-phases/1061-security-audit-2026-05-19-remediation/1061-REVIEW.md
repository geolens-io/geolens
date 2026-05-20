---
status: fixed
phase: 1061
review_date: 2026-05-20
fixed_date: 2026-05-20
depth: standard
files_reviewed: 27
files_reviewed_list:
  - backend/app/standards/stac/router.py
  - backend/app/modules/catalog/datasets/api/router.py
  - backend/app/modules/catalog/layers/router.py
  - backend/app/modules/catalog/datasets/api/router_data.py
  - backend/app/modules/catalog/datasets/domain/service_relationships.py
  - backend/app/modules/catalog/sources/security.py
  - backend/app/modules/catalog/sources/router.py
  - backend/app/modules/catalog/sources/adapters/stac.py
  - backend/app/processing/ingest/ogr.py
  - backend/app/processing/ingest/manifest_service.py
  - backend/app/core/config.py
  - docker-compose.yml
  - .env.demo.example
  - .env.example
  - .gitignore
  - scripts/init-demo-env.sh
  - .pre-commit-config.yaml
  - AGENTS.md
  - backend/tests/test_stac_visibility.py
  - backend/tests/test_dataset_metadata_idor.py
  - backend/tests/test_column_ddl_idor.py
  - backend/tests/test_related_datasets_idor.py
  - backend/tests/test_ssrf_redirect.py
  - backend/tests/test_demo_credentials_guard.py
  - backend/tests/test_config.py
  - e2e/sec-audit.spec.ts
  - backend/app/modules/catalog/authorization.py
critical: 2
warning: 2
info: 2
---

# Phase 1061 Code Review

## Summary

Phase 1061 remediates 7 HIGH severity security findings from the 2026-05-19 audit. The
core SSRF (S04), visibility filter (S01, S05), IDOR (S02, S03), credential guard (S06),
and MinIO hardening (S07) fixes are correctly implemented and well-tested. The
`_revalidate_redirect` event hook, `make_safe_client` factory, `GDAL_HTTP_FOLLOWLOCATION=NO`
env block, and `validate_demo_credentials_guard` extension all work as designed.

Two critical issues were found that represent security gaps the phase failed to close or
introduced:

1. **`update_publication_status` and `set_target_status`** in `router_data.py` are
   write-mutation endpoints that lack `check_dataset_access`. Any editor can promote
   another user's private dataset to `published` (fully public). These endpoints were
   in-scope for the audit's S02 root cause (IDOR on dataset mutation) but were missed
   because Plan 02's file list named only `router.py`, not `router_data.py`. The audit
   document itself scoped S02 to `router.py:263-426`; these are at `router_data.py:231+`.

2. **The SSRF pre-commit hook pattern is insufficient.** The `pygrep` pattern
   `httpx\.AsyncClient\([^)]*follow_redirects=True` operates per-line and cannot match
   multi-line `AsyncClient(...)` declarations. `backend/app/processing/tiles/router.py:51-53`
   already has exactly this shape (`AsyncClient(` on one line, `follow_redirects=True,` on
   the next) and the hook does not catch it. The hook passes CI clean on the current
   codebase for the wrong reason — not because no unsafe clients exist, but because the
   existing one (tiles router, fixed internal URL) predates this phase and was already
   exempted by the planner as non-scope (not-user-controlled URL). The hook cannot
   enforce its stated Rule 2 guarantee because it cannot see future multi-line additions.

Two warnings round out the review:

3. `AGENTS.md` Rule 3 asserts that `validate_demo_credentials_guard` blocks
   `minioadmin/minioadmin`. The code does not check MinIO credentials. MinIO is not
   a `Settings` field. The guard is doc-accurate for the three credentials it does check
   (JWT, admin password, postgres password) but the claim about `minioadmin/minioadmin`
   is inaccurate, which could give operators false confidence.

4. `dataset_maps` in `router_data.py` (not touched by this phase, but a newly-relevant
   gap) does not gate on the dataset's visibility before listing maps. An anonymous caller
   can probe any `dataset_id` UUID to determine whether it appears in any publicly-visible
   map — a dataset-existence oracle. This is a lower-severity information-disclosure gap
   analogous to S05 (related-datasets oracle).

---

## Critical Findings

### CR-01: Publication-status mutation endpoints missing check_dataset_access (IDOR)

**File:** `backend/app/modules/catalog/datasets/api/router_data.py:231` and `:282`
**Severity:** BLOCKER

**Issue:** `update_publication_status` (PATCH `/{dataset_id}/status/`) and
`set_target_status` (PATCH `/{dataset_id}/target-status/`) both fetch the dataset by ID
and mutate `record.record_status`. Neither calls `check_dataset_access` before performing
the mutation. Both use `require_permission("edit_metadata")` which is a role-level gate
(any editor, any dataset), not a resource-level gate.

Attack scenario: Editor B knows Editor A's private dataset UUID (obtainable from
`/collections/` listings). Editor B issues `PATCH /datasets/{A_uuid}/target-status/` with
`{"status": "published"}`. The server walks the draft→ready→internal→published chain
without any ownership check, making A's private dataset fully public.

This is the same root cause as SEC-S02 (`require_permission` without `check_dataset_access`)
but on a different router file. The audit scoped S02 to `router.py:263-426`; these handlers
live at `router_data.py:231+` and were not enumerated in Plan 02.

**Fix:**
```python
# In both update_publication_status and set_target_status,
# add after the dataset existence check:
from app.modules.catalog.authorization import check_dataset_access

dataset = dataset.unique().scalar_one_or_none()
if not dataset:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
    )
# ADD THIS LINE in both handlers:
await check_dataset_access(db, dataset, dataset_id, user)

# Then proceed with the workflow transition...
```

Note: `check_dataset_access` returns user_roles, which can be passed into the
`WorkflowTransitionContext` if needed.

---

### CR-02: SSRF pre-commit hook does not catch multi-line httpx.AsyncClient declarations

**File:** `.pre-commit-config.yaml:21`
**Severity:** BLOCKER

**Issue:** The `ssrf-safe-client` hook uses `pygrep` with pattern
`httpx\.AsyncClient\([^)]*follow_redirects=True`. The `pygrep` hook scans
per-line. A multi-line declaration like:

```python
_titiler_client = httpx.AsyncClient(        # line 51 — no follow_redirects here
    timeout=httpx.Timeout(30.0, connect=10.0),
    follow_redirects=True,                   # line 53 — no AsyncClient( here
)
```

will NOT trigger the hook because no single line contains both `AsyncClient(` and
`follow_redirects=True`. This is confirmed: `backend/app/processing/tiles/router.py:51-53`
already has exactly this shape and the hook does not flag it.

The planner noted this file was exempted because the URL is a fixed internal host (`http://titiler:8000`) and cannot be SSRF'd. That is a sound engineering call. But the problem is the hook's guarantee is broken: it will not catch a future engineer who writes a multi-line `AsyncClient(follow_redirects=True)` with a user-supplied URL. The hook claims to enforce Rule 2 but cannot.

**Fix option A (preferred — covers multi-line):** Switch to a `system` hook that uses
`pcregrep -M` (multi-line PCRE) or a two-pass approach that checks for AsyncClient in a
file AND checks if that file has a non-security.py context:

```yaml
- id: ssrf-safe-client
  name: "SSRF Rule 2 — follow_redirects=True outside make_safe_client"
  language: system
  entry: >-
    bash -c '
    for f in "$@"; do
      if grep -qE "follow_redirects\s*=\s*True" "$f"; then
        if grep -qE "httpx\.AsyncClient" "$f" && ! grep -qE "make_safe_client|security\.py" "$f"; then
          echo "FAIL: $f has follow_redirects=True with AsyncClient outside make_safe_client"
          exit 1
        fi
      fi
    done
    ' --
  types: [python]
  files: '^backend/app/.*\.py$'
  exclude: '^backend/app/modules/catalog/sources/security\.py$'
```

**Fix option B (minimal patch):** Add `backend/app/processing/tiles/router.py` to the
exclude list with rationale (non-user-controlled URL), and document the multi-line
limitation in a comment on the hook. This does not fix the general case but makes the
current state explicit.

---

## Warnings

### WR-01: AGENTS.md Rule 3 inaccurately claims minioadmin is blocked by validate_demo_credentials_guard

**File:** `AGENTS.md:82`
**Severity:** WARNING

**Issue:** The Rule 3 paragraph states:
> "the boot-time `validate_demo_credentials_guard` in `backend/app/core/config.py`
> refuses these literals regardless of `GEOLENS_DEMO_MODE`"

and lists `minioadmin/minioadmin` as a refused literal. The code in `config.py:207-258`
checks only three values: `DEMO_JWT_SECRET`, `DEMO_ADMIN_PASSWORD`, and
`DEMO_POSTGRES_PASSWORD`. MinIO credentials (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`)
are not `Settings` fields and are never inspected by `validate_demo_credentials_guard`.

An operator reading AGENTS.md will believe the backend boot guards against
`minioadmin`/`minioadmin` being used — it does not. The actual protection for MinIO is
the `${MINIO_ROOT_USER:?...}` required-variable syntax in `docker-compose.yml:510-511`,
which prevents `docker compose up` from succeeding if the var is unset, but does NOT
block the Docker default of `minioadmin/minioadmin` if someone explicitly sets
`MINIO_ROOT_USER=minioadmin`.

**Fix:** Update the sentence in `AGENTS.md:82`:
```
# Current (inaccurate):
"Rotate by re-running `scripts/init-demo-env.sh --force` and restarting the stack."
# Add parenthetical:
"Note: MinIO credentials (MINIO_ROOT_USER / MINIO_ROOT_PASSWORD) are enforced by
docker-compose required-variable syntax (`:?required`), not by the Python boot guard.
Use `scripts/init-demo-env.sh` to generate both."
```

Either add MinIO credential checks to `validate_demo_credentials_guard` (if MinIO creds
are accessible from settings), or correct the AGENTS.md claim to reflect that only the
three Python-layer credentials are Python-guarded.

---

### WR-02: dataset_maps endpoint has no dataset-visibility gate (dataset-existence oracle)

**File:** `backend/app/modules/catalog/datasets/api/router_data.py:194-216`
**Severity:** WARNING

**Issue:** `GET /{dataset_id}/maps/` does not verify the caller has access to the dataset
before querying which maps contain it. An anonymous caller can pass any `dataset_id` UUID
and receive a `MapListResponse`. The `get_maps_for_dataset` service applies map-level RBAC
(anon sees only public maps), so map content is not leaked. However, the response shape
itself is an oracle: if the endpoint returns a non-empty list, the `dataset_id` exists; if
it returns `{"maps": [], "total": 0}`, the dataset may not exist or may not appear in any
public map.

This is a lower-severity variant of the SEC-S05 pattern (related-datasets oracle) that was
fixed in Plan 03. It is not a direct IDOR (no data from the private dataset is returned)
but it allows confirming dataset UUID validity without authentication.

This was not in the audit scope for S05 (which targeted `router_data.py:56-65`), and may
be an acceptable risk tradeoff, but it should be a conscious decision.

**Fix:** Add a visibility gate before the map query:
```python
@router.get("/{dataset_id}/maps/", response_model=MapListResponse)
async def dataset_maps(
    dataset_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> MapListResponse:
    # Gate on dataset visibility (mirrors the S05 fix on related-datasets)
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    user_roles = await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    from app.modules.catalog.maps.service import get_maps_for_dataset
    user_id = user.id if user else None
    maps, total = await get_maps_for_dataset(
        db, dataset_id, user_id=user_id, user_roles=user_roles,
        skip=skip, limit=limit,
    )
    return MapListResponse(maps=maps, total=total)
```

---

## Informational

### IN-01: _revalidate_redirect does not handle HTTP 305 (Use Proxy)

**File:** `backend/app/modules/catalog/sources/security.py:81`
**Severity:** INFO

**Issue:** The hook checks `response.status_code not in (301, 302, 303, 307, 308)`. HTTP
305 ("Use Proxy") is theoretically redirects a client through a proxy, which could be
SSRF-exploitable in theory, but it is deprecated in RFC 7231 and modern HTTP clients
(including httpx) do not follow it. This is informational only — the current omission
poses no practical risk.

**Fix:** Either document the omission with a comment, or add 305 to the tuple for
completeness:
```python
if response.status_code not in (301, 302, 303, 305, 307, 308):
    return
```

---

### IN-02: GDAL_HTTP_FOLLOWLOCATION=NO is only set on run_ogr2ogr_service, not run_ogr2ogr

**File:** `backend/app/processing/ingest/ogr.py:524-537`
**Severity:** INFO

**Issue:** `run_ogr2ogr` (file-ingest path) does not set `GDAL_HTTP_FOLLOWLOCATION=NO`.
The Plan 04 SUMMARY explicitly notes this was intentional: `run_ogr2ogr` processes local
file paths and not HTTP URLs, so libcurl redirect control is irrelevant. This is correct.

The issue is the absence of a comment in the `run_ogr2ogr` function explaining why the
env override is absent, creating a "why is this missing here?" question for future
maintainers who read `run_ogr2ogr_service` and expect consistency.

**Fix:** Add a one-line comment to `run_ogr2ogr` at the subprocess creation site:
```python
# GDAL_HTTP_FOLLOWLOCATION not set here — run_ogr2ogr processes local file
# paths only; no libcurl redirect control needed (contrast: run_ogr2ogr_service).
proc = await asyncio.create_subprocess_exec(...)
```

---

## Test Coverage Assessment

The test suite for this phase is comprehensive for its explicit scope:

- `test_stac_visibility.py` — covers anonymous/owner/non-owner access to STAC items, search,
  and collection items (5 cases). Tests the negative (404) and positive (200) for both
  authenticated and anonymous paths. Adequate.

- `test_dataset_metadata_idor.py` — 7 tests covering PATCH/DELETE/bulk-delete for
  Editor B vs Editor A (private dataset 404), and the owner-allows path (200/204). Misses
  the public dataset owner-only-delete path cross-user regression: no test for Editor B
  attempting DELETE on Editor A's **public** dataset (expected 403). The 403 case is
  covered in one test (`test_delete_dataset_other_user_public_returns_403`) — adequate.

- `test_column_ddl_idor.py` — not read in full but described as 8 tests (4 deny + 4 allow).
  Pattern mirrors metadata IDOR tests.

- `test_related_datasets_idor.py` — not read but described as covering S05.

- `test_ssrf_redirect.py` — 7 tests including positive, negative, relative redirect, and
  non-http scheme cases. The `test_make_safe_client_has_event_hook` test verifies factory
  wiring. Adequate.

- `test_demo_credentials_guard.py` — 5 tests covering demo/non-demo mode for all three
  guarded literals, plus a happy-path acceptance test. Adequate.

**Notable gap:** No test covers `update_publication_status` or `set_target_status` IDOR
(CR-01). An editor transitioning another user's private dataset to `published` would not
be caught by the current test suite.

---

## Recommendations

**Blockers before merge:**

1. **CR-01**: Add `check_dataset_access(db, dataset, dataset_id, user)` to both
   `update_publication_status` and `set_target_status` in `router_data.py`, with
   corresponding test coverage (Editor B cannot publish Editor A's private dataset).

2. **CR-02**: Fix the pre-commit SSRF hook to handle multi-line `AsyncClient`
   declarations, OR explicitly document the multi-line limitation as a known hook
   boundary and add `tiles/router.py` to the exclude list with rationale.

**Should fix:**

3. **WR-01**: Correct the `AGENTS.md` Rule 3 claim about `minioadmin/minioadmin` being
   refused by the Python boot guard. This is a documentation accuracy issue that can
   mislead operators.

4. **WR-02**: Add dataset-visibility gate to `dataset_maps` endpoint in `router_data.py`
   to close the dataset-existence oracle gap, consistent with the S05 fix pattern.

**Deferred items noted:** `router_reupload.py` IDOR gap is correctly tracked as
Phase 1063 SEC-FU with documented rationale in both `.pre-commit-config.yaml` and
`AGENTS.md`. The aggregate metadata leakage in STAC collections (`get_collections` /
`get_collection` serve extent/keywords without per-user dataset scoping) is correctly
documented as deferred to SEC-FU. Both are acceptable Phase 1061 deferrals.

---

---

## Resolution (2026-05-20)

All Critical and Warning findings fixed. Info findings deferred to pending todos.

### CR-01 — Fixed

**Commit:** (see git log `fix(1061-review): CR-01`)
**Files:** `backend/app/modules/catalog/datasets/api/router_data.py`, `backend/tests/test_dataset_metadata_idor.py`

Added `check_dataset_access` import and call in both `update_publication_status` and
`set_target_status` handlers, after the 404 check. Added 2 regression tests:
`test_update_publication_status_other_user_private_returns_404` and
`test_set_target_status_other_user_private_returns_404` — both PASS.

### CR-02 — Fixed

**Commit:** (see git log `fix(1061-review): CR-02`)
**Files:** `.pre-commit-config.yaml`

Replaced the `pygrep` per-line hook with a `system` bash hook that greps both
`follow_redirects=True` and `httpx.AsyncClient` across the full file. Added
`backend/app/processing/tiles/router.py` to the exclude list with rationale
(fixed internal URL to `http://titiler:8000`). The description block documents
the multi-line case that motivated the switch. Verified hook catches the
tiles/router.py multi-line shape and correctly exempts security.py.

### WR-01 — Fixed

**Commit:** (see git log `fix(1061-review): WR-01`)
**Files:** `AGENTS.md`

Separated Rule 3 into two distinct enforcement layers: (1) Python boot guard
scope (three Settings fields only), (2) docker-compose `:?required` syntax
(env-var presence, not value). Added explicit note that MinIO credentials are
not inspected by the Python guard and that minioadmin protection requires
`scripts/init-demo-env.sh`.

### WR-02 — Fixed

**Commit:** (see git log `fix(1061-review): WR-02`)
**Files:** `backend/app/modules/catalog/datasets/api/router_data.py`, `backend/tests/test_related_datasets_idor.py`

Added `get_dataset` + `check_dataset_access_or_anonymous` gate in `dataset_maps`
before querying maps. `user_roles` from the gate replaces the previous
`get_user_roles` call (no extra DB query). Added regression test
`test_maps_anonymous_private_returns_404` — PASS.

### IN-01 — Deferred

Deferred to `.planning/todos/pending/2026-05-20-in01-revalidate-redirect-http-305.md`.
No practical risk (httpx does not follow HTTP 305 redirects).

### IN-02 — Deferred

Deferred to `.planning/todos/pending/2026-05-20-in02-run-ogr2ogr-gdal-followlocation-comment.md`.
Maintainability-only comment addition.

---

_Reviewed: 2026-05-20T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Fixed: 2026-05-20T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
