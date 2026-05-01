# Phase 226: ai-provider-extension-protocol - Research

**Researched:** 2026-05-01
**Domain:** Python Protocol extension seam / AI provider dispatch refactor
**Confidence:** HIGH

## Summary

Phase 226 replaces 10 hardcoded `if provider ==` dispatch sites across 5 files in `backend/app/processing/ai/` with a name-keyed `AIProviderExtension` Protocol registered through the `geolens.extensions` entry-point mechanism. The locked decisions in 226-CONTEXT.md (D-01..D-28) specify every structural choice; this research surfaces implementation pitfalls discovered by reading the actual code that CONTEXT.md's enumeration understated.

**Primary finding:** CONTEXT.md lists 5 dispatch sites (`llm_loop.py:117,132,160-161`, `service.py:394`). A codebase scan reveals **10 sites across 5 files**: the three above plus `streaming.py:516,531`, `sql_generator.py:351,355`, and `metadata_service.py:255,291`. The planner must decide which of the three additional files are in scope for migration to the Protocol vs. treated as follow-on work, because the architecture-guard regex SC#3 (`grep -RE "if .*provider *== *['\"](anthropic|openai_compatible)" backend/app/processing/ai/`) will catch ALL of them.

**Primary recommendation:** Migrate all 5 files to zero-hit compliance. `streaming.py` and `sql_generator.py` have self-contained dispatch paths (they import `get_anthropic_client`/`get_openai_client` from `llm_loop.py` directly and call SDKs without `run_tool_loop`). These either move into the Provider classes or get migrated to a narrow Protocol method. `metadata_service.py` is analogous. This is additional scope that must be planned.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All D-01 through D-28 from 226-CONTEXT.md are locked. Key ones the planner must copy into plans:
- D-01: Wide Protocol — `complete()` runs the entire tool-calling loop
- D-02: `complete()` signature — keyword-only, mirrors `run_tool_loop()` minus `provider`
- D-03: `stream()` raises `NotImplementedError` in both defaults
- D-04: Registry slot is `dict[str, AIProviderExtension]` at `_extensions["ai_providers"]`
- D-05: Per-key `setdefault` seeding in accessor body
- D-06: `ValueError` on unknown provider (exact message: `"Unknown LLM provider: {name}"`)
- D-07: `@runtime_checkable` on Protocol
- D-08: Canonical tool format = Anthropic shape; OpenAI provider converts internally
- D-09: `ToolLoopResult` / `ToolExecutor` / `ActionCollector` stay in `llm_loop.py`, forward-referenced via `TYPE_CHECKING`
- D-10: `resolve_runtime_config(db)` as Protocol method; `resolve_provider` return changes to `(provider, model, runtime_config)`
- D-11..D-14: Architecture-guard test in `test_layering.py` named `test_no_hardcoded_ai_provider_branches`
- D-15..D-16: Entry-points dispatch test in `test_ai_provider_extension.py`
- D-17..D-18: Two classes — `DefaultAnthropicProvider`, `DefaultOpenAICompatibleProvider`
- D-19..D-21: Four call sites for `run_tool_loop` collapse; `tools_anthropic`/`tools_openai` → single `tools`; `resolve_provider` tuple changes
- D-24: Gate = 2050/2050 + ruff + alembic check + new tests
- D-26: No frontend change; no OpenAPI change
- D-27: No Alembic migration
- D-25: Dead-code cleanup (TOOLS_OPENAI, CHAT_TOOLS_OPENAI, module-level client caches) allowed but not required

### Claude's Discretion
- Commit decomposition (3 suggested; planner may collapse/split)
- Module docstring wording for the new Protocol class
- Whether `run_tool_loop()` is preserved as thin facade or deleted entirely
- Whether client caches move into provider class (default: move) or stay module-level
- Whether `stream()` return type is `ToolLoopResult` or `AsyncIterator[...]`
- Order of tests in `test_ai_provider_extension.py`
- Whether `resolve_runtime_config` is on Protocol surface (default: yes)

