---
phase: 226-ai-provider-extension-protocol
plan: "01"
subsystem: platform/extensions + processing/ai
tags:
  - protocol
  - extension
  - ai
  - additive
dependency_graph:
  requires: []
  provides:
    - AIProviderExtension Protocol (protocols.py)
    - DefaultAnthropicProvider (defaults.py)
    - DefaultOpenAICompatibleProvider (defaults.py)
    - get_ai_provider(name) accessor (__init__.py)
  affects:
    - backend/app/platform/extensions/protocols.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/platform/extensions/__init__.py
tech_stack:
  added: []
  patterns:
    - runtime_checkable Protocol (mirrors AuditSink/BillingExtension)
    - deferred-import discipline inside complete() method bodies (mirrors DefaultAuditSink.emit)
    - dict-keyed extension registry slot (new shape; differs from list-shape and single-slot)
    - per-key setdefault seeding (order-safe overlay registration)
    - class-level SDK client caches (survives test registry resets)
key_files:
  created: []
  modified:
    - backend/app/platform/extensions/protocols.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/platform/extensions/__init__.py
decisions:
  - "D-04/D-05: dict-keyed registry slot chosen over list or single-slot because AI dispatch fans out by name at request time — LLM_PROVIDER stores 'anthropic'/'openai_compatible' and accessor returns matching provider. O(1) lookup."
  - "D-07: @runtime_checkable on AIProviderExtension to allow isinstance checks for overlay debugging (mirrors AuditSink/BillingExtension/IdentityProtocol)"
  - "D-08: canonical tool format is Anthropic-shape; DefaultOpenAICompatibleProvider converts to OpenAI function format internally"
  - "D-09: ToolLoopResult/ToolExecutor/ActionCollector stay in llm_loop.py, forward-referenced via TYPE_CHECKING — avoids runtime import edge"
  - "D-03: stream() raises NotImplementedError in both defaults — no production caller uses stream() today"
metrics:
  duration: "~15 minutes"
  completed_date: "2026-05-01"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 3
  loc_added: ~480
  loc_removed: 0
---

# Phase 226 Plan 01: AI Provider Extension Protocol Scaffold Summary

**One-liner:** Purely additive AIProviderExtension Protocol scaffold — dict-keyed accessor with Anthropic/OpenAI community defaults whose complete() bodies are _loop_anthropic/_loop_openai copied verbatim.

## Objective

Establish the AIProviderExtension seam without any behavior change. The existing `run_tool_loop`, `_loop_anthropic`, and `_loop_openai` in `llm_loop.py` remain untouched and continue driving every production caller. Plan 02 migrates callers.

## What Was Built

### Task 1: AIProviderExtension Protocol (protocols.py)

Added `AIProviderExtension` after `BillingExtension` (line 84 → now line 152):

- `@runtime_checkable` decorator per D-07
- Three async keyword-only methods: `complete()`, `stream()`, `resolve_runtime_config(db)`
- `complete()` and `stream()` signatures mirror `run_tool_loop()` minus the `provider` arg
- `max_rounds: int = ...` uses Protocol-style ellipsis default (implementations supply `MAX_TOOL_ROUNDS`)
- Extended `if TYPE_CHECKING:` block with `ToolLoopResult`, `ToolExecutor`, `ActionCollector` forward refs from `app.processing.ai.llm_loop` — typing-only edge, no runtime import

File: `protocols.py` grew from 84 → 152 lines (+68 LOC).

### Task 2: DefaultAnthropicProvider + DefaultOpenAICompatibleProvider (defaults.py)

Appended two new provider classes after `DefaultProcessingPort` (line 391 → now line 764):

**DefaultAnthropicProvider:**
- `complete()` body is `_loop_anthropic` from `llm_loop.py:192-277` copied verbatim
- Class-level `_client = None` cache (survives test registry resets)
- Lazy `AsyncAnthropic` client init inside `complete()` body
- All imports deferred inside `complete()` body per Phase 214 discipline (no top-level SDK imports)
- `stream()` raises `NotImplementedError` per D-03
- `resolve_runtime_config(db)` returns `{"base_url": None, "default_model": model}`

**DefaultOpenAICompatibleProvider:**
- `complete()` body is `_loop_openai` from `llm_loop.py:294-404` copied verbatim
- Class-level `_clients: dict = {}` keyed by `base_url`
- Anthropic→OpenAI tool format conversion at top of `complete()` per D-08 (callers pass Anthropic-shape, provider converts internally)
- Uses `effective_base_url = base_url or settings.openai_base_url or "https://api.openai.com/v1"` (mirrors original `_loop_openai:295`)
- All imports deferred inside `complete()` body
- `stream()` raises `NotImplementedError` per D-03
- `resolve_runtime_config(db)` returns `{"base_url": base_url, "default_model": model}`

