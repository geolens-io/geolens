---
phase: 1081-test-fixture-assertion-drift
plan: "01"
subsystem: backend/tests
tags: [pytest, password-policy, SEC-S16, test-fixture-drift, hygiene, TD-02, TD-03]
requirements: [TD-02, TD-03]

dependency_graph:
  requires: []
  provides: [ADMIN-05-pin-restored]
  affects: [backend/tests/test_phase_279_user_lifecycle.py]

tech_stack:
  added: []
  patterns: [SEC-S16-compliant-test-fixture, project-standard-TestPass1234]

key_files:
  modified:
    - backend/tests/test_phase_279_user_lifecycle.py

decisions:
  - "Used TestPass1234! (13 chars, 4 classes) to mirror conftest.py:491 and test_password_policy.py:37 — single-sourced project standard"
  - "Inline literals (not module-level constant) per plan constraint — each test reads clearly on its own"
  - "One atomic commit for both fixtures — shared root cause (SEC-S16 policy drift)"

metrics:
  duration: "~8 minutes"
  completed: "2026-05-21"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 1081 Plan 01: TD-02 + TD-03 Register-Audit Password Fixture Alignment Summary

One-liner: Replace two SEC-S16-noncompliant `"securepass123"` test fixtures with the project-standard `"TestPass1234!"` literal to restore the ADMIN-05 audit-event pin under the current password policy.

## What Was Done

Task 1 replaced the weak password literal `"securepass123"` (lowercase + digit = 2 character classes, violating the SEC-S16 3-of-4 diversity rule) with `"TestPass1234!"` in two register-audit integration tests that had drifted from the v1014 SEC-S16 policy. A 4-line comment block citing the root cause was added above each change.

## Exact Diff of Password Fixture Changes

### Test 1: `test_register_emits_user_register_audit` (TD-02)

```diff
-    resp = await client.post(
-        "/auth/register/",
-        json={
-            "username": username,
-            "password": "securepass123",
-            "email": email,
-        },
-    )
+    # TD-02 (Plan 1081-01): v1014 SEC-S16 enforces 12-char minimum + 3-of-4 class
+    # diversity at validate_password_complexity. The prior "securepass123" literal
+    # (lowercase + digit = 2 classes) fails the 3-of-4 rule before the register
+    # audit path runs. "TestPass1234!" mirrors conftest.py:491 / test_password_policy.py:37.
+    resp = await client.post(
+        "/auth/register/",
+        json={
+            "username": username,
+            "password": "TestPass1234!",
+            "email": email,
+        },
+    )
```

**Lines modified:** comment block inserted before line 151 (originally line 150); password literal at line 158 (was line 154).

### Test 2: `test_register_disabled_does_not_emit_audit` (TD-03)

```diff
-    resp = await client.post(
-        "/auth/register/",
-        json={
-            "username": f"shouldfail_{unique}",
-            "password": "securepass123",
-        },
-    )
+    # TD-03 (Plan 1081-01): v1014 SEC-S16 enforces 12-char minimum + 3-of-4 class
+    # diversity at validate_password_complexity. The prior "securepass123" literal
+    # (lowercase + digit = 2 classes) fails the 3-of-4 rule before the registration
+    # disabled path runs. "TestPass1234!" mirrors conftest.py:491 / test_password_policy.py:37.
+    resp = await client.post(
+        "/auth/register/",
+        json={
+            "username": f"shouldfail_{unique}",
+            "password": "TestPass1234!",
+        },
+    )
```

**Lines modified:** comment block inserted before line 207 (originally line 202); password literal at line 214 (was line 206).

## pytest Exit Codes

| Invocation | Exit Code | Result |
|-----------|-----------|--------|
| `pytest tests/test_phase_279_user_lifecycle.py::test_register_emits_user_register_audit -x` | 0 | PASSED |
| `pytest tests/test_phase_279_user_lifecycle.py::test_register_disabled_does_not_emit_audit -x` | 0 | PASSED |
| `pytest tests/test_phase_279_user_lifecycle.py -x` | 0 | 4/4 PASSED |

## Production Code Confirmation

`git diff --stat backend/app/` produced zero output. No production code was modified.

## Password Fixture: SEC-S16 Compliance

**Fixture used:** `"TestPass1234!"`

| SEC-S16 Rule | Requirement | Value | Status |
|---|---|---|---|
| Minimum length | >= 12 characters | 13 characters | PASS |
| Lowercase class | present | `estass` (T-e-s-t-P-a-s-s) | PASS |
| Uppercase class | present | `T`, `P` | PASS |
| Digit class | present | `1`, `2`, `3`, `4` | PASS |
| Symbol class | present | `!` | PASS |
| Class diversity | >= 3 of 4 classes | 4/4 classes | PASS (max margin) |

`"TestPass1234!"` satisfies all four character classes — it passes even if `PASSWORD_REQUIRE_CLASSES` is raised to 4 without further test edits. This mirrors `conftest.py:491` and `test_password_policy.py:37` (both use the same literal), keeping the project standard single-sourced.

## Path Correction Surfaced

The REQUIREMENTS.md, ROADMAP, and 1081-CONTEXT.md name the TD-02 and TD-03 failing tests as:
- `test_register_password_too_short` (TD-02)
- `test_register_password_diversity` (TD-03)

**Those test names do not exist in the codebase.** `grep -rln "test_register_password_too_short\|test_register_password_diversity" backend/` returns zero hits.

The actual failing tests (as discovered during Phase 1075-05 VERIFICATION.md and confirmed during Plan 1081-01 planning) are:
- `test_phase_279_user_lifecycle.py::test_register_emits_user_register_audit` (TD-02)
- `test_phase_279_user_lifecycle.py::test_register_disabled_does_not_emit_audit` (TD-03)

**Root cause of the naming drift:** The original REQUIREMENTS.md entries were written based on the _intended_ test names from the Phase 279 planning document, which were never used when the tests were implemented. The implemented tests used descriptive names reflecting their actual contract (ADMIN-05 audit-event emission).

**Recommendation for close-gate plan (Phase 1083, TD-08):** Update REQUIREMENTS.md rows TD-02 and TD-03 to reference the correct test names. Alternatively, add a `## Path corrections from v1018 planning` section to `.planning/v1017-MILESTONE-AUDIT.md` so future audits do not re-discover this drift. The spirit of TD-02/TD-03 ("align password tests to SEC-S16") is fully satisfied — only the test-name documentation is stale.

## Deviations from Plan

None. Plan executed exactly as written.

## Commit

- `9bc2294b`: `test(1081-01): TD-02/TD-03 align register-audit password fixtures to SEC-S16`

## Self-Check: PASSED

- [x] `backend/tests/test_phase_279_user_lifecycle.py` — modified, verified with git log
- [x] commit `9bc2294b` — exists (`git log --oneline -1` confirms)
- [x] `grep -n '"password": "securepass123"'` — returns 0 hits (the weak literal is fully gone as a live JSON value; it appears only in the 4-line explanation comments)
- [x] `grep -n '"password": "TestPass1234!"'` — returns 2 hits at lines 158 and 214
- [x] `grep -c "pytest.mark.skip" backend/tests/test_phase_279_user_lifecycle.py` — returns 0
- [x] `git diff --stat backend/app/` — empty (zero production code changes)
- [x] All 4 tests in file pass: exit code 0