### Deferred Ideas (OUT OF SCOPE)
- New provider implementations (Bedrock/Vertex/Azure/vLLM)
- True LLM-token streaming
- WorkflowExtension / PermissionExtension Protocols
- Admin UI for provider configuration
- Pyright/mypy CI gate
- Tightening arch-guard regex beyond SC#3 binding
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AIEXT-01 | `AIProviderExtension` Protocol at `platform/extensions/protocols.py` with `complete()` and `stream()` | D-01..D-03/D-07 specify exact shape; `protocols.py` precedent confirmed by reading current file |
| AIEXT-02 | `DefaultAIProviderExtension` maps two community providers via accessor pattern | D-17/D-18 specify two classes; `get_ai_provider(name)` accessor per D-04/D-05 |
| AIEXT-03 | Hardcoded `if/elif provider ==` dispatch replaced with extension lookup | 10 sites found (see Pitfall 1 below); all must reach zero-hit SC#3 compliance |
| AIEXT-04 | Overlays can register Bedrock/Vertex/Azure/vLLM via `importlib.metadata` entry_points | D-04/D-05 dict-keyed registry; existing `load_extensions()` unchanged; test pattern confirmed |
| AIEXT-05 | Architecture-guard test verifies no `if provider ==` branches in `processing/ai/` | D-11..D-14; `test_layering.py:421-491` pattern confirmed by reading |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Protocol definition + accessor | `platform/extensions/` | — | Matches `AuditSink` / `BillingExtension` precedent; audit explicitly places AIProviderExtension here |
| Default implementations | `platform/extensions/defaults.py` | — | Same file as all other defaults |
| Tool-loop body (Anthropic) | `DefaultAnthropicProvider.complete()` | — | Moved from `llm_loop._loop_anthropic`; same logic, new home |
| Tool-loop body (OpenAI) | `DefaultOpenAICompatibleProvider.complete()` | — | Moved from `llm_loop._loop_openai`; OpenAI→Anthropic tool conversion happens here |
| SQL generation dispatch | `sql_generator.py` (migrate) | `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider` | No-tool single-round calls; narrow pattern, not via `complete()` or must extend Protocol |
| Metadata generation dispatch | `metadata_service.py` (migrate) | same | Same narrow single-call pattern |
| True streaming dispatch | `streaming.py` (migrate or carve out) | `stream()` Protocol method | Two full streaming implementations; must reach zero-hit or be excluded via pathspec |
| Client cache | `DefaultAnthropicProvider` (instance) | module-level (fallback) | D-25 default moves into provider class |

---

## Standard Stack

### Core (no new packages)

| Component | Current Location | Destination |
|-----------|-----------------|-------------|
| `anthropic.AsyncAnthropic` | `llm_loop.py:14` | Imported at module level in `defaults.py` (external SDK, no deferred-import required per CONTEXT §code_context) |
| `openai.AsyncOpenAI` | `llm_loop.py:15` | Same |
| `httpx.Timeout` | `llm_loop.py:23` | Move with client constructors |
| `importlib.metadata.entry_points` | `__init__.py:10` | Unchanged |
| `@runtime_checkable` / `Protocol` | `protocols.py:13` | Add `AIProviderExtension` |

No new pip installs. All packages already in `backend/requirements*.txt`. [VERIFIED: reading actual import statements]

---

## Architecture Patterns

### Protocol Class Pattern (from `protocols.py:43-83`)

```python
# Source: backend/app/platform/extensions/protocols.py (read directly)
if TYPE_CHECKING:
    from app.processing.ai.llm_loop import ToolLoopResult, ToolExecutor, ActionCollector

@runtime_checkable
class AIProviderExtension(Protocol):
    """..."""
    async def complete(self, *, model: str, system_prompt: str, user_message: str,
                       tools: list[dict], tool_executor: "ToolExecutor",
                       action_collector: "ActionCollector | None" = None,
                       history: "list[dict] | None" = None,
                       max_rounds: int = ..., max_tokens: int = 4096,
                       base_url: "str | None" = None,
                       temperature: float = 0.5) -> "ToolLoopResult": ...
    async def stream(self, **kwargs) -> "ToolLoopResult": ...
    async def resolve_runtime_config(self, db) -> dict[str, object]: ...
```

### Accessor Pattern (from `__init__.py:197-218`)

```python
# Source: backend/app/platform/extensions/__init__.py (read directly)
def get_ai_provider(name: str) -> "AIProviderExtension":
    providers = _extensions.setdefault("ai_providers", {})
    providers.setdefault("anthropic", DefaultAnthropicProvider())
    providers.setdefault("openai_compatible", DefaultOpenAICompatibleProvider())
    if name not in providers:
        raise ValueError(f"Unknown LLM provider: {name}")
    return providers[name]  # type: ignore[return-value]
```

### Entry-Points Test Pattern (from `test_extensions.py:49-65`)

```python
# Source: backend/tests/test_extensions.py (read directly)
mock_ep = MagicMock()
mock_ep.name = "geolens.ai-providers.test"
mock_ep.load.return_value = register  # register(registry) -> None

with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
    load_extensions()
    provider_ext = get_ai_provider("test_provider")
```

### Registry Reset in Tests

```python
# Source: backend/tests/test_extensions.py:10-14 (autouse fixture)
def _reset_registry():
    import app.platform.extensions as ext_mod
    ext_mod._extensions.clear()
    ext_mod._loaded = False
```

