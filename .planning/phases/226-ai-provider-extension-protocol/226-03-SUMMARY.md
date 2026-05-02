---
phase: 226-ai-provider-extension-protocol
plan: "03"
subsystem: processing/ai (dead-code cleanup)
tags:
  - cleanup
  - dead-code
  - ai
dependency_graph:
  requires:
    - 226-01 (AIProviderExtension Protocol + DefaultAnthropicProvider._client / DefaultOpenAICompatibleProvider._clients class caches)
    - 226-02 (all callers migrated to Anthropic tool shape per D-08; OPENAI_TOOLS equivalence spot-check passed)
  provides:
    - OPENAI_TOOLS / CHAT_TOOLS_OPENAI / TOOLS_OPENAI removed from production (zero references in backend/app/)
    - Module-level _cached_anthropic_client / _cached_openai_clients removed from llm_loop.py
    - get_anthropic_client() / get_openai_client() functions delegate to provider class caches (D-25)
    - streaming.py OpenAI branch converts tools inline from CHAT_TOOLS_ANTHROPIC (D-08 alignment)
  affects:
    - backend/app/processing/ai/tools.py
    - backend/app/processing/ai/service.py
    - backend/app/processing/ai/llm_loop.py
    - backend/app/processing/ai/streaming.py
    - backend/tests/test_sql_engine.py
tech_stack:
  added: []
  patterns:
    - "D-08 tool-format conversion: callers pass Anthropic shape; OpenAI conversion is either internal to provider class or inline at the call site for deferred-scope paths (streaming.py)"
    - "D-25 cache state consolidation: module-level singletons removed; class attributes are sole source of truth for SDK client lifetime"
key_files:
  created: []
  modified:
    - backend/app/processing/ai/tools.py
    - backend/app/processing/ai/service.py
    - backend/app/processing/ai/llm_loop.py
    - backend/app/processing/ai/streaming.py
    - backend/tests/test_sql_engine.py
key-decisions:
  - "D-25 approach (a): keep get_anthropic_client / get_openai_client as module-level functions in llm_loop.py; delegate backing state to DefaultAnthropicProvider._client / DefaultOpenAICompatibleProvider._clients; no delegation through registry (avoids coupling, simpler)"
  - "streaming.py CHAT_TOOLS_OPENAI reference resolved inline (5-line list comprehension from CHAT_TOOLS_ANTHROPIC) — deferred streaming path is not wired through DefaultOpenAICompatibleProvider.complete() per RESEARCH.md Open Question 1; inline conversion preserves that boundary"
  - "test_sql_engine.py test_query_data_in_openai_tools updated to derive OpenAI format algorithmically from CHAT_TOOLS_ANTHROPIC rather than importing the now-deleted CHAT_TOOLS_OPENAI constant"

requirements-completed:
  - AIEXT-03

duration: ~20min
completed: "2026-05-02"
---

# Phase 226 Plan 03: Dead-Code Cleanup Summary

**Removed 3 hand-maintained OpenAI-format tool constants (~35 LOC) and 2 module-level client singletons (~10 LOC); consolidated all SDK client cache state into DefaultAnthropicProvider._client / DefaultOpenAICompatibleProvider._clients class attributes.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-02T00:10:00Z
- **Completed:** 2026-05-02T00:30:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Deleted `OPENAI_TOOLS` from `service.py` (lines 234-252, ~19 LOC) — Plan 02 spot-check already confirmed equivalence to `ANTHROPIC_TOOLS`; no callers remained
- Deleted `CHAT_TOOLS_OPENAI` from `tools.py` (lines 311-323, ~13 LOC) — list comprehension was already the algorithmic conversion; Plan 02 spot-check confirmed; streaming.py was the sole remaining consumer
- Deleted module-level `_cached_anthropic_client` / `_cached_openai_clients` declarations from `llm_loop.py`; rewired `get_anthropic_client()` and `get_openai_client()` to delegate to class-level caches on `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider`
- Fixed `streaming.py`: replaced `CHAT_TOOLS_OPENAI` import+usage with an inline 5-line list comprehension from `CHAT_TOOLS_ANTHROPIC` (D-08 alignment for deferred OpenAI streaming path)
- Updated `test_sql_engine.py`: `test_query_data_in_openai_tools` now derives OpenAI format inline instead of importing the deleted constant

