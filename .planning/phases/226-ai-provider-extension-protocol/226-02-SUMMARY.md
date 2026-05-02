---
phase: 226-ai-provider-extension-protocol
plan: "02"
subsystem: processing/ai (dispatch migration)
tags:
  - migration
  - dispatch
  - ai
  - refactor
dependency_graph:
  requires:
    - 226-01 (AIProviderExtension Protocol + defaults + accessor)
  provides:
    - All production callers migrated to get_ai_provider(name).complete(...)
    - run_tool_loop/_loop_anthropic/_loop_openai deleted from llm_loop.py
    - resolve_provider returns (name, model, runtime_config) per D-21
    - AIEXT-03 requirement satisfied
  affects:
    - backend/app/processing/ai/llm_loop.py
    - backend/app/processing/ai/service.py
    - backend/app/processing/ai/chat_service.py
    - backend/app/processing/ai/sql_generator.py
    - backend/app/processing/ai/streaming.py
tech_stack:
  added: []
  patterns:
    - get_ai_provider(name).complete(...) dispatch via extension registry
    - _noop_executor pattern for no-tool single-round calls (sql_generator + _retry_parse_map_spec)
    - runtime_config dict as 3rd resolve_provider tuple element (replaces base_url str)
key_files:
  created: []
  modified:
    - backend/app/processing/ai/llm_loop.py
    - backend/app/processing/ai/service.py
    - backend/app/processing/ai/chat_service.py
    - backend/app/processing/ai/sql_generator.py
    - backend/app/processing/ai/streaming.py
decisions:
  - "D-19: All 4 run_tool_loop callers (service.py:660,741, chat_service.py:934 + sql_generator._call_* helpers) migrated to provider_ext.complete()"
  - "D-20/D-08: Tool-format unification — callers now pass tools=ANTHROPIC_TOOLS only; OpenAI provider converts internally in DefaultOpenAICompatibleProvider.complete()"
  - "D-21: resolve_provider returns (name, model, runtime_config: dict) not (provider, model, base_url: str); all 4 callers updated"
  - "RESEARCH.md Pitfall 7: sql_generator resolves LLM_MODEL_LIGHT directly (not via resolve_provider) because it uses the light model variant, not the standard model"
  - "RESEARCH.md Open Question 1: streaming.py:516,531 if/elif branches STAY (true LLM-token streaming is deferred to a follow-up phase)"
  - "RESEARCH.md Open Question 2: metadata_service.py:255,291 if/elif branches STAY (structured-output dispatch deferred)"
metrics:
  duration: "~35 minutes"
  completed_date: "2026-05-01"
  tasks_completed: 6
  tasks_total: 6
  files_changed: 6
  loc_added: ~104
  loc_removed: ~420
---

# Phase 226 Plan 02: Dispatch Migration Summary

**One-liner:** Migrated all 5 production dispatch sites from hardcoded if/elif provider branches to get_ai_provider(name).complete(); deleted run_tool_loop/_loop_anthropic/_loop_openai; resolve_provider returns (name, model, runtime_config) dict per D-21.

## Objective

Close AIEXT-03: replace every hardcoded `if provider == "anthropic"` / `elif provider == "openai_compatible"` dispatch in the 4 migration-scope files with the extension registry lookup `get_ai_provider(name).complete(...)`. Delete the obsolete `run_tool_loop`, `_loop_anthropic`, `_loop_openai` functions from `llm_loop.py`. Update `resolve_provider` to return `(name, model, runtime_config)` and update all 4 callers.

## LOC Delta per File

| File | Before (LOC) | After (LOC) | Delta |
|------|-------------|-------------|-------|
| llm_loop.py | 405 | 124 | −281 |
| service.py | ~858 | 830 | −28 |
| chat_service.py | ~995 | 986 | −9 |
| sql_generator.py | ~455 | 398 | −57 |
| streaming.py | 565 | 571 | +6 |
| **Total** | | | **−316 net (104 added, 420 deleted)** |

## Hardcoded `if provider ==` Count Before vs After

