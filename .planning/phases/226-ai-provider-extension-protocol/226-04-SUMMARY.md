---
phase: 226-ai-provider-extension-protocol
plan: "04"
subsystem: testing (architecture guards + seam tests)
tags:
  - architecture
  - test
  - guard
  - entry-points
  - ai-provider

dependency_graph:
  requires:
    - 226-01 (AIProviderExtension Protocol + defaults — get_ai_provider() accessor, DefaultAnthropicProvider, DefaultOpenAICompatibleProvider)
    - 226-02 (dispatch migration — all callers use get_ai_provider(); zero if/elif provider == branches in migrated paths)
  provides:
    - Architecture guard test test_no_hardcoded_ai_provider_branches (AIEXT-03/05) in test_layering.py
    - Entry-points seam tests in test_ai_provider_extension.py (AIEXT-02, AIEXT-04, D-06)
    - Negative-control verification: guard catches forbidden branches and surfaces offending line
  affects:
    - 226 final close gate (Phase 229 audit)
    - Future phases that add AI provider dispatch sites

tech-stack:
  added: []
  patterns:
    - "Architecture guard via git grep -P (PCRE): preferred over -E (ERE) when using (?:...) non-capturing groups — POSIX ERE in git grep does not support ?:"
    - "Autouse _clean_registry fixture replicated inline (not imported) per RESEARCH.md Pitfall 6 — prevents inter-test-file registry leakage"
    - "Negative-control verification: insert forbidden branch → confirm test FAILS with offending line surfaced → revert → confirm PASSES"

key-files:
  created:
    - backend/tests/test_ai_provider_extension.py
  modified:
    - backend/tests/test_layering.py

key-decisions:
  - "Use git grep -P (PCRE) instead of -E (ERE) for the architecture guard regex — POSIX ERE rejects (?:...) non-capturing groups, causing rc=128. PCRE supports the full regex as specified in the plan's SC#3 binding."
  - "Regex scope: backend/app/processing/ (wider than backend/app/processing/ai/) — catches future drift; non-AI files (ingest/service.py, raster/vrt.py) don't match because their if/elif patterns use storage_provider not provider."
  - "Three pathspec exclusions: :!backend/tests/ (fixture stubs), :!backend/app/processing/ai/streaming.py (RESEARCH.md Open Question 1), :!backend/app/processing/ai/metadata_service.py (RESEARCH.md Open Question 2)."

requirements-completed:
  - AIEXT-04
  - AIEXT-05

duration: ~30min
completed: "2026-05-02"
---

# Phase 226 Plan 04: Architecture Guard + Entry-Points Seam Test Summary

**Architecture-guard test and entry-points dispatch seam test close AIEXT-04 and AIEXT-05; negative-control verification confirms the guard catches forbidden branches with offending line surfaced.**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-05-02
- **Tasks:** 4 (2 code, 1 verification, 1 acceptance gate)
- **Files created:** 1 (`test_ai_provider_extension.py`)
- **Files modified:** 1 (`test_layering.py`)

## Accomplishments

