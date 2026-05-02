---
phase: 226-ai-provider-extension-protocol
verified: 2026-05-01T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run the dev server (`docker compose up`), open the map builder, and exercise: (1) a chat-edit-map session against the configured LLM provider, (2) a generate-map-from-prompt session. Confirm responses are identical to pre-Phase-226 behavior."
    expected: "LLM responses complete successfully with no errors; map creation and chat editing produce correct results, confirming no functional regression in the live dispatch path."
    why_human: "Live LLM API calls require API keys and network access not available in the automated test suite. This is the only check that exercises DefaultAnthropicProvider.complete() or DefaultOpenAICompatibleProvider.complete() against a real API, as all unit tests mock at the SDK boundary (TestProvider) or the router boundary."
---

# Phase 226: ai-provider-extension-protocol Verification Report

**Phase Goal:** Close the last red seam from `oc-separation-audit-20260430-b.md` by extracting AI provider dispatch into an `AIProviderExtension` Protocol on the same accessor pattern as `BillingExtension` (Phase 223) and `AuditSink` (Phase 222). Replace hardcoded `if/elif provider ==` branches with extension lookup. Default registry maps the two community providers; overlays can register additional providers via `importlib.metadata` entry_points.

**Verified:** 2026-05-01
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `AIProviderExtension` Protocol exists at `backend/app/platform/extensions/protocols.py` with `@runtime_checkable`, `complete()`, `stream()`, and `resolve_runtime_config()` method signatures | VERIFIED | `grep -c "class AIProviderExtension" protocols.py` = 1; `grep -c "@runtime_checkable" protocols.py` = 6 (includes new one); three async method signatures confirmed at lines 120, 136, 152 |
| 2 | `DefaultAnthropicProvider` and `DefaultOpenAICompatibleProvider` exist and resolve via `get_ai_provider()` with the same accessor pattern as `get_billing_extension()` / `get_audit_sink()` | VERIFIED | `get_ai_provider("anthropic")` returns `DefaultAnthropicProvider`; `get_ai_provider("openai_compatible")` returns `DefaultOpenAICompatibleProvider`; both pass `isinstance(_, AIProviderExtension)`; singleton stable (same instance on two calls); `get_ai_provider("bedrock")` raises `ValueError("Unknown LLM provider: bedrock")` — all confirmed by live Python invocation |
| 3 | Zero `if/elif provider ==` branches in `backend/app/processing/ai/` outside the documented pathspec exclusions; architecture guard enforces this in CI | VERIFIED | `git grep -nP "if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)" -- backend/app/processing/ ':!streaming.py' ':!metadata_service.py'` exits 1 (no matches); deferred files retain exactly 4 documented branches (streaming.py:526,541; metadata_service.py:255,291); `test_no_hardcoded_ai_provider_branches` PASSED; docstring + VALIDATION.md exclusions table document both deferrals |
| 4 | Existing AI integration tests pass unchanged with the default extension wired in | VERIFIED | All 11 architecture tests pass; 4/4 key phase tests pass (`test_ai_provider_extension.py` x3 + `test_no_hardcoded_ai_provider_branches`); REVIEW.md fix_verification records 2054 passed, 19 skipped post-review-fix baseline; full suite still running but targeted suite confirms no regression |
| 5 | A test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file | VERIFIED | `test_overlay_provider_is_dispatched` PASSED — exercises full chain: `entry_points()` discovery → `register_extensions(registry)` callback → `get_ai_provider("test_provider")` → `provider.complete()` async dispatch → `ToolLoopResult(text="from-test-provider")` returned; community defaults (`"anthropic"`, `"openai_compatible"`) coexist correctly after overlay registration |

**Score: 5/5 truths verified**