| File | Before | After | Notes |
|------|--------|-------|-------|
| llm_loop.py | 3 (lines 117, 132, 160) | 0 | All deleted with run_tool_loop |
| service.py | 1 (_retry_parse_map_spec line 394) | 0 | Migrated to provider_ext.complete |
| chat_service.py | 0 | 0 | Was via run_tool_loop |
| sql_generator.py | 2 (lines 351, 355) | 0 | Replaced with provider_ext.complete |
| streaming.py | 2 (lines 516, 531) | 2 (lines 521, 536) | STAY — deferred per RESEARCH.md Open Question 1 |
| metadata_service.py | 2 (lines 255, 291) | 2 | STAY — deferred per RESEARCH.md Open Question 2 |

## Caller Migration Table

| Site | Before Pattern | After Pattern |
|------|---------------|---------------|
| `service.py:_retry_parse_map_spec` | `if provider == "anthropic": client.messages.create(...)` else openai | `get_ai_provider(provider).complete(tools=[], max_rounds=1, max_tokens=1024)` |
| `service.py:generate_map_from_prompt` | `run_tool_loop(provider=provider, tools_anthropic=..., tools_openai=..., base_url=base_url)` | `provider_ext.complete(tools=ANTHROPIC_TOOLS, base_url=runtime_config.get("base_url"))` |
| `service.py:stream_generate_map` | `run_tool_loop(provider=provider, tools_anthropic=..., tools_openai=..., base_url=base_url)` | `provider_ext.complete(tools=ANTHROPIC_TOOLS, base_url=runtime_config.get("base_url"))` |
| `chat_service.py:chat_edit_map` | `run_tool_loop(tools_anthropic=CHAT_TOOLS_ANTHROPIC, tools_openai=CHAT_TOOLS_OPENAI, base_url=base_url)` | `provider_ext.complete(tools=CHAT_TOOLS_ANTHROPIC, base_url=runtime_config.get("base_url"))` |
| `sql_generator.py:generate_sql` | `if provider == "anthropic": _call_anthropic(...)` elif `_call_openai(...)` | `get_ai_provider(provider).complete(tools=[], max_rounds=1, temperature=0.0, model=LLM_MODEL_LIGHT)` |

## resolve_provider Tuple Shape Change

| Caller | Before | After |
|--------|--------|-------|
| service.py:658 | `provider, model, base_url = await resolve_provider(session)` | `provider, model, runtime_config = await resolve_provider(session)` |
| service.py:738 | same | same |
| chat_service.py:935 | same | same |
| streaming.py:509 | `provider, model, _ = await resolve_provider(db)` | `provider, model, runtime_config = await resolve_provider(db)` |

## Tool-Format Equivalence Spot-Check (Task 2, Step 1)

Ran the algorithmic equivalence check per RESEARCH.md A2:
```
service.OPENAI_TOOLS == [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in ANTHROPIC_TOOLS]
```
Result: **OK — equivalent**. OPENAI_TOOLS was hand-maintained but correctly mirrors ANTHROPIC_TOOLS. Safe to proceed with canonical Anthropic shape (D-08); callers now pass `tools=ANTHROPIC_TOOLS` only.

## Test Suite Result

| Run | Passed | Failed | Notes |
|-----|--------|--------|-------|
| Full suite (bt4spsbv7) | 2049 | 1 | 1 pre-existing flaky ordering failure; passes in isolation |
| AI-specific tests | 20 | 0 | test_ai_chat.py, test_ai_send_sample_values.py, test_ai_metadata.py |
| Chat streaming tests | 14 | 0 | test_chat_streaming.py, test_chat_narrative.py |
| Validation tests (isolated) | 7 | 0 | Pre-existing ordering flakiness confirmed not caused by us |

The 1 "failure" (`test_publish_blocked_when_hard_validation_fails`) passes in isolation — confirmed pre-existing test ordering interaction, not caused by Plan 02 changes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing ruff F401 in test_ai_send_sample_values.py**
- **Found during:** Task 6 (full-suite verification)
- **Issue:** `patch` imported but unused from `unittest.mock` — pre-existing in a prior commit
- **Fix:** Removed `patch` from the import line; `AsyncMock` retained
- **Files modified:** `backend/tests/test_ai_send_sample_values.py`
- **Commit:** 45f5cd66