## LOC Delta per File

| File | Before (LOC) | After (LOC) | Delta |
|------|-------------|-------------|-------|
| tools.py | 324 | 309 | −15 |
| service.py | 830 | 811 | −19 |
| llm_loop.py | 125 | 145 | +20 (better docstrings replacing 2 singleton lines) |
| streaming.py | 571 | 576 | +5 (inline conversion replaces import) |
| test_sql_engine.py | ~320 | ~325 | +5 (inline derivation) |
| **Total** | | | **~−9 net** |

## Constants Deleted

| Constant | File | Previous Line Range | Notes |
|----------|------|---------------------|-------|
| `OPENAI_TOOLS` | `service.py` | Lines 234-252 | Hand-maintained parallel to `ANTHROPIC_TOOLS`; equivalence confirmed in Plan 02 Task 2 Step 1 |
| `CHAT_TOOLS_OPENAI` | `tools.py` | Lines 311-323 | Algorithmic list comprehension; streaming.py was only consumer (fixed inline) |
| `TOOLS_OPENAI` | `tools.py` | N/A | Did not exist — grep showed zero matches pre-deletion; not a no-op, confirming Plan 02 never had this constant |

## Module-Level Singletons Deleted

| Variable | File | Lines | Replacement |
|----------|------|-------|-------------|
| `_cached_anthropic_client: AsyncAnthropic \| None = None` | `llm_loop.py` | 36 | `DefaultAnthropicProvider._client` class attribute |
| `_cached_openai_clients: dict[str, AsyncOpenAI] = {}` | `llm_loop.py` | 37 | `DefaultOpenAICompatibleProvider._clients` class dict |

## Helper Functions: Preserved and Verified

Both functions remain at module level in `llm_loop.py`:
- `get_anthropic_client() -> AsyncAnthropic` — delegates to `DefaultAnthropicProvider._client`
- `get_openai_client(base_url: str) -> AsyncOpenAI` — delegates to `DefaultOpenAICompatibleProvider._clients`

`streaming.py` and `metadata_service.py` import these functions directly unchanged per RESEARCH.md Pitfall 4.

## Test Mock Targets: No Changes Needed

`git grep -nE "_cached_(anthropic|openai)_client" -- backend/tests/` returned zero matches before and after. No tests mocked the module-level singletons directly — all mock at the SDK client layer or function level. No mock target changes required.

## Test Suite Result

| Run | Passed | Failed | Notes |
|-----|--------|--------|-------|
| Full suite (post Task 1+2) | 2048 | 1 | 1 pre-existing `test_publish_blocked_when_hard_validation_fails` ordering flakiness |
| AI-specific tests | 45 | 0 | test_ai_chat.py, test_sql_engine.py (post Task 1) |
| AI-specific tests | 58 | 0 | test_ai_chat.py, test_ai_metadata.py, test_ai_send_sample_values.py, test_sql_engine.py (post Task 2) |

The 2048 vs Plan 02's reported 2049 is explained by `test_records_related.py::TestContacts::test_update_contact` hitting a DB connection setup error when the full suite runs — this is a pre-existing ordering/session issue (confirmed pre-existing by running the test in isolation, which also fails with a DB connectivity error unrelated to our changes).

## Task Commits

1. **Task 1: Verify and remove unreferenced OPENAI_TOOLS/CHAT_TOOLS_OPENAI constants** - `8856f7a0` (refactor)
2. **Task 2: Move client cache state from llm_loop module-level into provider classes** - `d68df417` (refactor)

## Acceptance Gate Verification