- Architecture-guard test `test_no_hardcoded_ai_provider_branches` added to `test_layering.py` — PCRE regex `if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)` scans `backend/app/processing/` with 3 pathspec exclusions; passes on post-Plan-02 codebase; all 11 test_layering tests still green.
- New file `backend/tests/test_ai_provider_extension.py` with 3 tests: smoke (D-16/AIEXT-02), ValueError (D-06), and entry-points overlay dispatch (D-15/AIEXT-04/SC#5). All 3 pass.
- Negative-control verification completed: temporarily inserting `if provider == "anthropic":` in `sql_generator.py` caused the guard to FAIL with the offending line surfaced; reverting restored PASS; git working tree confirmed clean.
- Full suite: **2053 passed** (baseline 2050 + 4 new tests — 1 architecture guard + 3 entry-points); 0 failures; ruff clean.

## Task Commits

1. **Task 1: Architecture guard + module docstring** - `5610464c` (feat)
2. **Task 2: Entry-points seam test file** - `433c3e81` (feat)
3. **Task 3: Negative-control verification** - no commit (verification-only; git working tree was restored clean)
4. **Task 4: Full-suite acceptance gate** - no commit (verification-only)

## Files Created/Modified

- `backend/tests/test_layering.py` — Updated module docstring to credit Phase 226 alongside 212-225; appended `test_no_hardcoded_ai_provider_branches` with PCRE regex, `_has_git_metadata()` + `_has_pathspec_magic()` skip guards, 3 pathspec exclusions, and detailed docstring documenting why each exclusion is intentional.
- `backend/tests/test_ai_provider_extension.py` (NEW) — Autouse `_clean_registry` fixture (isolates registry per Pitfall 6), three tests: `test_default_providers_registered`, `test_unknown_provider_raises_value_error`, `test_overlay_provider_is_dispatched` (`@pytest.mark.asyncio`).

## Decisions Made

**Deviation from plan regex flag: `-E` → `-P` (PCRE)**

The plan specified `git grep -n -E` with regex `r"if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)"`. Apple git 2.50.1's `-E` (POSIX ERE) does not support `(?:...)` non-capturing group syntax — it returned rc=128 with `fatal: command line: repetition-operator operand invalid`. Switched to `-P` (PCRE) which accepts the full regex exactly as written in the plan, exits 0 for matches and 1 for no-matches (same semantics). The regex itself is unchanged. PCRE is available in both Apple Git and standard Linux git ≥ 1.7.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] git grep flag changed from -E to -P for PCRE regex support**
- **Found during:** Task 1 (test_no_hardcoded_ai_provider_branches)
- **Issue:** The plan-specified regex `(?:anthropic|openai_compatible)` uses a PCRE non-capturing group. Apple Git 2.50.1's `-E` (POSIX ERE mode) rejects this with rc=128 ("repetition-operator operand invalid"). The test was failing at the `result.returncode != 1` guard, not passing.
- **Fix:** Changed `"-E"` to `"-P"` in the subprocess.run call. The regex itself is unchanged. `-P` (PCRE) is supported by git ≥ 1.7 including macOS's Apple Git. Exit code semantics are identical (0 = match found, 1 = no match, other = error).
- **Files modified:** `backend/tests/test_layering.py`
- **Verification:** Test passed after the change; all 11 test_layering tests still green; ruff clean.
- **Committed in:** `5610464c` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug fix)
**Impact on plan:** Single-character change to grep flag; zero semantic impact on what is tested. The PCRE regex is semantically identical to the planned ERE regex, just using the correct engine for the syntax.

## Negative-Control Verification (D-14)

This section documents the Task 3 negative-control verification required by VALIDATION.md §Nyquist Dimensions #8.

**Step 1 — Pre-condition: test PASSES**

```
cd backend && uv run pytest tests/test_layering.py::test_no_hardcoded_ai_provider_branches -x -q
1 passed, 1 warning in 1.47s
```

**Step 2 — Inserted forbidden branch into `generate_sql()` in `sql_generator.py`**

Line ~338, just before `provider = await LLM_PROVIDER.get(db)`:
```python
# PHASE 226 D-14 NEGATIVE CONTROL — DO NOT COMMIT
if provider == "anthropic":  # type: ignore[name-defined]
    pass
```

**Step 3 — Architecture guard FAILS with offending line surfaced**

```
FAILED tests/test_layering.py::test_no_hardcoded_ai_provider_branches - Failed:
Phase 226 AIEXT-03 invariant violated: hardcoded AI provider dispatch
(`if provider == 'anthropic'/'openai_compatible'`) found in backend/app/processing/.
Replace with `get_ai_provider(name).complete(...)` from `app.platform.extensions`.
Offending lines:
backend/app/processing/ai/sql_generator.py:338:    if provider == "anthropic":  # type: ignore[name-defined]
```

The guard surfaces the exact file, line number, and content.

**Step 4 — Reverted change**

```
git checkout -- backend/app/processing/ai/sql_generator.py
```

**Step 5 — git status clean**

```
git diff --quiet backend/app/processing/ai/sql_generator.py && echo "CLEAN"
CLEAN
```

**Step 6 — Architecture guard PASSES again**

```
1 passed, 1 warning in 1.41s
```

Negative-control verification: **COMPLETE**. No commits from Task 3.

## Full-Suite Acceptance Gate (D-24)