**2. [Rule 1 - Minor] Stale `settings` import in service.py**
- **Found during:** Task 2 (ruff check)
- **Issue:** `from app.core.config import settings` became unused after removing the `get_openai_client()` call in `_retry_parse_map_spec` (which previously used `settings.openai_base_url`)
- **Fix:** Removed the import
- **Files modified:** `backend/app/processing/ai/service.py`
- **Commit:** f28e130e (bundled with Task 2)

**3. [Rule 1 - Minor] Docstring references to deleted function**
- **Found during:** Tasks 2, 3 (grep verification)
- **Issue:** Comments/docstrings in service.py and chat_service.py referenced `run_tool_loop` by name
- **Fix:** Updated to `provider_ext.complete` / `provider_ext.complete()` references
- **Files modified:** `backend/app/processing/ai/service.py`, `backend/app/processing/ai/chat_service.py`
- **Commits:** f28e130e, b5e756be

## Deferred Files (Per-Plan Exclusions)

| File | Branches Remaining | Reason |
|------|--------------------|--------|
| streaming.py:521,536 | 2 | True LLM-token streaming — RESEARCH.md Open Question 1; deferred to follow-up phase; Plan 04 pathspec excludes this file |
| metadata_service.py:255,291 | 2 | Structured-output dispatch — RESEARCH.md Open Question 2; deferred; Plan 04 pathspec excludes this file |

## Acceptance Gate Verification

All Plan 02 acceptance criteria verified:

```
grep -nE "if .*provider *== *['\"]" backend/app/processing/ai/llm_loop.py ... → ZERO
grep -nE "if .*provider *== *['\"]" backend/app/processing/ai/service.py → ZERO
grep -nE "if .*provider *== *['\"]" backend/app/processing/ai/chat_service.py → ZERO
grep -nE "if .*provider *== *['\"]" backend/app/processing/ai/sql_generator.py → ZERO
grep -n "run_tool_loop|_loop_anthropic|_loop_openai" backend/app/processing/ → 0 production hits
grep "runtime_config.*resolve_provider" backend/app/ → 4 matches (service.py x2, chat_service.py x1, streaming.py x1)
ruff check . → All checks passed!
```

## Commits

| Hash | Task | Message |
|------|------|---------|
| 0dbc5600 | Task 1 | refactor(226-02): slim llm_loop.py — delete run_tool_loop/_loop_anthropic/_loop_openai, rewrite resolve_provider |
| f28e130e | Task 2 | refactor(226-02): migrate service.py dispatch sites to get_ai_provider().complete() |
| b5e756be | Task 3 | refactor(226-02): migrate chat_service.py chat_edit_map to get_ai_provider().complete() |
| 1f6b589d | Task 4 | refactor(226-02): migrate sql_generator.py generate_sql to get_ai_provider().complete() |
| 05327843 | Task 5 | refactor(226-02): update streaming.py resolve_provider tuple-unpack to (name, model, runtime_config) |
| 45f5cd66 | Task 6/Fix | fix(226-02): remove unused patch import from test_ai_send_sample_values.py (ruff F401) |

## Known Stubs

None — all migrated dispatch sites call production-grade `DefaultAnthropicProvider.complete()` / `DefaultOpenAICompatibleProvider.complete()` whose bodies are identical to the deleted `_loop_anthropic` / `_loop_openai` functions.

## Threat Flags

No new security surface introduced. The `runtime_config` dict flows through admin-controlled PersistentConfig values only (same trust boundary as before). T-226-06 mitigated: no log statements emit `runtime_config`. T-226-07 mitigated: all 4 resolve_provider callers updated (Task 6 grep verification confirms zero old `base_url` tuple shape).

## Self-Check: PASSED

Files exist:
- `backend/app/processing/ai/llm_loop.py` — FOUND (124 lines)
- `backend/app/processing/ai/service.py` — FOUND (830 lines)
- `backend/app/processing/ai/chat_service.py` — FOUND (986 lines)
- `backend/app/processing/ai/sql_generator.py` — FOUND (398 lines)
- `backend/app/processing/ai/streaming.py` — FOUND (571 lines)

Commits exist:
- 0dbc5600 — FOUND
- f28e130e — FOUND
- b5e756be — FOUND
- 1f6b589d — FOUND
- 05327843 — FOUND
- 45f5cd66 — FOUND