File: `defaults.py` grew from 391 → 764 lines (+373 LOC). `isinstance(DefaultAnthropicProvider(), AIProviderExtension)` and `isinstance(DefaultOpenAICompatibleProvider(), AIProviderExtension)` both pass.

### Task 3: get_ai_provider(name) accessor (__init__.py)

Three modifications:

1. Added `DefaultAnthropicProvider` and `DefaultOpenAICompatibleProvider` to imports (alphabetical)
2. Added `from app.platform.extensions.protocols import AIProviderExtension` to TYPE_CHECKING block
3. Appended `get_ai_provider(name: str) -> "AIProviderExtension"` after `get_processing_port()`

The accessor:
- `_extensions.setdefault("ai_providers", {})` creates the dict-keyed slot (D-04 — new shape)
- Per-key `setdefault` seeds both community defaults without overwriting overlay registrations (D-05)
- Raises `ValueError(f"Unknown LLM provider: {name}")` for unknown names (D-06 — preserves `llm_loop.py:149` exception message)
- Singleton stable: two calls return the same instance (verified via `p1 is p2`)

File: `__init__.py` grew from 219 → 255 lines (+36 LOC).

## Verification Results

| Check | Result |
|-------|--------|
| `isinstance(DefaultAnthropicProvider(), AIProviderExtension)` | PASS |
| `isinstance(DefaultOpenAICompatibleProvider(), AIProviderExtension)` | PASS |
| `get_ai_provider('anthropic')` returns `DefaultAnthropicProvider` | PASS |
| `get_ai_provider('openai_compatible')` returns `DefaultOpenAICompatibleProvider` | PASS |
| `get_ai_provider('xyz')` raises `ValueError("Unknown LLM provider: xyz")` | PASS |
| Singleton stability: two calls return same instance | PASS |
| `ruff check app/platform/extensions/` | PASS |
| Architecture guard tests (`test_layering.py -m architecture`) | 10 passed |
| Full backend test suite | **2050 passed, 19 skipped** (baseline preserved) |

## Commits

| Hash | Task | Message |
|------|------|---------|
| c3217960 | Task 1 | feat(226-01): add AIProviderExtension Protocol to protocols.py |
| c4645957 | Task 2 | feat(226-01): add DefaultAnthropicProvider + DefaultOpenAICompatibleProvider to defaults.py |
| 07265d14 | Task 3 | feat(226-01): add get_ai_provider(name) accessor to extensions/__init__.py |

## Deviations from Plan

None — plan executed exactly as written.

The only minor note: `NotImplementedError` appears 3 times in defaults.py (once in `DefaultAnthropicProvider`'s docstring mentioning it, and once per `stream()` raise statement). The acceptance criteria said "2" which referred to the 2 raise statements — both present and correct.

## Baseline Confirmation

- `_loop_anthropic` at `llm_loop.py:179-277` STILL PRESENT — Plan 02 deletes it
- `_loop_openai` at `llm_loop.py:280-404` STILL PRESENT — Plan 02 deletes it
- `if provider == "anthropic"` dispatch at `llm_loop.py:117,132,160`, `service.py:394`, `sql_generator.py:351,355`, `metadata_service.py:255,291`, `streaming.py:516,531` — ALL UNCHANGED
- `grep -rn "if.*provider.*==" backend/app/processing/ai/` count: 10 matches (unchanged from pre-Plan-01 baseline — Plan 01 adds zero new dispatch sites and removes zero)
- No production code path calls `get_ai_provider()` yet — that is Plan 02's responsibility

## Known Stubs

None — both provider classes contain complete, working implementations (bodies copied verbatim from `_loop_anthropic`/`_loop_openai`). The `stream()` methods intentionally raise `NotImplementedError` per D-03, documented in both docstrings and CONTEXT.md.

## Threat Flags

No new security surface introduced. The new code lives in `platform/extensions/` (community-edition defaults) and is not wired to any production request path at this plan. API keys are accessed via `reveal(settings.*)` (T-226-01 mitigated). No new network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

Files exist:
- `backend/app/platform/extensions/protocols.py` — FOUND (152 lines)
- `backend/app/platform/extensions/defaults.py` — FOUND (764 lines)
- `backend/app/platform/extensions/__init__.py` — FOUND (255 lines)

Commits exist:
- c3217960 — FOUND
- c4645957 — FOUND
- 07265d14 — FOUND
