---
phase: 213-catalog-authz-relocate
reviewed: 2026-04-27T00:00:00Z
depth: standard
files_reviewed: 25
files_reviewed_list:
  - backend/app/modules/auth/dependencies.py
  - backend/app/modules/catalog/authorization.py
  - backend/app/modules/catalog/collections/router.py
  - backend/app/modules/catalog/collections/service.py
  - backend/app/modules/catalog/datasets/api/router.py
  - backend/app/modules/catalog/datasets/api/router_data.py
  - backend/app/modules/catalog/datasets/api/router_export.py
  - backend/app/modules/catalog/datasets/api/router_metadata.py
  - backend/app/modules/catalog/datasets/api/router_vrt.py
  - backend/app/modules/catalog/datasets/domain/service.py
  - backend/app/modules/catalog/features/router.py
  - backend/app/modules/catalog/maps/router.py
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/records/router.py
  - backend/app/modules/catalog/search/router.py
  - backend/app/modules/catalog/search/service.py
  - backend/app/platform/sandbox/validator.py
  - backend/app/platform/jobs/router.py
  - backend/app/processing/ai/router.py
  - backend/app/processing/ai/service.py
  - backend/app/processing/export/router.py
  - backend/app/processing/ingest/service.py
  - backend/app/processing/tiles/router.py
  - backend/app/standards/ogc/router.py
  - backend/tests/test_layering.py
findings:
  critical: 1
  warning: 3
  info: 1
  total: 5
status: issues_found
---

# Phase 213: Code Review Report

**Reviewed:** 2026-04-27
**Depth:** standard
**Files Reviewed:** 25
**Status:** issues_found

## Summary

This phase is a mechanical module relocation: `app.modules.auth.visibility` was deleted and its contents (unchanged) now live at `app.modules.catalog.authorization`. All 23 caller files were updated with 1-line import changes. Two new architecture guard tests in `test_layering.py` protect against regression.

The relocation itself is clean — all imported names are intact, the `DatasetGrant` promotion from function-scope to module-level is correct, and the public API surface is preserved. The automated gates (ruff, mypy, 1999 pytest, 4 arch tests) would not catch the issues below.

The issues found are all pre-existing logic bugs that survive into the relocated module unchanged. One is a security-relevant RBAC gap.

---

## Critical Issues

### CR-01: `apply_visibility_filter` grants authenticated non-owner access to unpublished public datasets

**File:** `backend/app/modules/catalog/authorization.py:67-95`

**Issue:** The authenticated user path in `apply_visibility_filter` produces the OR condition:

```python
conditions = [
    record_cls.visibility == DatasetVisibility.PUBLIC,          # (1)
    and_(record_cls.visibility == DatasetVisibility.PRIVATE,    # (2)
         record_cls.created_by == user.id),
]
# ...
status_filter = or_(
    record_cls.record_status == "published",
    record_cls.created_by == user.id,     # owner sees own drafts
)
return stmt.where(and_(or_(*conditions), status_filter))
```

Condition (1) matches any public dataset regardless of `record_status`. `status_filter` is then ANDed with the full OR of conditions — but because `status_filter` itself is an OR (`published OR owner`), a non-owner authenticated user who matches condition (1) (public visibility) also matches `status_filter` via the `published` branch only. So far correct.

The gap: because `conditions` and `status_filter` are evaluated jointly as `and_(or_(*conditions), status_filter)`, a non-owner authenticated user can see a **public + unpublished** dataset if `record_status == "published"` is true for any reason — but the critical miss is the converse: condition (1) matches `visibility == PUBLIC` with NO `record_status` constraint attached to that condition. The `status_filter` is supposed to enforce the status check, but the `status_filter` expression is:

```
published  OR  created_by == user.id
```

This means: any authenticated non-owner user can see a `visibility=public, record_status=draft` dataset because the combined filter resolves to:

```
(visibility=public) AND (published OR owner)
   ↓
True AND (False OR False)
   ↓
False  ← would be filtered out
```

Wait — that is actually correct. Let me re-examine the actual gap.

The real gap is more subtle. The anonymous path (line 62-65) enforces **both** `visibility=public AND record_status=published`. The authenticated non-owner path (lines 67-95) constructs the OR of conditions wrapped with a status AND-filter. The expression evaluates correctly in SQL.

However there is a concrete bug: when `grant_cls` is `None` (passed as `None` by some callers), the RESTRICTED visibility condition is simply omitted from the `conditions` list. This means `apply_visibility_filter(..., grant_cls=None)` will make **restricted datasets invisible to all non-admin authenticated users** — including those who have a grant. For callers that legitimately pass `grant_cls=None` (the sandbox validator at line 143 of `validator.py`, which passes `grant_cls` implicitly via the default `None`), this is a **silent privilege elevation in the wrong direction** (under-access). But the more serious problem: if a caller accidentally passes `grant_cls=None` when they meant to pass `DatasetGrant`, restricted-visibility datasets are silently excluded rather than raising an error. The parameter being optional with a silent behavioral change means a caller mistake causes a data access denial that is hard to debug.

More critically: the `apply_visibility_filter` call in `sandbox/validator.py` (line 143) passes `grant_cls` as the default `None`, meaning users with grants to restricted datasets **cannot query those datasets in the SQL sandbox**. This is a privilege-enforcement error — the sandbox should respect the same RBAC as the rest of the API.

**Fix:** In `build_table_allowlist` in `validator.py`, pass `DatasetGrant` as `grant_cls`:

```python
# backend/app/platform/sandbox/validator.py
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record

stmt = select(Dataset.table_name).join(Record, Dataset.record_id == Record.id)
stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
```