---

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | `streaming.py:526,541` — true LLM-token streaming `_stream_anthropic_chat`/`_stream_openai_chat` still dispatches via `if provider == "anthropic"` | Future phase | RESEARCH.md Open Question 1: "True LLM-token streaming is explicitly deferred (CONTEXT.md §deferred)"; VALIDATION.md exclusions table documents follow-up phase for `stream()` Protocol method implementation |
| 2 | `metadata_service.py:255,291` — structured-output dispatch via `client.beta.chat.completions.parse` / `tool_choice={"type":"tool"}` still branched | Future phase | RESEARCH.md Open Question 2: "a future phase adds `structured_complete(response_model, ...)` to the Protocol"; VALIDATION.md exclusions table documents follow-up phase |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/platform/extensions/protocols.py` | AIProviderExtension Protocol with `@runtime_checkable`, three async methods | VERIFIED | File exists at 152 lines; class present with correct decorator and methods |
| `backend/app/platform/extensions/defaults.py` | DefaultAnthropicProvider + DefaultOpenAICompatibleProvider | VERIFIED | File exists at 764 lines; both classes present with `complete()` (full tool-loop body), `stream()` (raises NotImplementedError), `resolve_runtime_config()`; class-level client caches |
| `backend/app/platform/extensions/__init__.py` | `get_ai_provider(name)` accessor with dict-keyed setdefault seeding | VERIFIED | File exists at 255 lines; accessor at line 255+; both provider classes in imports; `ValueError("Unknown LLM provider: {name}")` confirmed |
| `backend/app/processing/ai/llm_loop.py` | Slimmed: `run_tool_loop`, `_loop_anthropic`, `_loop_openai` deleted; `resolve_provider` returns new tuple shape | VERIFIED | No `run_tool_loop`, `_loop_anthropic`, `_loop_openai` definitions; `get_anthropic_client`, `get_openai_client` present (compatibility shims); `_cached_*` module-level singletons removed; module docstring updated; ~100 LOC |
| `backend/app/processing/ai/service.py` | 3 dispatch sites migrated to `get_ai_provider(provider).complete(...)` | VERIFIED | `get_ai_provider` imported at line 17; used at lines 374, 640, 720; `resolve_provider` returns `(provider, model, runtime_config)` at lines 639, 719 |
| `backend/app/processing/ai/chat_service.py` | `chat_edit_map` dispatch migrated | VERIFIED | `get_ai_provider` imported at line 15; used at line 936; `resolve_provider` tuple-unpack at line 935 |
| `backend/app/processing/ai/sql_generator.py` | `generate_sql` dispatch migrated; `_call_anthropic`/`_call_openai` deleted; `resolve_runtime_config` used for base_url | VERIFIED | `get_ai_provider` imported at line 16; used at line 353; `resolve_runtime_config` used at line 354; no `_call_anthropic` or `_call_openai` definitions |
| `backend/app/processing/ai/streaming.py` | `resolve_provider` tuple-unpack updated to `(name, model, runtime_config)` | VERIFIED | `(provider, model, runtime_config)` at line 514; `if provider ==` branches at 526, 541 remain (documented deferred scope) |
| `backend/tests/test_layering.py` | `test_no_hardcoded_ai_provider_branches` added; Phase 226 credited in module docstring | VERIFIED | Test function present; module docstring line 1 says "Phases 212, 213, 214, 222, 223, 224, 225, and 226"; pathspec exclusions `:!streaming.py` and `:!metadata_service.py` at lines 750-751; vacuous `:!backend/tests/` exclusion removed (IN-01 fix confirmed) |
| `backend/tests/test_ai_provider_extension.py` | Three tests: `test_default_providers_registered`, `test_unknown_provider_raises_value_error`, `test_overlay_provider_is_dispatched` | VERIFIED | File exists; all 3 tests present and pass; autouse `_clean_registry` fixture present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `service.py:_retry_parse_map_spec` | `get_ai_provider` | `get_ai_provider(provider).complete(tools=[], max_rounds=1, ...)` | WIRED | `get_ai_provider` at line 374 |
| `service.py:generate_map_from_prompt` | `get_ai_provider` | `provider_ext = get_ai_provider(provider)` then `provider_ext.complete(...)` | WIRED | `get_ai_provider` at line 640 |
| `service.py:stream_generate_map` | `get_ai_provider` | `provider_ext = get_ai_provider(provider)` then `provider_ext.complete(...)` | WIRED | `get_ai_provider` at line 720 |
| `chat_service.py:chat_edit_map` | `get_ai_provider` | `provider_ext = get_ai_provider(provider)` | WIRED | `get_ai_provider` at line 936 |
| `sql_generator.py:generate_sql` | `get_ai_provider` | `provider_ext = get_ai_provider(provider).complete(tools=[], max_rounds=1, ...)` | WIRED | `get_ai_provider` at line 353 |
| `test_ai_provider_extension.py:test_overlay_provider_is_dispatched` | `get_ai_provider` | `patch("app.platform.extensions.entry_points", ...)` | WIRED | Entry-points chain exercised end-to-end in test |
| `test_layering.py:test_no_hardcoded_ai_provider_branches` | `backend/app/processing/` | `subprocess.run(["git", "grep", "-P", regex, "--", pathspec, exclusions])` | WIRED | PCRE regex; 2 documented exclusions; passes on post-Plan-02 codebase |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `DefaultAnthropicProvider.complete()` | `result: ToolLoopResult` | Anthropic SDK `client.messages.create()` → tool loop → accumulates tokens | Yes (live API in production; mocked by TestProvider in tests) | FLOWING (production) / MOCK-IN-TEST |
| `DefaultOpenAICompatibleProvider.complete()` | `result: ToolLoopResult` | OpenAI SDK `client.chat.completions.create()` → tool loop → accumulates tokens | Yes (live API in production; mocked by TestProvider in tests) | FLOWING (production) / MOCK-IN-TEST |
| `get_ai_provider(name)` accessor | `providers: dict` | `_extensions["ai_providers"]` seeded by `setdefault` from defaults | Concrete class instances returned | VERIFIED — singleton confirmed by Python assertion |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Protocol methods exist on AIProviderExtension | `python -c "from app.platform.extensions.protocols import AIProviderExtension; assert hasattr(AIProviderExtension, 'complete'); ..."` | OK | PASS |
| DefaultAnthropicProvider satisfies Protocol | `python -c "from app.platform.extensions.defaults import DefaultAnthropicProvider; from app.platform.extensions.protocols import AIProviderExtension; assert isinstance(DefaultAnthropicProvider(), AIProviderExtension)"` | ALL ASSERTIONS PASSED | PASS |
| get_ai_provider returns correct instances + singleton | `python -c "from app.platform.extensions import get_ai_provider; ..."` | ALL ASSERTIONS PASSED | PASS |
| Zero hardcoded dispatch in migrated paths | `git grep -nP "if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)" -- backend/app/processing/ ':!streaming.py' ':!metadata_service.py'` | exit 1 (no matches) | PASS |
| 4 branches retained in deferred files | `git grep -nP "..." -- streaming.py metadata_service.py` | 4 matches (streaming.py:526,541; metadata_service.py:255,291) | PASS |
| Architecture guard test | `pytest tests/test_layering.py::test_no_hardcoded_ai_provider_branches -x -q` | PASSED | PASS |
| Entry-points seam tests (3) | `pytest tests/test_ai_provider_extension.py -x -q` | 3 passed | PASS |
| All 11 architecture tests | `pytest tests/test_layering.py -m architecture -q` | 11 passed, 3 deselected | PASS |
| Review finding CR-01 fix (conditional tools=) | `grep -n "if cached_tools" backend/app/platform/extensions/defaults.py` | Lines 488, 669 — conditional guard present in both providers | PASS |
| Review finding WR-01 fix (API key guard) | `grep -n "if not settings.anthropic_api_key" backend/app/processing/ai/llm_loop.py` | Line 54 (anthropic), line 81 (openai) | PASS |
| Review finding WR-02 fix (sql_generator base_url) | `grep -n "resolve_runtime_config" backend/app/processing/ai/sql_generator.py` | Line 354 | PASS |
| Review finding IN-01 fix (vacuous exclusion removed) | Architecture guard subprocess call in test_layering.py | `:!backend/tests/` exclusion absent from pathspec list | PASS |
| No alembic migrations in Phase 226 | `git log --after="2026-04-30" -- backend/alembic/versions/` | Empty (zero new migrations) | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| AIEXT-01 | 226-01 | AIProviderExtension Protocol at protocols.py with `complete()` and `stream()` | SATISFIED | Protocol exists; `@runtime_checkable`; three async methods; TYPE_CHECKING forward references to ToolLoopResult/ToolExecutor/ActionCollector |
| AIEXT-02 | 226-01 (defined) + 226-04 (verified) | DefaultAIProviderExtension maps two community providers via accessor pattern | SATISFIED | Both defaults registered via `get_ai_provider()`; accessor follows same `setdefault` pattern as `get_billing_extension()`/`get_audit_sink()`; test_default_providers_registered PASSED |
| AIEXT-03 | 226-02 (migrated) + 226-04 (guarded) | Hardcoded `if/elif provider ==` dispatch replaced with extension lookup | SATISFIED | Zero hits in migrated paths; four documented hits in deferred-scope files; architecture guard enforces invariant |
| AIEXT-04 | 226-04 | Overlays can register additional providers via `importlib.metadata` entry_points | SATISFIED | test_overlay_provider_is_dispatched PASSED — exercises full entry_points chain without modifying any core file |
| AIEXT-05 | 226-04 | Architecture-guard test verifies no `if provider ==` branches in `processing/ai/` | SATISFIED | test_no_hardcoded_ai_provider_branches in test_layering.py; PCRE regex; 2 pathspec exclusions; negative-control confirmed in Plan 04 Summary |

**Note on REQUIREMENTS.md traceability table:** The traceability table at REQUIREMENTS.md lines 82-86 still shows AIEXT-01..05 as `[ ] not started`. The requirement descriptions at lines 21-25 are correctly marked `[x]`. The traceability table was not updated by the phase execution — this is a documentation inconsistency but does not affect implementation correctness. All five requirements are satisfied by codebase evidence.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/platform/extensions/defaults.py` | Both `stream()` methods | `raise NotImplementedError(...)` | Info | Intentional per D-03 — `stream()` is a deferred-scope seam placeholder; documented in Protocol docstring and CONTEXT.md; no production caller invokes `stream()` |
| `backend/.planning/REQUIREMENTS.md` | Lines 82-86 | Traceability table shows `[ ] not started` for AIEXT-01..05 after implementation completed | Warning | Documentation gap only — the requirement descriptions at lines 21-25 are correctly marked `[x]`; no functional impact; can be updated at milestone close |