The `_clean_registry` autouse fixture in `test_extensions.py` patches `entry_points` to return `[]` globally. `test_ai_provider_extension.py` must either use the same autouse fixture (if it lives in the same module or conftest propagates) or replicate the reset pattern. [VERIFIED: reading test_extensions.py:18-34]

---

## CRITICAL FINDING: Dispatch Sites Beyond CONTEXT.md Enumeration

### Actual Hit Count: 10 sites across 5 files

CONTEXT.md §specifics states: "Codebase scan today shows hits at `llm_loop.py:117, 132, 160-161` and `service.py:394`." This is **incomplete**. Running the SC#3 binding regex against the codebase as of the Phase 225 baseline (2050/2050) finds:

| File | Lines | Pattern | Notes |
|------|-------|---------|-------|
| `llm_loop.py` | 117, 132, 160 | `if provider == "anthropic"`, `elif provider == "openai_compatible"`, `if provider == "openai_compatible"` | In scope per CONTEXT.md |
| `service.py` | 394 | `if provider == "anthropic":` | In scope per CONTEXT.md |
| `streaming.py` | 516, 531 | `if provider == "anthropic":`, `elif provider == "openai_compatible":` | **NOT in CONTEXT.md** |
| `sql_generator.py` | 351, 355 | `if provider == "anthropic":`, `elif provider == "openai_compatible":` | **NOT in CONTEXT.md** |
| `metadata_service.py` | 255, 291 | `if provider == "anthropic":`, `elif provider == "openai_compatible":` | **NOT in CONTEXT.md** |