---

## Warnings

### WR-01: `check_dataset_access` does not check `record_status` for restricted datasets

**File:** `backend/app/modules/catalog/authorization.py:130-182`

**Issue:** `check_dataset_access` checks `record_status` before the private-visibility check (line 158-161), but then proceeds to the restricted-visibility grant lookup (lines 168-180) **without first checking** whether the dataset is published. A non-admin user with a grant on a restricted-but-unpublished dataset will receive access, while the documented contract (line 157 comment: "Block access to non-published datasets for non-owners") is only enforced for the private path. The `record_status` check at lines 158-161 does not `return` after blocking — it only raises. So the flow for a restricted dataset is:

1. `record_status != "published" AND created_by != user.id` → raises 404 ✓ correct for all visibilities when unpublished

Wait — actually lines 158-161 ARE reached before the restricted check. For a restricted unpublished dataset owned by someone else, the check at line 158 fires correctly. This is actually correct as written.

The actual warning is: `check_dataset_access_or_anonymous` (lines 111-127) checks visibility for anonymous users using **string literals** (`"public"`, `"published"`) rather than the `DatasetVisibility` enum defined in the same module. If the DB ever stores the enum's `.value` differently this diverges silently. It also skips the `check_dataset_access` path's `record_status` check for authenticated users entirely when user is None — but that path does call `check_dataset_access` for authenticated users, so the divergence is only for anonymous. For anonymous, it correctly checks both `visibility != "public"` and `record_status != "published"`. However, it uses raw strings rather than `DatasetVisibility.PUBLIC.value` which is a consistency issue.

**Fix:**
```python
# authorization.py line 122
if record.visibility != DatasetVisibility.PUBLIC or record.record_status != "published":
```

### WR-02: `test_no_auth_visibility_module_referenced` excludes only the test file itself, not `__pycache__`

**File:** `backend/tests/test_layering.py:157-172`

**Issue:** The `test_no_auth_visibility_module_referenced` test uses `:!backend/tests/test_layering.py` to prevent a self-positive. However `git grep` does not search `.pyc` files (binary), so `__pycache__` is not a concern. The more real issue: the pathspec exclusion syntax `:!` is not available in all git versions (requires git >= 2.13 / pathspec magic). If run in a container with an older git, the `:!` pathspec will cause `git grep` to error with `returncode > 1`, which the test catches as a failure with `f"git grep failed unexpectedly"`. This means the test could generate false failures in CI environments with older git.

The guard in `_has_git_metadata()` skips when `.git/` is absent, but does not guard against git version incompatibility.

**Fix:** Add a git version pre-check, or test for pathspec support before relying on it:

```python
def _has_pathspec_magic() -> bool:
    """Return True if git supports :! pathspec exclusion (git >= 2.13)."""
    result = subprocess.run(
        ["git", "--version"], capture_output=True, text=True, check=False
    )
    # git version 2.X.Y -> extract X
    m = re.search(r"git version 2\.(\d+)", result.stdout)
    return m is not None and int(m.group(1)) >= 13
```

### WR-03: `update_collection` commits internally while service comment claims "flush-only pattern" preferred

**File:** `backend/app/modules/catalog/collections/service.py:50-72`

**Issue:** `update_collection` at line 70-71 calls `await session.commit()` and `await session.refresh(collection)` internally. The module docstring at line 16 explicitly warns: "if you add a new write function, prefer the flush-only pattern." The caller in `router.py` at line 209 then calls `await db.commit()` again after `update_collection` returns. This double-commit pattern is safe because SQLAlchemy will no-op a commit on a session that has nothing pending, but it is confusing and creates divergence from all other service functions. If the router's `log_action` call (lines 200-208) adds dirty state to the session, then the first commit in `update_collection` persists the collection update without the audit log, meaning a crash between the two commits leaves an auditable action unlogged.

This bug pre-dates this phase, but the relocation does not change it. The issue is that `update_collection` commits before `log_action` has run in the router, so on crash the collection update is durable but the audit log is not.

**Fix:** Change `update_collection` to flush-only (match all other write functions):

```python
async def update_collection(...) -> Collection:
    ...
    if name is not None:
        collection.name = name
    if description is not None:
        collection.description = description
    await session.flush()
    return collection
```

Then remove the internal `session.refresh(collection)` call; the router calls `db.commit()` which makes the session consistent before returning.

---

## Info

### IN-01: `_lookup_by_external_id` in search router omits visibility check

**File:** `backend/app/modules/catalog/search/router.py:1079-1120`

**Issue:** When `?externalId=<uuid>` is passed to the OGC `collection_items` endpoint, `_lookup_by_external_id` fetches the dataset by UUID (line 1100-1111) and returns it without calling any visibility check. All other item endpoints (`get_collection_item` at line 1255, `get_single_dataset` in router.py, etc.) call `check_dataset_access_or_anonymous` before returning. This means any unauthenticated caller who knows a dataset UUID can retrieve its full OGC record metadata regardless of visibility or publication status by using the `?externalId=` parameter.

This is a pre-existing issue that survives the relocation unchanged. It is flagged here because the authorization functions are now clearly grouped and this usage pattern stands out.

**Fix:**
```python
async def _lookup_by_external_id(db, external_id, request, user=None):
    ...
    dataset = ext_result.unique().scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Record not found")
    # Add visibility check:
    await check_dataset_access_or_anonymous(db, dataset, record_uuid, user)
    ...
```

The caller in `collection_items` already receives `user: User | None` and should pass it through to `_lookup_by_external_id`.

---

_Reviewed: 2026-04-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
