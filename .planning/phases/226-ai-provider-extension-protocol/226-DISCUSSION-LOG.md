# Phase 226: ai-provider-extension-protocol - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-01
**Phase:** 226-ai-provider-extension-protocol
**Areas discussed:** accessor-shape, protocol-granularity, tool-format-normalization, loop-bodies-location, stream-method-default, provider-config-ownership, architecture-guard-regex, test-seam-mechanism

**Mode:** `--auto` — Claude auto-selected the recommended option for every gray area without interactive prompts. All decisions are inline-logged below for audit.

---

## Accessor shape

| Option | Description | Selected |
|--------|-------------|----------|
| List-shape (Phase 222/223 pattern) | `_extensions["ai_providers"] = list[AIProviderExtension]`; each extension has a `name` attribute; lookup is linear scan | |
| Single-slot (Phase 214/225 pattern) | `_extensions["ai_provider"]` holds ONE extension; overlays REPLACE | |
| Name-keyed dict (NEW shape) | `_extensions["ai_providers"] = dict[str, AIProviderExtension]`; lookup by name is O(1) | ✓ |

**User's choice (auto-selected):** Name-keyed dict
**Notes:** AI providers fan out by NAME at request time (`LLM_PROVIDER` PersistentConfig stores `"anthropic"` / `"openai_compatible"`). List requires linear scan + name-attribute matching; single-slot can't hold multiple. Dict-shape matches the audit's "dispatch table" wording verbatim. Sets a precedent for future "fan-out by name" extensions (e.g., Phase 999.13 connector adapters).

---

## Protocol granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Wide (full tool-loop) | `complete()` runs the entire tool-calling loop for that provider; subsumes today's `_loop_anthropic`/`_loop_openai` | ✓ |
| Narrow (per-LLM-call) | `complete()` does ONE LLM round; tool-loop orchestration stays in `llm_loop.py` and uses `provider.parse_tool_calls()` etc. | |

**User's choice (auto-selected):** Wide
**Notes:** The audit's dispatch sites at `llm_loop.py:117,132` route to whole-loop helpers, so the natural seam IS the whole loop. Narrow shape would still need provider-specific `parse_tool_calls(response)` + `format_tool_result(result)` Protocol methods — adding 4-5 more methods that all branch on provider response shape. Wide is cleaner and matches the audit's intent.

---

## Tool format normalization

| Option | Description | Selected |
|--------|-------------|----------|
| Unified canonical (Anthropic-shape) | `complete(tools=...)` takes Anthropic JSON-Schema format; provider converts internally | ✓ |
| Provider-native at call site | Caller picks the right format (`tools_anthropic` vs `tools_openai`) before calling | |
| Unified canonical (OpenAI-shape) | Use OpenAI's wrapped format as the canonical; Anthropic provider unwraps | |

**User's choice (auto-selected):** Unified canonical (Anthropic-shape)
**Notes:** Eliminates the dual `tools_anthropic`/`tools_openai` argument pair on `run_tool_loop`. Anthropic format (`{name, description, input_schema}`) is the cleaner JSON Schema shape; OpenAI's `{type: "function", function: {...}}` wraps it trivially. The existing `TOOLS_ANTHROPIC` constants are the source of truth.

---

## Loop bodies location

| Option | Description | Selected |
|--------|-------------|----------|
| Move into provider classes | `_loop_anthropic` body becomes `DefaultAnthropicProvider.complete()`; `_loop_openai` becomes `DefaultOpenAICompatibleProvider.complete()` | ✓ |
| Keep in `llm_loop.py` as private helpers | Provider classes just call `_loop_anthropic` / `_loop_openai` based on their identity | |

**User's choice (auto-selected):** Move into provider classes
**Notes:** Cleanest separation. Each provider class IS the implementation for its name. Keeping helpers in `llm_loop.py` would either re-introduce internal `if self.name == ...` branches OR force the helpers to know about both shapes — both undesirable.

---

## Stream method default behavior

| Option | Description | Selected |
|--------|-------------|----------|
| `NotImplementedError` in defaults | Protocol declares `stream()` per SC#1; community defaults raise — overlays implement | ✓ |
| Fall through to `complete()` + single yield | Default `stream()` calls `complete()` and yields the result as a single chunk | |
| Implement true streaming | Wire to Anthropic `messages.stream` / OpenAI `chat.completions.create(stream=True)` for real token streaming | |

