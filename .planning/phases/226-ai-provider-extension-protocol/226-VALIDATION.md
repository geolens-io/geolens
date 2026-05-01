---
phase: 226
slug: ai-provider-extension-protocol
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-01
---

# Phase 226 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (uv run pytest) |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/test_ai_provider_extension.py tests/test_layering.py -x -q` |
| **Full suite command** | `cd backend && uv run pytest --tb=short -q` |
| **Estimated runtime** | ~120 seconds (full); ~3 seconds (quick) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_ai_provider_extension.py tests/test_layering.py -x -q`
- **After every plan wave:** Run `cd backend && uv run pytest --tb=short -q`
- **Before `/gsd-verify-work`:** Full suite must be green (2050+/2050+ baseline)
- **Max feedback latency:** 5 seconds for quick run; 120 seconds for full

---

## Per-Task Verification Map

(Filled by gsd-planner — every task gets a row mapping it to its requirement, threat ref, and automated command.)

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD by planner — see Wave 0 below for the test files that must exist before task verification can run |

---

## Wave 0 Requirements

- [ ] `backend/tests/test_ai_provider_extension.py` — NEW. Stubs for AIEXT-01, AIEXT-02, AIEXT-04. Includes:
  - `test_default_providers_registered` — `get_ai_provider("anthropic")` and `get_ai_provider("openai_compatible")` return `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider` after fresh `load_extensions()`.
  - `test_overlay_provider_is_dispatched` — registers a fake `TestProvider` via `patch("app.platform.extensions.entry_points")` mock + `register_extensions(registry)` callback; asserts `get_ai_provider("test_provider").complete()` returns the fake's response.
  - `test_unknown_provider_raises_value_error` — `get_ai_provider("nonexistent")` raises `ValueError("Unknown LLM provider: nonexistent")`.
  - Autouse fixture: imports/uses `_reset_registry` to prevent cross-test leakage (per RESEARCH.md Pitfall 6).
- [ ] `backend/tests/test_layering.py` — UPDATE existing file. Add `test_no_hardcoded_ai_provider_branches` covering AIEXT-03 + AIEXT-05. Mirrors `test_no_log_action_calls_outside_audit_service` (`:421-491`) verbatim:
  - `_has_git_metadata()` skip guard, `_has_pathspec_magic()` git-version check.
  - `git grep -n -E "if .*provider *== *['\"](anthropic|openai_compatible)" -- backend/app/processing/ ':!backend/app/processing/ai/streaming.py' ':!backend/app/processing/ai/metadata_service.py' ':!backend/tests/'`.
  - On exit-code 0 (matches found): `pytest.fail(...)` with offending lines.
  - Update module docstring to credit Phase 226 alongside 212/213/214/222/223/224/225.
- [ ] No new framework install — pytest already in `backend/pyproject.toml`; `pytest.mark.architecture` marker registered in Phase 212.

---

## Nyquist Dimensions (per RESEARCH.md §Validation Architecture)

| # | Dimension | Concrete Verification |
|---|-----------|----------------------|
| 1 | **Existence** | `isinstance(get_ai_provider("anthropic"), AIProviderExtension)` returns `True` |
| 2 | **Behavior** | `DefaultAnthropicProvider.complete(...)` returns `ToolLoopResult` with byte-identical shape to today's `_loop_anthropic` (existing AI integration tests cover this) |
| 3 | **Boundary** | `complete(tools=[], max_rounds=1, ...)` works without crashing — exercises retry-parse and SQL-generator migration paths |
| 4 | **Data flow** | entry_points → `load_extensions()` → `_extensions["ai_providers"]` → `get_ai_provider("test")` end-to-end (test_overlay_provider_is_dispatched) |
| 5 | **Integration** | Full backend test suite passes (2050/2050 baseline maintained per SC#4) |
| 6 | **State management** | `get_ai_provider("anthropic")` called twice returns the SAME instance (registry singleton, not re-seeded per call) |
| 7 | **Error handling** | `get_ai_provider("unknown")` raises `ValueError("Unknown LLM provider: unknown")` (matches today's exception type/message) |
| 8 | **Architecture invariants** | Negative-control: temporarily insert `if provider == "anthropic":` in `processing/ai/sql_generator.py`, run `pytest tests/test_layering.py::test_no_hardcoded_ai_provider_branches`, confirm RED. Revert, confirm GREEN. (D-14) |

---

## Pathspec Exclusions in Architecture Guard

**Confirmed by RESEARCH.md scope decisions (researcher recommendation accepted in --auto mode):**

| File | Reason for Exclusion | Follow-Up Phase |
|------|---------------------|-----------------|
| `backend/app/processing/ai/streaming.py` | True LLM-token streaming via `_stream_anthropic_chat` / `_stream_openai_chat` (~200 LOC each). Migrating these into `stream()` defaults removes D-03's `NotImplementedError` and adds 400 LOC of streaming code per default — beyond seam-only scope. CONTEXT.md §deferred lists "True LLM-token streaming" as a deferred phase. | Future: implement `stream()` properly, remove the exclusion. |
| `backend/app/processing/ai/metadata_service.py` | Uses structured-output APIs (`client.beta.chat.completions.parse` for OpenAI, `tool_choice={"type":"tool"}` for Anthropic) that don't map to the `complete()` Protocol shape (which returns `ToolLoopResult`, not Pydantic models). | Future: add `structured_complete(response_model, ...)` Protocol method, then migrate. |

The exclusions are documented (NOT silently hidden) and have a clear deferred-follow-up phase. SC#3's wording (`backend/app/processing/ai/`) is path-bound; the architecture guard's pathspec adds `:!streaming.py` and `:!metadata_service.py` to scope-down to migrated files. This is a deviation from CONTEXT.md D-23 ("strict zero-hit, no allowlist") justified by research findings (10 sites, not 5; two of the additional files require Protocol-shape changes outside seam-only scope).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Existing AI chat features (chat-edit-map, generate-map-from-prompt) work end-to-end after migration | SC#4 | Live LLM calls aren't part of the unit/integration test suite (would require API keys + network) | Run the dev server (`docker compose up`), open the map builder, attempt a chat-edit-map session and a generate-map-from-prompt session against the configured LLM provider. Confirm responses behave identically to pre-Phase-226. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (planner fills)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (planner ensures)
- [ ] Wave 0 covers all MISSING references (test_ai_provider_extension.py + test_layering.py update)
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s for quick run, < 120s for full
- [ ] `nyquist_compliant: true` set in frontmatter (after Wave 0 lands)

**Approval:** pending — awaiting Wave 0 completion + planner per-task verification map fill-in