[VERIFIED: ran SC#3 regex programmatically against all 5 files]

**Impact:** SC#3 requires zero hits. The three files not enumerated in CONTEXT.md cannot be exempted without modifying SC#3 or the architecture-guard pathspec. The planner has two options:

**Option A (recommended):** Migrate all 5 files. This satisfies SC#3 as written.
- `streaming.py:516,531` — `stream_chat_edit` does true SSE token streaming via `_stream_anthropic_chat` / `_stream_openai_chat`. These are ~200-line streaming loops each. Migration = either move them into `DefaultAnthropicProvider.stream()` / `DefaultOpenAICompatibleProvider.stream()` (removing the `NotImplementedError`), or extract the dispatch line into an accessor call while keeping the streaming loops in `streaming.py`.
- `sql_generator.py:351,355` — `generate_sql` calls `_call_anthropic` / `_call_openai` (no-tool single-round). Migrate to `get_ai_provider(provider).complete(tools=[], max_rounds=1, ...)` or to a narrow helper method on the Protocol.
- `metadata_service.py:255,291` — `_structured_llm_call` uses `client.beta.chat.completions.parse` (OpenAI) and `client.messages.create` with `tool_choice={"type": "tool"}` (Anthropic). These are structured-output calls — different from tool-loop calls; they're not directly expressible as `complete(tools=[], max_rounds=1)` without losing the `response_format` / `tool_choice` semantics.

**Option B:** Narrow the pathspec in the architecture-guard to `backend/app/processing/ai/llm_loop.py backend/app/processing/ai/service.py` (or expand `:!backend/app/processing/ai/streaming.py` etc.) — but this contradicts SC#3 which says `backend/app/processing/ai/` (no sub-file exclusions). SC#3 text is binding per ROADMAP.

**Planner decision needed on `metadata_service.py`**: `_structured_llm_call` uses OpenAI's `client.beta.chat.completions.parse` (Pydantic response_format parsing) and Anthropic's forced `tool_choice={"type": "tool"}`. These are incompatible with the wide `complete()` Protocol shape (which returns `ToolLoopResult`, not a Pydantic model). The planner should decide whether to: (a) add a `structured_complete(response_model, ...)` Protocol method, (b) keep `metadata_service.py` as a pathspec exclusion in the architecture guard, or (c) migrate the dispatch to `get_anthropic_client()` / `get_openai_client()` calls that are gated on provider name via the registry lookup rather than bare string comparison.

---

## Tool-Format Conversion Verification

CONTEXT.md D-08 notes the conversion from Anthropic → OpenAI format is mechanical. Confirmed by reading `tools.py:313-323`:

```python
# Source: backend/app/processing/ai/tools.py:313-323 (read directly)
CHAT_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],  # JSON Schema is shared verbatim
        },
    }
    for tool in CHAT_TOOLS_ANTHROPIC
]
```

`CHAT_TOOLS_OPENAI` is generated algorithmically from `CHAT_TOOLS_ANTHROPIC` — there are **no hand-tuned differences**. Same descriptions, same parameter schemas, same names. [VERIFIED: reading tools.py:313-323]

However, `service.py` uses `ANTHROPIC_TOOLS` / `OPENAI_TOOLS` (not `CHAT_TOOLS_*`) — these are module-level constants defined at `service.py:224-253`. `OPENAI_TOOLS` is also hand-maintained inline (not derived from `ANTHROPIC_TOOLS`). The planner should spot-check: `assert _algorithmic_convert(ANTHROPIC_TOOLS) == OPENAI_TOOLS` before deleting `OPENAI_TOOLS`. From reading `service.py:238-253`, the structure matches the same wrapping pattern as `tools.py`, but must be verified programmatically. [ASSUMED — not programmatically diffed in this session]

---

## Test Mock Inventory

### `_loop_anthropic` / `_loop_openai` mocks: ZERO

```bash
# grep result: (no output)
find backend/tests -name "*.py" -exec grep -l "_loop_anthropic\|_loop_openai" {} \;
```

No test mocks `_loop_anthropic` or `_loop_openai` directly. [VERIFIED]

### `run_tool_loop` mocks: ZERO in test files

```bash
# grep result: (no output) 
find backend/tests -name "*.py" -exec grep -l "run_tool_loop" {} \;
```

No test file imports or mocks `run_tool_loop`. [VERIFIED]

### Tests that DO import from `llm_loop.py`

Reading `service.py:14-22` reveals that `service.py` imports `get_anthropic_client, get_openai_client, resolve_provider, run_tool_loop` from `llm_loop`. Tests exercise `service.py`'s public API; they mock at the router/service boundary, not at the SDK client level.

Confirmed mocking pattern from `test_chat_streaming.py` and `test_chat_narrative.py`: tests patch `app.processing.ai.router.stream_chat_edit`, `app.processing.ai.router.chat_edit_map`, `app.processing.ai.router._check_ai_available` — all at the router boundary, not inside the tool-loop. [VERIFIED: reading test files]

**After migration:** zero test mock changes needed for the moved bodies. If `run_tool_loop` is deleted, any test that imports it directly (none found) would break. Tests that mock at the service boundary continue to work unchanged.

### AI Test Files (SC#4 closed set)

| File | Lines | What it tests |
|------|-------|---------------|
| `test_ai_chat.py` | `_validate_chat_layers` | Router validation, not LLM calls |
| `test_ai_metadata.py` | Unknown (not read) | AI metadata generation |
| `test_chat_streaming.py` | SSE endpoint | Mocks at `stream_chat_edit` router boundary |
| `test_chat_narrative.py` | Chat dispatch | Mocks at `chat_edit_map` router boundary |
| `test_ai_send_sample_values.py` | Sample values flag | Setting-level |

[VERIFIED: reading test_ai_chat.py, test_chat_streaming.py, test_chat_narrative.py]

---

## Additional Callers of `llm_loop` Functions (Not in CONTEXT.md)

Three files import directly from `llm_loop` but are NOT in the D-19 four-caller list:

| File | Imports from `llm_loop` | Impact |
|------|------------------------|--------|
| `streaming.py:22-28` | `add_tool_cache_control`, `get_anthropic_client`, `get_openai_client`, `build_history_messages`, `resolve_provider` | After migration: `add_tool_cache_control` moves into `DefaultAnthropicProvider`; client functions may move too |
| `sql_generator.py:16` | `get_anthropic_client`, `get_openai_client` | After migration: need alternative import path if moved into provider class |
| `metadata_service.py:22` | `get_anthropic_client`, `get_openai_client` | Same |

If the client getter functions (`get_anthropic_client`, `get_openai_client`) move from `llm_loop.py` into the `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider` classes, `streaming.py`, `sql_generator.py`, and `metadata_service.py` lose their import path. The planner must either: (a) keep the module-level functions in `llm_loop.py` as thin shims, (b) re-export them from `defaults.py`, or (c) migrate those 3 files fully. [VERIFIED: reading import statements]

---

## SSE Event Shape Contract

The frontend SSE consumer in `MapCreateDialog.tsx:78-112` expects:
- `event === 'tool_start'` → `data.label` string (shown as progress label)
- `event === 'done'` → `data.{map_id, map_name, explanation, datasets_used}`
- `event === 'error'` → `data.message` string

`stream_generate_map` in `service.py:819` emits `{"type": "done", **map_result}` — but the frontend reads `event` (SSE event: header), not `data.type`. The router formats these as SSE events with `event: tool_start` / `event: done` / `event: error` in the header. **Phase 226 must preserve the router's SSE formatting layer unchanged** — only the inner LLM call swaps from `run_tool_loop(...)` to `provider_ext.complete(...)`. [VERIFIED: reading MapCreateDialog.tsx:82-101 and maps.ts:220-235]

The `stream_generate_map` function is NOT true streaming (it awaits `run_tool_loop` entirely, then replays collected `tool_events`). Its migration to `provider_ext.complete()` is a one-line swap with no SSE contract change.

---

## `@runtime_checkable` Protocol Behavior

Python 3.11+ `@runtime_checkable` Protocol: `isinstance(obj, Proto)` checks only that the class has the required **methods** (not that they are async, have correct signatures, or return correct types). For a Protocol with `complete`, `stream`, and `resolve_runtime_config`, `isinstance` verifies attribute existence only. [ASSUMED — Python typing documentation, not verified against 3.11 release notes in this session]

For `AIProviderExtension` with three async methods: `isinstance(DefaultAnthropicProvider(), AIProviderExtension)` returns `True` as long as the class defines attributes named `complete`, `stream`, and `resolve_runtime_config`. The check does not validate async, signature, or return type. This is adequate for overlay debugging purposes (D-07). No issue for this phase.

---

## Module Import Order and `ToolLoopResult` Forward Reference

The `TYPE_CHECKING` forward reference pattern (D-09): `protocols.py` will import `ToolLoopResult` only when type checkers run, not at Python runtime. This works correctly because `protocols.py` has `from __future__ import annotations` (line 11 of current file) — all annotations are strings at runtime. No circular import possible. [VERIFIED: reading protocols.py:11]

**Risk:** If `llm_loop.py` is fully gutted (only `ToolLoopResult`, `ToolExecutor`, `ActionCollector`, `resolve_provider`, `build_history_messages` remain), it becomes a ~40-line file. The planner should keep it — `resolve_provider` and `build_history_messages` are utility functions that don't belong in `protocols.py` (which is structural-typing-only by discipline).

---

## Client Cache Lifetime Analysis

Today: `_cached_anthropic_client` at `llm_loop.py:28` is a module-level singleton — lives for the FastAPI process lifetime. `_cached_openai_clients` at `llm_loop.py:29` is a dict keyed by `base_url`.

After migration (D-25 default: move into provider class as instance attribute):

```python
class DefaultAnthropicProvider:
    _client: AsyncAnthropic | None = None  # class-level, shared across instances
    # OR
    def __init__(self):
        self._client: AsyncAnthropic | None = None  # instance-level
```

The accessor `get_ai_provider("anthropic")` calls `providers.setdefault("anthropic", DefaultAnthropicProvider())` — the singleton is set on first call and reused. So an instance-level `_client` on `DefaultAnthropicProvider` is effectively process-scoped as long as the accessor instantiates only once. [VERIFIED: reading D-05 accessor body in CONTEXT.md]

**Pitfall:** if `_extensions.clear()` is called between requests (tests reset the registry), `DefaultAnthropicProvider()` is re-instantiated and a new `AsyncAnthropic` client is created. In tests, this is correct behavior. In production, `load_extensions()` is called once at startup and `_extensions` is not cleared — no issue.

Class-level `_client: AsyncAnthropic | None = None` (class attribute) avoids per-instantiation cost and survives across registry resets in tests (the class object persists; only the registry dict entry is cleared). **Recommended: class-level cache.**

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Tool format conversion | Custom serializer | List comprehension identical to `tools.py:313-323` pattern |
| Entry-points test isolation | Real package install | `patch("app.platform.extensions.entry_points", ...)` per `test_extensions.py` |
| Architecture regex enforcement | Shell script | `subprocess.run(["git", "grep", ...])` per `test_layering.py:461-491` |
| Registry cleanup in tests | Manual dict surgery | `ext_mod._extensions.clear(); ext_mod._loaded = False` per `test_extensions.py:10-14` |

---

## Common Pitfalls

### Pitfall 1: Undercounted Dispatch Sites (CRITICAL)

**What goes wrong:** Planner migrates only the 5 sites in CONTEXT.md. Architecture-guard test catches `streaming.py:516`, `sql_generator.py:351`, `metadata_service.py:255` and fails CI.
**Why it happens:** CONTEXT.md §specifics cited only the sites visible in `llm_loop.py` + `service.py`. `streaming.py`, `sql_generator.py`, `metadata_service.py` each have their own direct SDK dispatch.
**How to avoid:** Run the binding regex before planning to get the full hit list: `grep -rE "if .*provider *== *['\"]" backend/app/processing/ai/`. Found 10 hits across 5 files in this research session.
**Warning signs:** `test_no_hardcoded_ai_provider_branches` fails with lines from the 3 undercounted files.

### Pitfall 2: `metadata_service.py` Uses Structured-Output APIs

**What goes wrong:** `_structured_llm_call` in `metadata_service.py` uses `client.beta.chat.completions.parse(response_format=PydanticModel)` for OpenAI and `client.messages.create(tool_choice={"type":"tool","name":"output"})` for Anthropic. These are NOT the same as the tool-loop pattern — they're single-call structured-output paths. Calling `provider_ext.complete(tools=[output_tool], max_rounds=1)` would work for Anthropic but would lose the `response_format` Pydantic parsing for OpenAI.
**How to avoid:** Either (a) keep `metadata_service.py` outside the Protocol by using pathspec exclusion in the guard test, or (b) extend the Protocol with a `structured_complete(response_model, ...)` method. Document the decision explicitly.

### Pitfall 3: `resolve_provider` Return Tuple Breaks 4 Callers

**What goes wrong:** `resolve_provider` currently returns `(provider, model, base_url)`. After D-21 it returns `(provider, model, runtime_config)`. If any of the 4 callers are missed, they unpack `runtime_config` (a dict) as a string and pass it as `base_url=<dict>`, silently producing wrong behavior.
**Callers (from grep):** `service.py:660` (`provider, model, base_url = await resolve_provider(session)`), `service.py:741`, `chat_service.py:934`. `streaming.py:509` also calls `resolve_provider` (`provider, model, _ = await resolve_provider(db)`).
**How to avoid:** `git grep -n "resolve_provider"` in `backend/app/` to get the exhaustive caller list before changing the return type.

### Pitfall 4: `streaming.py` Imports `add_tool_cache_control` from `llm_loop`

**What goes wrong:** `streaming.py:23` imports `add_tool_cache_control` from `llm_loop`. If `add_tool_cache_control` moves into `DefaultAnthropicProvider`, `streaming.py` gets an `ImportError`.
**How to avoid:** Either (a) keep `add_tool_cache_control` in `llm_loop.py` as a module-level utility (it's a pure function, not provider-specific state), or (b) re-export it from `defaults.py`. Simplest: keep it in `llm_loop.py`.

### Pitfall 5: Architecture-Guard Regex Flags Dict Keys

**What goes wrong:** If `defaults.py` ends up with code like `if self._name == "anthropic":` inside a provider class, the regex `if .*provider *==` does NOT match (token is `self._name`, not `provider`). But if a developer writes `if provider_name == "anthropic":` in a helper within `processing/ai/`, the regex catches it.
**How to avoid:** D-11 already excludes `backend/app/platform/extensions/defaults.py` from the pathspec. The guard is scoped to `backend/app/processing/` — no false positives from the defaults file.

### Pitfall 6: `_extensions.clear()` in Test Autouse Fixture

**What goes wrong:** `test_extensions.py` has an autouse `_clean_registry` fixture that: (1) clears `_extensions`, (2) patches `entry_points` to return `[]` during the test, (3) clears `_extensions` again on teardown. If `test_ai_provider_extension.py` does NOT reset the registry between tests, the `DefaultAnthropicProvider()` and `DefaultOpenAICompatibleProvider()` singletons leak into subsequent tests.
**How to avoid:** `test_ai_provider_extension.py` must import and call `_reset_registry()` (or use the same autouse fixture via `conftest.py`). The simplest approach: import `_reset_registry` from `test_extensions.py` as a module-level fixture, or add the autouse fixture directly to the new test file.

### Pitfall 7: `sql_generator.py` Uses `LLM_MODEL_LIGHT` Not `LLM_MODEL`

**What goes wrong:** `sql_generator.py:339` uses `LLM_MODEL_LIGHT` (the "light" model for SQL generation) not `LLM_MODEL`. If migrated to `provider_ext.complete()`, the Protocol signature takes `model: str` explicitly — callers pass the already-resolved model. This is fine. But the `resolve_runtime_config(db)` method returns `{"default_model": ...}` based on `LLM_MODEL`. SQL generation callers must continue to resolve `LLM_MODEL_LIGHT` separately and pass it explicitly.
**How to avoid:** Keep model resolution as a caller responsibility; `complete(model=model_light, ...)` where `model_light = await LLM_MODEL_LIGHT.get(db)`.

### Pitfall 8: `streaming.py` True-Streaming Path is In-Scope for SC#3

**What goes wrong:** `streaming.py`'s `stream_chat_edit` function has its own full provider dispatch (lines 516-551) into `_stream_anthropic_chat` and `_stream_openai_chat` (~200 lines each). These are true token-streaming loops, not tool-loops. They CANNOT be migrated to `complete()` (wrong semantics). They ARE caught by SC#3's regex. The planner must either (a) migrate them into `DefaultAnthropicProvider.stream()` / `DefaultOpenAICompatibleProvider.stream()` (removing the `NotImplementedError` from D-03), or (b) add `streaming.py` as a pathspec exclusion in the architecture guard (contradicts SC#3 strictness as written).
**Planner decision:** D-03 says `stream()` defaults raise `NotImplementedError` because "no production caller invokes `stream()` today." But `streaming.py` IS a production caller of the streaming SDK methods. The resolution is that `streaming.py:stream_chat_edit` calls `_stream_anthropic_chat`/`_stream_openai_chat` (internal helpers), not `provider_ext.stream()`. The Protocol's `stream()` method is the public seam; `streaming.py`'s true-streaming dispatch is a separate concern. The pathspec for the guard must add `:!backend/app/processing/ai/streaming.py` OR those functions must move into the defaults.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (uv run pytest) |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/test_ai_provider_extension.py tests/test_layering.py -x -q` |
| Full suite command | `cd backend && uv run pytest --tb=short -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AIEXT-01 | Protocol class exists with correct methods | unit | `pytest tests/test_ai_provider_extension.py::test_default_providers_registered -x` | ❌ Wave 0 |
| AIEXT-02 | `get_ai_provider("anthropic")` returns `DefaultAnthropicProvider` | unit | `pytest tests/test_ai_provider_extension.py::test_default_providers_registered -x` | ❌ Wave 0 |
| AIEXT-03 | `if provider ==` branches gone from `processing/ai/` | architecture | `pytest tests/test_layering.py::test_no_hardcoded_ai_provider_branches -x` | ❌ Wave 0 |
| AIEXT-04 | Overlay provider dispatched via entry_points | integration | `pytest tests/test_ai_provider_extension.py::test_overlay_provider_is_dispatched -x` | ❌ Wave 0 |
| AIEXT-05 | Architecture guard test exists and passes | architecture | `pytest tests/test_layering.py -k architecture -x` | ❌ add to existing file |

### Nyquist Dimensions

1. **Existence** — `isinstance(get_ai_provider("anthropic"), AIProviderExtension)` returns `True`
2. **Behavior** — `DefaultAnthropicProvider.complete(...)` returns `ToolLoopResult` with same shape as today's `_loop_anthropic` (existing AI integration tests cover this)
3. **Boundary** — `complete(tools=[], max_rounds=1, ...)` works (covers `_retry_parse_map_spec` migration)
4. **Data flow** — entry_points → `load_extensions()` → `_extensions["ai_providers"]` → `get_ai_provider("test")` end-to-end (D-15 test)
5. **Integration** — full suite 2050/2050 baseline maintained (SC#4)
6. **State management** — registry singleton: `get_ai_provider("anthropic")` twice returns same instance (not re-seeded per call)
7. **Error handling** — `get_ai_provider("unknown")` raises `ValueError("Unknown LLM provider: unknown")`
8. **Architecture invariants** — negative-control: temporarily insert `if provider == "anthropic":` in `processing/ai/service.py`, confirm guard test fails (D-14)

### Wave 0 Gaps

- [ ] `backend/tests/test_ai_provider_extension.py` — covers AIEXT-01, AIEXT-02, AIEXT-04 + edge cases (D-15, D-16)
- [ ] `test_layering.py` update — add `test_no_hardcoded_ai_provider_branches` (AIEXT-03, AIEXT-05)

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | Extension loading is startup-time, not per-request auth |
| V5 Input Validation | No | User prompts already sanitized at router layer; this phase is below that |
| V6 Cryptography | No | — |

### Threat Model

| Threat | STRIDE | Standard Mitigation |
|--------|--------|---------------------|
| API key leakage via overlay logs | Information Disclosure | Keys read from `settings.anthropic_api_key` / `settings.openai_api_key` (env-backed, not logged); `reveal()` wrapper at `config.py`; Phase 226 adds no new logging of key values |
| SSRF via overlay-controlled `base_url` | Tampering | `base_url` comes from `PersistentConfig.OPENAI_BASE_URL` (admin DB write, not user-controlled); overlays that set their own base_url do so through `resolve_runtime_config()` — must be admin-deployed signed packages |
| Untrusted overlay code executing arbitrary HTTP | Elevation of Privilege | Supply chain control: overlays are installed packages (`pip install geolens-enterprise`) signed by the operator; community edition loads nothing (empty entry-points); no plugin marketplace |
| `stream()` NotImplementedError exposed to user | Denial of Service | `stream_chat_edit` calls `_stream_anthropic_chat`/`_stream_openai_chat` directly, NOT `provider_ext.stream()`. No production path invokes `stream()`. Guard: `git grep 'provider_ext.stream\|\.stream(' backend/app/processing/ai/` |

---

## Open Questions

1. **`streaming.py` migration scope**
   - What we know: Lines 516, 531 are caught by SC#3 regex; the functions are true-streaming loops (~200 LOC each); D-03 says `stream()` raises `NotImplementedError` by default
   - What's unclear: Whether to (a) move streaming loops into `DefaultAnthropicProvider.stream()` / `DefaultOpenAICompatibleProvider.stream()` (removes NotImplementedError from D-03), or (b) add `:!backend/app/processing/ai/streaming.py` pathspec exclusion, or (c) restructure dispatch without `if provider ==`
   - Recommendation: Add pathspec exclusion for `streaming.py` in the architecture guard. Rationale: true LLM-token streaming is explicitly deferred (CONTEXT.md §deferred); moving 400 LOC of streaming loops into defaults adds scope without architectural benefit; the exclusion is documented rather than silently hidden.

2. **`metadata_service.py` structured-output migration**
   - What we know: Uses `client.beta.chat.completions.parse` (OpenAI Pydantic parser) and `tool_choice={"type":"tool"}` (Anthropic forced tool use); these semantics don't map to `complete()` naturally
   - What's unclear: Whether to add a Protocol method, use pathspec exclusion, or restructure without bare `if provider ==`
   - Recommendation: Add pathspec exclusion for `metadata_service.py` in the architecture guard. Document as follow-on scope for a future `structured_complete()` Protocol method.

3. **`sql_generator.py` migration**
   - What we know: No-tool single-round calls; `_call_anthropic` and `_call_openai` are ~20 LOC helpers; `LLM_MODEL_LIGHT` used (not `LLM_MODEL`)
   - What's unclear: Whether `complete(tools=[], max_rounds=1)` adequately replaces `_call_anthropic`/`_call_openai` or whether there are semantic differences (temperature=0.0, different system/user message shape)
   - Recommendation: Migrate `sql_generator.py` to `get_ai_provider(provider).complete(tools=[], max_rounds=1, temperature=0.0, model=model_light, ...)`. The Anthropic provider's `complete()` body (moved from `_loop_anthropic`) handles `max_rounds=1` naturally (exits after first `end_turn`). OpenAI handles `finish_reason=="stop"` with no tool calls. This is clean.

---

## Environment Availability

Step 2.6: SKIPPED — phase is purely code/config changes within the existing Python backend. No new external dependencies. All required packages (`anthropic`, `openai`, `httpx`) already installed in backend venv.

---

## Sources

### Primary (HIGH confidence)
- `backend/app/processing/ai/llm_loop.py` — read entire file; all dispatch sites verified
- `backend/app/processing/ai/service.py:224-253, 383-414, 655-834` — read tool constants and dispatch sites
- `backend/app/processing/ai/tools.py` — read entire file; CHAT_TOOLS_OPENAI is algorithmic derivation
- `backend/app/processing/ai/streaming.py:22-31, 270-560` — read import block and streaming dispatch
- `backend/app/processing/ai/sql_generator.py:330-415` — read dispatch and helpers
- `backend/app/processing/ai/metadata_service.py:240-323` — read structured-output dispatch
- `backend/app/platform/extensions/protocols.py` — read entire file; Protocol template confirmed
- `backend/app/platform/extensions/defaults.py` — read entire file; deferred-import pattern confirmed
- `backend/app/platform/extensions/__init__.py` — read entire file; accessor pattern confirmed
- `backend/tests/test_extensions.py:1-65` — read; entry-points test pattern and registry reset confirmed
- `backend/tests/test_layering.py:420-491` — read; architecture-guard test pattern confirmed
- `backend/tests/test_ai_chat.py`, `test_chat_streaming.py`, `test_chat_narrative.py` — read; test mocking confirmed at router boundary
- `frontend/src/components/maps/MapCreateDialog.tsx:78-112` — read; SSE event shape confirmed
- `frontend/src/api/maps.ts:190-248` — read; SSE parsing logic confirmed
- `226-CONTEXT.md` — complete (all decisions D-01..D-28)
- `.planning/ROADMAP.md §Phase 226` — SC#1..SC#5 confirmed

### Tertiary (LOW confidence — assumed)
- `@runtime_checkable` Protocol behavior in Python 3.11+ for async methods [ASSUMED]
- `ANTHROPIC_TOOLS` / `OPENAI_TOOLS` equivalence in `service.py` [ASSUMED — structural match visible but not programmatically diffed]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `@runtime_checkable` with async methods performs attribute-existence check only (not async/signature check) in Python 3.11+ | Architecture Patterns | Low — behavior has been stable since Python 3.8; test coverage via `isinstance(DefaultAnthropicProvider(), AIProviderExtension)` assertion |
| A2 | `ANTHROPIC_TOOLS` and `OPENAI_TOOLS` in `service.py` are structurally equivalent (the wrapping is the same as `tools.py`) | Tool-Format Conversion | Medium — if they diverge, the D-08 migration breaks the OpenAI tool call path; verify programmatically before deleting `OPENAI_TOOLS` |

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all imports and patterns verified by reading actual source files
- Architecture: HIGH — all extension scaffold files read; patterns confirmed
- Pitfalls: HIGH — dispatch site count verified programmatically; test mock patterns confirmed by reading test files
- SC#3 hit count: HIGH — Python script confirmed 10 hits across 5 files

**Research date:** 2026-05-01
**Valid until:** Indefinite (source files are stable; no external API versioning concern)