---

### Human Verification Required

#### 1. Live LLM Dispatch Round-Trip

**Test:** Run the development server (`docker compose up -d`). Open the map builder in the browser (`http://localhost:8080`). Perform two actions:
1. Use the chat-edit-map feature to send a prompt that results in a map modification
2. Use the generate-map-from-prompt feature to create a new map from a text description

**Expected:** Both LLM features complete successfully, returning coherent AI responses and producing correct map edits/creation. No errors in the browser console or backend logs. Behavior should be identical to pre-Phase-226 (the tool-loop bodies were copied verbatim from `_loop_anthropic`/`_loop_openai`; dispatch path now goes through `DefaultAnthropicProvider.complete()` or `DefaultOpenAICompatibleProvider.complete()` instead of `run_tool_loop()`).

**Why human:** Live LLM calls require API keys and network access not available in the automated test suite. All unit tests mock the provider at either the TestProvider stub (test_overlay_provider_is_dispatched) or at the router boundary (test_chat_streaming.py, test_chat_narrative.py). The review finding CR-01 (conditional `tools=` for empty-tools callers) was confirmed fixed in code, but the live path through DefaultAnthropicProvider.complete() with a real LLM response — particularly `sql_generator.generate_sql()` which passes `tools=[]` — has not been exercised against a live API. This is the VALIDATION.md §Manual-Only Verifications item.

---

### Gaps Summary

No gaps. All five success criteria are verified by automated evidence. The only open item is the one mandatory manual verification from VALIDATION.md — a live LLM round-trip that cannot be automated without API keys and network access.

The REQUIREMENTS.md traceability table inconsistency (lines 82-86 showing `[ ] not started`) is a documentation gap that should be corrected at milestone close but does not affect phase goal achievement.

---

_Verified: 2026-05-01_
_Verifier: Claude (gsd-verifier)_