| Check | Result |
|-------|--------|
| `pytest --collect-only -q \| tail -1` | 2073/2078 tests collected (5 deselected = perf) |
| `pytest -q --tb=short \| tail -5` | **2053 passed**, 19 skipped, 5 deselected, 1 error (pre-existing `test_saved_searches.py` asyncpg — unrelated to Plan 04) |
| `ruff check .` | All checks passed! |
| `alembic check` | N/A — Plan 04 modifies only test files; zero model changes confirmed by `git diff HEAD~2 HEAD --name-only` showing only `backend/tests/*.py` |
| SC#3 binding regex (migrated paths) | 0 matches — `git grep -nP "if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)" -- backend/app/processing/ :!streaming.py :!metadata_service.py :!tests/` exits 1 |
| Deferred-files regex | 4 matches — `metadata_service.py:255, 291` + `streaming.py:526, 541` |
| Architecture guard | `test_no_hardcoded_ai_provider_branches` PASSED |
| Entry-points seam tests | All 3 tests PASSED (test_ai_provider_extension.py) |
| All architecture tests | 11 passed (`-m architecture`) |

**D-24 gate: MET.** 2053 ≥ 2053 threshold.

## AIEXT Requirement Closure Table

| REQ-ID | Plan | Status |
|--------|------|--------|
| AIEXT-01 | Plan 01 | satisfied — AIProviderExtension Protocol at protocols.py with complete()/stream()/resolve_runtime_config() |
| AIEXT-02 | Plan 01 (defined) + Plan 04 (verified) | satisfied — test_default_providers_registered confirms accessor returns DefaultAnthropicProvider + DefaultOpenAICompatibleProvider |
| AIEXT-03 | Plan 02 (migrated) + Plan 04 (guarded) | satisfied — zero if/elif provider == branches in migrated paths; architecture guard enforces it |
| AIEXT-04 | Plan 04 (entry_points test) | satisfied — test_overlay_provider_is_dispatched proves SC#5 binding: overlay registered via entry_points dispatches correctly |
| AIEXT-05 | Plan 04 (architecture guard) | satisfied — test_no_hardcoded_ai_provider_branches in test_layering.py |

## Phase 226 SC Checklist

| SC | Description | Status |
|----|-------------|--------|
| SC#1 | AIProviderExtension Protocol exists at protocols.py with complete()/stream() | Plan 01 ✅ |
| SC#2 | DefaultAIProviderExtension resolves the two community providers via accessor | Plan 01 + Plan 04 verification ✅ |
| SC#3 | grep returns zero hits in migrated paths | Plan 02 + Plan 04 architecture guard ✅ |
| SC#4 | Existing AI integration tests pass unchanged with default extension wired in | Plan 02 Task 6 + Plan 04 full suite ✅ |
| SC#5 | Test overlay registered via entry_points dispatched correctly | Plan 04 test_overlay_provider_is_dispatched ✅ |

## Deferred-Scope Confirmation

`streaming.py` and `metadata_service.py` retain their if/elif branches (4 total). These are documented pathspec exclusions in `test_no_hardcoded_ai_provider_branches` and in `226-VALIDATION.md`:

- `streaming.py:526, 541` — true LLM-token streaming deferred to follow-up phase (RESEARCH.md Open Question 1); `stream()` Protocol method defaults raise `NotImplementedError`
- `metadata_service.py:255, 291` — structured-output APIs (Anthropic forced-tool-use; OpenAI `client.beta.chat.completions.parse`) don't map to the wide `complete()` Protocol shape; RESEARCH.md Open Question 2: a future phase adds `structured_complete(response_model, ...)` to the Protocol

## Known Stubs

None — this plan creates test infrastructure only. No stub data wiring needed.

## Threat Flags

None — test-only changes (no new network endpoints, auth paths, file access patterns, or schema changes).

## Next Phase Readiness

Phase 226 is complete. All 5 AIEXT requirements satisfied (AIEXT-01..05). All 5 SC criteria met.

Next: `/gsd-verify-work` followed by Phase 227 (saml-test-fixture-tmp-path) or Phase 229 (post-impl-audit-v13.4) close gate.

---
*Phase: 226-ai-provider-extension-protocol*
*Plan: 04*
*Completed: 2026-05-02*