**User's choice (auto-selected):** `NotImplementedError` in defaults
**Notes:** "Ships only the seam — new provider implementations land in overlays or follow-up milestones" (ROADMAP §226 goal). No production caller invokes `stream()` today (`stream_generate_map` semi-streams via `complete()` + milestone events). True streaming is a meaningful UX phase of its own. NotImplementedError loudly signals deferred status.

---

## Provider-specific runtime config ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Provider class owns config | Each provider exposes `resolve_runtime_config(db) -> dict`; `resolve_provider()` delegates | ✓ |
| Keep `if provider == "openai_compatible":` branch in `resolve_provider` | Add an exception to the architecture-guard regex | |
| Move base_url to a separate dispatch table | New `_extensions["ai_provider_configs"]` registry | |

**User's choice (auto-selected):** Provider class owns config
**Notes:** Required to satisfy SC#3's binding grep — `if provider == "openai_compatible":` at `llm_loop.py:160` matches the regex today. Adding regex exceptions undermines the seam-quality argument. Per-provider config method also generalizes to future providers (Bedrock reads AWS creds, Vertex reads GCP creds).

---

## Architecture-guard regex strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Strict zero-hit, no allowlist | Mirror Phase 225 D-23 — all hits must migrate; no exceptions | ✓ |
| Allowlist (Phase 224 pattern) | Permit specific files to keep `if provider ==` references | |

**User's choice (auto-selected):** Strict zero-hit
**Notes:** Codebase scan confirms today's only hits are at the migration sites (`llm_loop.py:117, 132, 160-161`, `service.py:394`). No legitimate side-effect provider-name comparison exists in `processing/`. Strict mirrors the most recent precedent (Phase 225 D-23).

---

## Test seam mechanism (SC#5)

| Option | Description | Selected |
|--------|-------------|----------|
| `entry_points` mock pattern | `patch("app.platform.extensions.entry_points", return_value=[mock_ep])` from `test_extensions.py` precedent | ✓ |
| Real package install in pytest fixture | Generate a tiny Python package, install via `pip install -e`, register entry point, run, uninstall | |
| Direct `_extensions` registry mutation | Skip the entry_points layer; directly insert a fake provider into `_extensions["ai_providers"]` | |

**User's choice (auto-selected):** entry_points mock
**Notes:** Established codebase pattern (6+ usages in `test_extensions.py`). Cleaner than real package install (no filesystem mutation per test). Direct registry mutation skips the entry_points layer — wouldn't satisfy SC#5's binding "registered via `importlib.metadata` entry_points" wording.

---

## Claude's Discretion

The following implementation details were left to the planner per the CONTEXT.md "Claude's Discretion" section:

- Commit decomposition (likely 3 atomic commits; planner may collapse/split based on file-size budgets).
- Module docstring wording for the new Protocol class.
- Whether `run_tool_loop()` is preserved as a thin facade or deleted entirely (default: delete).
- Whether `_cached_anthropic_client` / `_cached_openai_clients` caches move into the provider classes or stay module-level (default: move).
- Whether `stream()` declares `AsyncIterator[...]` return type or `ToolLoopResult` (default: `ToolLoopResult`).
- Test naming for `test_ai_provider_extension.py` (default: `test_default_providers_registered`, `test_overlay_provider_is_dispatched`, `test_unknown_provider_raises_value_error`).
- Whether `resolve_runtime_config` is part of the Protocol or just a community-default convenience method (default: part of the Protocol — overlays will need it).
- Class names: `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider` (default; planner may use `DefaultAnthropicAIProvider` if disambiguation matters).
- Pathspec scope for the architecture-guard test (default: `backend/app/processing/` — wider than SC#3's `processing/ai/` because the regex doesn't constrain narrower).

## Deferred Ideas

See `<deferred>` section in CONTEXT.md for the full list. Highlights:

- New provider implementations (Bedrock / Vertex / Azure / vLLM) — overlays or follow-up phases.
- True LLM-token streaming — separate UX phase.
- `WorkflowExtension` (Phase 999.9), `PermissionExtension` (Phase 999.8), `Connector` ORM (Phase 999.13).
- Provider configuration UX (admin UI metadata for registered providers) — out of seam-only scope.
- Tightening the architecture-guard regex beyond SC#3's two-name match — P3 follow-up.

---

*Generated 2026-05-01 by `--auto` mode discussion.*