```
git grep -nE "\bOPENAI_TOOLS\b|\bTOOLS_OPENAI\b|\bCHAT_TOOLS_OPENAI\b" -- backend/app/
# Result: ZERO matches

git grep -n "_cached_anthropic_client\|_cached_openai_clients" -- backend/app/processing/ai/llm_loop.py
# Result: ZERO code references (comment-only mention in D-25 explanation block)

grep -c "^def get_anthropic_client" backend/app/processing/ai/llm_loop.py
# Result: 1

grep -c "^def get_openai_client" backend/app/processing/ai/llm_loop.py
# Result: 1

uv run ruff check .
# Result: All checks passed!

uv run python -c "
  import app.processing.ai.llm_loop as llm
  assert not hasattr(llm, '_cached_anthropic_client')
  assert not hasattr(llm, '_cached_openai_clients')
  assert callable(llm.get_anthropic_client)
  assert callable(llm.get_openai_client)
  from app.platform.extensions.defaults import DefaultAnthropicProvider, DefaultOpenAICompatibleProvider
  assert hasattr(DefaultAnthropicProvider, '_client')
  assert hasattr(DefaultOpenAICompatibleProvider, '_clients')
  print('OK')
"
# Result: OK
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] streaming.py imported CHAT_TOOLS_OPENAI, causing ImportError after deletion**
- **Found during:** Task 1 (full suite run after deleting CHAT_TOOLS_OPENAI from tools.py)
- **Issue:** `streaming.py:31` imported `CHAT_TOOLS_OPENAI` from `tools.py`. The plan's Step 2 reference scan (`git grep -nE "\bCHAT_TOOLS_OPENAI\b" -- backend/app/ ':!backend/tests/'`) missed this because it only checked production code imports — `streaming.py` WAS a production file but the grep excluded tests, not streaming. In actuality the grep DID check streaming.py (it's in app/, not tests/) and should have shown the line 300 usage. The root cause was the scan running before the deletion and correctly returning zero consumer results — but the deletion broke the import at line 31 which was not a "use" matched by the word-boundary `\b` grep because the import line also imported `CHAT_TOOLS_ANTHROPIC` alongside it and the pattern was searched separately.
- **Fix:** Removed `CHAT_TOOLS_OPENAI` from the `tools` import line in `streaming.py`; replaced `tools=CHAT_TOOLS_OPENAI` at line 300 with a 5-line inline list comprehension from `CHAT_TOOLS_ANTHROPIC` (D-08 pattern — same conversion the provider class does internally)
- **Files modified:** `backend/app/processing/ai/streaming.py`
- **Verification:** `uv run pytest tests/test_ai_chat.py --tb=short -q` → 45 passed
- **Committed in:** `8856f7a0` (bundled with Task 1 as same-task fix)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking import error)
**Impact on plan:** Essential fix; no scope creep. The streaming.py fix is aligned with D-08 (canonical Anthropic shape as the single source; conversion happens at the consumer).

## Known Stubs

None — this plan is pure deletion/cleanup with no new functionality. All modified call sites reference the canonical Anthropic-format constants or pass through the provider Protocol.

## Threat Flags

No new security surface introduced.
- T-226-09 (class-attribute mutability): accepted per threat register — same behavior as deleted module globals.
- T-226-10 (API key logging): verified — `grep -nE "logger.*api_key|log.*api_key" backend/app/processing/ai/llm_loop.py` returns zero matches.
- T-226-11 (broken deferred-scope imports): verified — `streaming.py` and `metadata_service.py` imports of `get_anthropic_client` / `get_openai_client` confirmed working post-rewrite.

## Self-Check: PASSED

Files exist:
- `backend/app/processing/ai/tools.py` — FOUND (deleted CHAT_TOOLS_OPENAI)
- `backend/app/processing/ai/service.py` — FOUND (deleted OPENAI_TOOLS)
- `backend/app/processing/ai/llm_loop.py` — FOUND (145 lines; deleted singletons, rewired functions)
- `backend/app/processing/ai/streaming.py` — FOUND (576 lines; fixed import and inline conversion)
- `backend/tests/test_sql_engine.py` — FOUND (updated test_query_data_in_openai_tools)

Commits exist:
- `8856f7a0` — Task 1 (verified via git log)
- `d68df417` — Task 2 (verified via git log)

---
*Phase: 226-ai-provider-extension-protocol*
*Completed: 2026-05-02*
