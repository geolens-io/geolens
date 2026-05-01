# Phase 226: ai-provider-extension-protocol - Context

**Gathered:** 2026-05-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the hardcoded `if/elif provider == "anthropic"/"openai_compatible"` dispatch in `processing/ai/` with a name-keyed `AIProviderExtension` Protocol registered through the same `geolens.extensions` entry-point mechanism as `BillingExtension` (Phase 223), `AuditSink` (Phase 222), `IdentityExtension` (Phase 214), and `ProcessingPort` (Phase 225). After this phase:

- `backend/app/platform/extensions/protocols.py` gains `AIProviderExtension` (and any small supporting structural Protocols needed for tool/result shapes). The Protocol exposes `complete(...)` and `stream(...)` per ROADMAP §226 SC#1 — both methods take `messages` + `tools` per the audit-26-b §2 Seam #7 wording, plus the additional kwargs the existing tool-loop body needs (`tool_executor`, `action_collector`, `system_prompt`, `model`, `max_rounds`, `max_tokens`, `temperature`, `base_url`).
- `backend/app/platform/extensions/defaults.py` adds **two** community defaults — `DefaultAnthropicProvider` and `DefaultOpenAICompatibleProvider` (one per current provider name). Their `complete()` bodies are the existing `_loop_anthropic` (`processing/ai/llm_loop.py:179-277`) and `_loop_openai` (`:280-404`) bodies, MOVED in (deferred imports preserved per Phase 225 D-09 / D-19 discipline). Their `stream()` defaults raise `NotImplementedError` — no production caller invokes `stream()` today (the `stream_generate_map` "semi-streaming" path at `service.py:723-806` wraps a non-stream `run_tool_loop` and yields milestone events, not LLM tokens).
- `backend/app/platform/extensions/__init__.py` adds the typed accessor `get_ai_provider(name: str) -> AIProviderExtension`. The registry slot is `_extensions["ai_providers"]` — a `dict[str, AIProviderExtension]` (NEW shape; differs from Phase 222's list-shape `audit_sinks` and Phase 214/225's single-slot accessors because the AI dispatch fans out by name, not by iteration). Default seed populates `{"anthropic": DefaultAnthropicProvider(), "openai_compatible": DefaultOpenAICompatibleProvider()}` via per-key `setdefault` (D-04 below) so any registration order — overlay-first or default-first — produces the correct combined registry.
- The `if provider == "anthropic"` branch at `processing/ai/llm_loop.py:117,132` is replaced. After migration `run_tool_loop()` shrinks to: `provider_ext = get_ai_provider(provider); return await provider_ext.complete(...)`. Optionally the function can be deleted entirely and the 4 callers (`service.py:669, 770`, `chat_service.py:944` plus any tests) call `provider_ext.complete()` directly. Either way, zero `if .*provider *==` branches remain in `processing/ai/`.
- The `if provider == "openai_compatible":` branch at `llm_loop.py:160-161` (base_url resolution) is also dispatch-table-converted: each provider class exposes a `resolve_runtime_config(db)` (or equivalently named) method that returns the provider-specific runtime config (base_url, default model, etc.). `resolve_provider(db)` calls `get_ai_provider(name).resolve_runtime_config(db)` instead of branching on the name string. This is required to satisfy SC#3's binding regex `if .*provider *== *['\"](anthropic|openai_compatible)` — which DOES match line 160 today.
- The `if provider == "anthropic":` branch at `service.py:394` (the `_retry_parse_map_spec` helper, which makes a single tool-less LLM call to repair malformed JSON) is also migrated: it calls `provider_ext.complete(messages=[{user msg}], tools=[], max_rounds=1, ...)` — the wide-Protocol shape covers the no-tools single-round case naturally. No second Protocol method needed.
- A new `@pytest.mark.architecture` test in `backend/tests/test_layering.py` named `test_no_hardcoded_ai_provider_branches` enforces that `^.*if\s+.*provider\s*==\s*['\"](anthropic|openai_compatible)` returns zero hits under `backend/app/processing/ai/` (and conservatively under `backend/app/processing/` as a whole — the audit's regex doesn't bound the path narrower). Mirrors Phase 222's `test_no_log_action_calls_outside_audit_service` (`test_layering.py:421-491`) and Phase 224's `test_no_external_imports_of_dataset_domain_submodules` (`:333-420`) patterns: `git grep` + pathspec exclusion (excludes `backend/tests/` and excludes the new defaults file because dispatch tables in `defaults.py` will mention provider names as dict KEYS, not as `if ==` comparisons), `_has_git_metadata()` skip guard, `_has_pathspec_magic()` git-version check, fail with offending lines.
- A new test file `backend/tests/test_ai_provider_extension.py` registers a fake `TestProvider` via the `app.platform.extensions.entry_points` mock pattern (precedent: `backend/tests/test_extensions.py:32, 61, 84, 146, 166, 171`), exercises the extension load path, then calls `get_ai_provider("test_provider").complete(...)` and asserts the fake is dispatched. Satisfies ROADMAP §226 SC#5.
- The full backend test suite (2050/2050 baseline post-Phase-225 close) stays green with the two community providers wired in — zero functional regressions because the migrated bodies are byte-identical to today's `_loop_anthropic` / `_loop_openai`.
- All AI integration tests pass unchanged (SC#4 — "Existing AI integration tests pass unchanged with the default extension wired in"). Includes `backend/tests/test_ai_chat.py`, `test_ai_router.py`, `test_ai_service.py`, etc.
- New providers (Bedrock, Vertex, Azure, vLLM) are NOT shipped by Phase 226 — only the seam. The audit's "5–8d" estimate was for the seam; new provider impls land in overlays (`geolens-enterprise/ai-providers/`) or follow-up community phases. Phase 226 ships **zero** behavior change for community users (default registry has the same two providers as today; their bodies are the same code).

**Allowlist — sites that legitimately keep `if provider ==` style code:**
- **`backend/app/platform/extensions/defaults.py`** — the two `DefaultAnthropicProvider` and `DefaultOpenAICompatibleProvider` classes legitimately reference provider names (e.g., as their internal identifier or in log statements) but do NOT branch on the name internally — each class IS a single provider. The architecture-guard regex `if .*provider *==` does not match `class DefaultAnthropicProvider:` or `provider="anthropic"` log lines. No allowlist needed unless dispatch defaults end up using a `name == self.name` check (planner avoids).
- **`backend/app/platform/extensions/__init__.py`** — `get_ai_provider(name: str)` may have an `if name not in providers:` raise. The regex matches on the literal token `provider` but `name` ≠ `provider`. No conflict.
- **`backend/tests/`** — test fixtures may construct dispatch tables for verification. Pathspec excludes `backend/tests/`.
- **`processing/ai/llm_loop.py:resolve_provider`** — returns `provider, model, runtime_config` tuple; no branching on the string after the migration. Clean.

**In scope:** add `AIProviderExtension` Protocol to `platform/extensions/protocols.py`; add `DefaultAnthropicProvider` + `DefaultOpenAICompatibleProvider` to `defaults.py` (move `_loop_anthropic` and `_loop_openai` bodies into them); add `get_ai_provider(name)` accessor to `__init__.py`; migrate `run_tool_loop()` (and `_retry_parse_map_spec`) to dispatch via the accessor; migrate `resolve_provider()` base_url branch into per-provider `resolve_runtime_config()`; add the architecture-guard test; add the entry-points test seam; verify 2050/2050 + ruff + alembic.

**Out of scope:** new provider implementations (Bedrock / Vertex / Azure / vLLM) — those land in overlays or future community phases; true LLM-token streaming (`stream()` declared but defaults raise `NotImplementedError`); changes to the `processing/ai/tools.py` module-level `TOOLS_ANTHROPIC` / `TOOLS_OPENAI` / `CHAT_TOOLS_ANTHROPIC` / `CHAT_TOOLS_OPENAI` constants beyond what tool-format normalization (D-08) requires; any `WorkflowExtension` (Phase 999.9 backlog); any `PermissionExtension` (Phase 999.8); any change to `processing/ai/service.py:stream_generate_map`'s milestone-yielding semi-streaming pattern (its `phase: thinking → ready` event shape is a contract with the frontend SSE consumer); any frontend change; any Alembic migration; any change to `LLM_PROVIDER` / `LLM_MODEL` / `OPENAI_BASE_URL` PersistentConfig keys; any change to the `DefaultProcessingPort` (Phase 225 territory).

</domain>

<decisions>
## Implementation Decisions

### Protocol surface

- **D-01 — Wide Protocol (full tool-loop semantics).** `AIProviderExtension.complete(...)` runs the **entire** tool-calling loop for that provider, not a single LLM round. Bodies of today's `_loop_anthropic` / `_loop_openai` move INTO the provider classes; `run_tool_loop()` shrinks to a thin dispatch facade or is deleted entirely. Reason: the audit (§7 P1) frames the goal as "consolidate hardcoded `if/elif provider ==` dispatch"; the dispatch sites at `llm_loop.py:117,132` route to whole-loop helpers, so the natural seam IS the whole loop. A narrow per-LLM-call shape (`complete()` does ONE round; orchestration stays in `llm_loop.py`) would still need `provider.parse_tool_calls(response)`, `provider.format_tool_result(result)`, etc. — adding 4-5 more Protocol methods that all branch on provider-specific response shape. Wide is cleaner and matches the audit's intent.

- **D-02 — Method signature for `complete()`** mirrors today's `run_tool_loop()` minus the `provider` arg. Concretely:
  ```python
  async def complete(
      self,
      *,
      model: str,
      system_prompt: str,
      user_message: str,
      tools: list[dict],
      tool_executor: ToolExecutor,
      action_collector: ActionCollector | None = None,
      history: list[dict] | None = None,
      max_rounds: int = MAX_TOOL_ROUNDS,
      max_tokens: int = 4096,
      base_url: str | None = None,
      temperature: float = 0.5,
  ) -> ToolLoopResult: ...
  ```
  All kwargs are keyword-only (matches today's `run_tool_loop` shape). `ToolLoopResult` is a forward-referenced typing alias (D-09).

- **D-03 — `stream()` declared but defaults raise NotImplementedError.** SC#1 mandates the Protocol declare both `complete()` and `stream()`. No production code path today actually streams LLM tokens — `service.py:stream_generate_map` is "semi-streaming" via milestone events around a non-stream `complete()`. Both default community providers raise `NotImplementedError("AnthropicProvider.stream() not implemented in community edition; use complete()")` (or similar) — this preserves the Protocol shape, signals the deferred status loudly to anyone trying to use it, and leaves overlays free to implement true streaming via the SDKs' native streaming APIs (Anthropic `client.messages.stream(...)`, OpenAI `client.chat.completions.create(stream=True)`). Method signature mirrors `complete()` exactly; return type left as `ToolLoopResult` for now (or `AsyncIterator[ToolLoopChunk]` if a future phase wants real streaming — planner picks; deferred behavior is the same either way).

- **D-04 — Name-keyed dispatch table at `_extensions["ai_providers"]`.** Registry slot is `dict[str, AIProviderExtension]`, NOT a list (Phase 222/223 shape) and NOT a single slot (Phase 214/225 shape). Reason: AI providers fan out **by name** at request time — `LLM_PROVIDER` PersistentConfig stores `"anthropic"` or `"openai_compatible"`, and `run_tool_loop()` looks up THE provider matching that name. List-shape would force linear scan + name-attribute matching; single-slot can't hold multiple providers. The dict gives O(1) lookup by name and matches the audit's "dispatch table" wording verbatim. New shape; sets a precedent for future "fan-out by name" extensions (e.g., Phase 999.13 connector adapters).

- **D-05 — Per-key `setdefault` seeding makes registration order safe.** The accessor body is:
  ```python
  def get_ai_provider(name: str) -> AIProviderExtension:
      providers = _extensions.setdefault("ai_providers", {})
      providers.setdefault("anthropic", DefaultAnthropicProvider())
      providers.setdefault("openai_compatible", DefaultOpenAICompatibleProvider())
      if name not in providers:
          raise ValueError(f"Unknown LLM provider: {name}")
      return providers[name]
  ```
  Per-key `setdefault` never overwrites overlay-registered providers. If an overlay registered `providers["anthropic"] = TierAwareAnthropicProvider()` BEFORE the first `get_ai_provider()` call (during `load_extensions()`), the seeding step skips that key and the overlay wins. If an overlay registers `providers["bedrock"] = BedrockProvider()`, both defaults + the new provider coexist. Order-safe regardless of overlay registration timing. Mirrors the spirit of Phase 222 D-09 ("setdefault + append" for list-shape) adapted to dict-shape.

  Alternative: seed defaults inside `load_extensions()` BEFORE the overlay loop (`_extensions["ai_providers"] = {default_a, default_o}; for ep in eps: ep(_extensions)`). This works too but ties seeding to startup; the lazy approach in the accessor body is more robust against test contexts that don't run `load_extensions()`. Planner picks; both are acceptable. Default recommendation: lazy in accessor (above).

- **D-06 — `ValueError` on unknown provider preserves today's behavior.** Today's `llm_loop.py:149` raises `ValueError(f"Unknown LLM provider: {provider}")`. The accessor preserves this exception type so existing tests that catch `ValueError` from `run_tool_loop()` keep passing. NOT `KeyError` (would change the exception type), NOT silent default-fallback (would mask config typos).

- **D-07 — `@runtime_checkable` on `AIProviderExtension`** (mirrors `IdentityProtocol`, `AuditSink`, `BillingExtension`). Negligible cost; enables `isinstance(provider_ext, AIProviderExtension)` for future overlay debugging.

### Tool format normalization

- **D-08 — Unified canonical tool format = Anthropic-shape.** The Protocol's `complete(tools=...)` takes a `list[dict]` in **Anthropic format** (`{name, description, input_schema}` — JSON Schema inside `input_schema`). Each provider class converts internally if its native format differs:
  - `DefaultAnthropicProvider.complete()` uses `tools` directly (it's already anthropic-shape).
  - `DefaultOpenAICompatibleProvider.complete()` wraps each tool to `{type: "function", function: {name, description, parameters: input_schema}}` before calling `client.chat.completions.create(tools=...)`.
  - The `add_tool_cache_control()` Anthropic-specific helper at `llm_loop.py:63-69` moves into `DefaultAnthropicProvider` (Anthropic-only feature).
  - The current `tools_anthropic` / `tools_openai` parameter pair on `run_tool_loop` collapses to a SINGLE `tools` parameter on `complete()`. Callers stop building both formats; they pass the canonical anthropic shape and the provider converts on the way in.
  - `processing/ai/tools.py` module-level constants `TOOLS_ANTHROPIC` (the canonical) stay; `TOOLS_OPENAI` (and the `CHAT_TOOLS_OPENAI` mirror) can be removed if no external caller references them — planner re-greps. Removal is allowed under D-25 (incidental dead-code cleanup) but not required.

- **D-09 — `ToolLoopResult` and `ToolExecutor`/`ActionCollector` type aliases stay in `llm_loop.py`.** They're forward-referenced from `protocols.py` via `TYPE_CHECKING` (mirrors the `AuditEvent` pattern at `protocols.py:18-19`). This creates a typing-only edge `platform.extensions.protocols → app.processing.ai.llm_loop`, NOT a runtime edge — `protocols.py` does not import `llm_loop` at module load. Acceptable per Phase 222's precedent. Alternative: move `ToolLoopResult` into `protocols.py` itself (small dataclass) — both work; default is the forward-ref to minimize move-churn.

  Trade-off note: if `llm_loop.py` is fully gutted (all bodies moved into provider classes), `ToolLoopResult` may end up living in a near-empty file. If the planner finds `llm_loop.py` reduces to <50 LOC of just type aliases + `resolve_provider()` + `build_history_messages()`, consider folding it into `protocols.py` or `service.py`. Default: keep `llm_loop.py` for now — its `resolve_provider()` and `build_history_messages()` helpers don't fit `protocols.py`'s structural-typing-only discipline.

### Provider-specific runtime config

- **D-10 — Each provider class owns its own runtime-config resolution.** Adds a Protocol method:
  ```python
  async def resolve_runtime_config(self, db) -> dict[str, object]:
      """Return provider-specific runtime config: base_url, default_model, etc."""
      ...
  ```
  - `DefaultAnthropicProvider.resolve_runtime_config()` returns `{"base_url": None, "default_model": "claude-..."}` (or whatever today's `LLM_MODEL` falls back to for anthropic — planner re-checks `app.core.persistent_config:LLM_MODEL`).
  - `DefaultOpenAICompatibleProvider.resolve_runtime_config()` reads `OPENAI_BASE_URL.get(db)` and returns `{"base_url": <url>, "default_model": "gpt-..."}`.
  - `resolve_provider(db)` becomes:
    ```python
    async def resolve_provider(db) -> tuple[str, str, dict]:
        name = await LLM_PROVIDER.get(db)
        provider_ext = get_ai_provider(name)
        runtime_config = await provider_ext.resolve_runtime_config(db)
        model = await LLM_MODEL.get(db) or runtime_config.get("default_model")
        return name, model, runtime_config  # callers extract base_url from runtime_config["base_url"]
    ```
  - Eliminates the `if provider == "openai_compatible":` branch at `llm_loop.py:160`. Without this change the architecture-guard regex (D-11) would catch line 160.
  - **API contract change consideration:** `resolve_provider`'s return tuple changes from `(provider, model, base_url)` to `(provider, model, runtime_config)` (or stays `(provider, model, base_url)` with `base_url = runtime_config.get("base_url")`). Callers (`service.py:660, 741`, `chat_service.py:934`) update accordingly. Tuple-return back-compat is NOT required — closed-set consumer list, mechanical update.

  **Alternative considered:** keep the if/elif branch in `resolve_provider` and add an exception to the architecture-guard regex. Rejected — the regex is binding per SC#3 ("returns zero hits after the migration"); allowing one exception undermines the seam quality argument.

### Architecture guard

- **D-11 — One new test in `backend/tests/test_layering.py` named `test_no_hardcoded_ai_provider_branches`.** Mirrors the Phase 222 `test_no_log_action_calls_outside_audit_service` pattern (`:421-491`) verbatim:
  - `_has_git_metadata()` skip guard
  - `_has_pathspec_magic()` git-version check
  - `git grep -n -E '<regex>' -- backend/app/processing/ ':!backend/tests/' ':!backend/app/platform/extensions/defaults.py'`
  - **Regex:** `if\s+.*provider\s*==\s*['\"](anthropic|openai_compatible)` (matches SC#3 binding wording with whitespace tolerance)
  - **Pathspec:** scoped to `backend/app/processing/` (the audit-cited directory). The audit's regex doesn't constrain the path narrower; SC#3 says `processing/ai/` but `processing/` is the safer wider scope. Planner picks; default = `backend/app/processing/`.
  - **Exclusions:** `backend/tests/` (test fixtures may legitimately stub provider names), `backend/app/platform/extensions/defaults.py` (defensively excluded in case the provider classes themselves end up needing an internal check — usually they won't, but the exclusion future-proofs).
  - On failure: `pytest.fail(f"Hardcoded AI provider dispatch found in processing/. Replace with get_ai_provider(name).complete(...). Offending lines:\n{result.stdout}")`
  - Strict zero-hit, no allowlist (mirrors Phase 225 D-23). Codebase scan confirms today's only hits are at the migration sites — no legitimate side-effect branch on provider name exists in `processing/`.

- **D-12 — Test marker `@pytest.mark.architecture`** — already registered in `backend/pyproject.toml`. No new marker.

- **D-13 — Update `test_layering.py` module docstring** to credit Phase 226 alongside 212/213/214/222/223/224/225. Same pattern as Phase 225 D-25.

- **D-14 — Negative-control verification** — temporarily reintroduce `if provider == "anthropic":` in (e.g.) `processing/ai/service.py`, run the test, confirm it fails with the offending line. Revert. Verifies the guard works (mirrors Phase 225 D-26 / SC#3 "intentionally adding a forbidden import causes the test to fail in CI").

### Test seam (entry_points dispatch)

- **D-15 — `backend/tests/test_ai_provider_extension.py` (NEW) registers a fake provider via the `entry_points` mock pattern.** Reuses the established `backend/tests/test_extensions.py` shape (precedent at `:32, 61, 84, 146, 166, 171`):
  ```python
  def test_overlay_provider_is_dispatched():
      class TestProvider:
          async def complete(self, **kwargs):
              return ToolLoopResult(text="from-test-provider", actions=[])
          async def stream(self, **kwargs):
              raise NotImplementedError
          async def resolve_runtime_config(self, db):
              return {"base_url": None, "default_model": "test-model-1"}

      def register(registry):
          providers = registry.setdefault("ai_providers", {})
          providers["test_provider"] = TestProvider()

      mock_ep = MagicMock()
      mock_ep.name = "geolens.ai-providers.test"
      mock_ep.load.return_value = register

      with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
          load_extensions()
          provider_ext = get_ai_provider("test_provider")
          result = await provider_ext.complete(...)
          assert result.text == "from-test-provider"
  ```
  - Exercises the FULL chain: `entry_points()` discovery → `register_extensions(registry)` callback → `get_ai_provider(name)` → `provider.complete(...)`. Satisfies SC#5 verbatim ("A test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file").
  - **No real package install required** — `patch()`-ing `entry_points` is the established codebase pattern. Cleaner than installing a tiny test package per pytest run.
  - **Cleanup:** the test resets `_extensions` (or uses an isolated registry fixture) to avoid leaking the test provider into other tests. Phase 222/223 fixtures already address this — planner reuses.

- **D-16 — Default-providers smoke test** — separate test in the same file: `test_default_providers_registered` calls `get_ai_provider("anthropic")` / `get_ai_provider("openai_compatible")` after a fresh `load_extensions()` (no overlay) and asserts the returned classes are `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider`. Verifies SC#2 ("`DefaultAIProviderExtension` resolves the two community providers"). NOTE: Phase 226 ships TWO defaults (one per name), not a single `DefaultAIProviderExtension` — see D-17 below for the rationale and naming.

### Naming & class shape

- **D-17 — Two community defaults, not one.** ROADMAP §226 SC#2 says "**`DefaultAIProviderExtension`** resolves the two community providers (Anthropic native, OpenAI-compatible) via the same accessor pattern as `get_billing_extension()` / `get_audit_sink()`." The phrasing is ambiguous: it could mean "ONE class that handles BOTH names" or "the default registry RESOLVES (i.e., contains) both."
  - **Decision:** ship TWO classes — `DefaultAnthropicProvider` and `DefaultOpenAICompatibleProvider` — registered under their respective name keys. Reasons:
    1. **Single-responsibility.** Each class owns ONE provider's full implementation (move of `_loop_anthropic` and `_loop_openai` respectively). A single `DefaultAIProviderExtension` class would internally dispatch `if self.name == "anthropic"` — re-introducing the very branch this phase removes.
    2. **Extensibility symmetry.** Overlays add NEW provider classes (one per provider, e.g., `BedrockProvider`); having two defaults that look like the eventual overlay shape sets a clean precedent.
    3. **Test isolation.** SC#5's test seam (D-15) registers a fake `TestProvider` — a single class per provider name. The community defaults match this shape.
  - SC#2's "DefaultAIProviderExtension" phrasing is interpreted as the SC writer not yet committing to single-vs-multi class decomposition; Phase 226 lands the multi-class shape. The accuracy gate (SC#2) is satisfied because both names ("anthropic", "openai_compatible") resolve to a default class via `get_ai_provider(name)`.

- **D-18 — Class names: `DefaultAnthropicProvider`, `DefaultOpenAICompatibleProvider`.** Drops the "Extension" suffix because `AIProviderExtension` is the Protocol; the concrete classes are providers (mirrors `DefaultAuditSink` / `DefaultBillingExtension` naming — the suffix matches the Protocol's role: Sink, Extension, Provider). If the planner prefers `DefaultAnthropicAIProvider` for unambiguity, that's fine; same shape, different label. Default: shorter form.

### Wire-in — caller migration

- **D-19 — Four call sites migrate to dispatch via the accessor:**
  - `processing/ai/llm_loop.py:run_tool_loop` (lines 117/132 dispatch) → either delete `run_tool_loop` and update callers to call `provider_ext.complete()` directly, OR keep as a thin facade `provider_ext = get_ai_provider(provider); return await provider_ext.complete(...)`. Default: delete + update callers (cleaner; mirrors Phase 223's pattern of removing the `core/marketplace.py` module entirely rather than keeping a shim). Planner picks based on diff churn.
  - `processing/ai/service.py:_retry_parse_map_spec` (line 394) → `provider_ext = get_ai_provider(provider); result = await provider_ext.complete(messages=[user_msg], tools=[], max_rounds=1, ...); ...`. Tool-less single-round case naturally fits the wide Protocol.
  - `processing/ai/service.py:generate_map_from_prompt` (line 660+) — calls `run_tool_loop(provider=provider, ...)` today. Update to `provider_ext = get_ai_provider(provider); result = await provider_ext.complete(...)`.
  - `processing/ai/service.py:stream_generate_map` (line 741+) — same migration as above. Note: the surrounding "milestone-yielding semi-streaming" pattern is preserved (frontend SSE contract); only the inner LLM call swaps.
  - `processing/ai/chat_service.py:chat_edit_map` (line 944+) — same migration.

- **D-20 — `tools_anthropic`/`tools_openai` argument collapse to single `tools`.** Tied to D-08. Callers stop passing both formats; they pass the canonical Anthropic-shape and the provider converts on the way in. The 4 callers above each have a `tools_anthropic=..., tools_openai=...` line today; both lines collapse to `tools=...` (the canonical, which is `TOOLS_ANTHROPIC` / `CHAT_TOOLS_ANTHROPIC` from `tools.py`). The OpenAI-format constants (`TOOLS_OPENAI`, `CHAT_TOOLS_OPENAI`) become unreferenced; planner removes them as incidental dead-code cleanup if no other consumer references them (D-25).

- **D-21 — `resolve_provider` return-tuple shape change.** Tied to D-10. Today returns `(provider, model, base_url)`. After Phase 226: returns `(provider, model, runtime_config)` where `runtime_config` is a dict containing `base_url` (OpenAI-compatible only) plus future provider-specific fields. Callers (`service.py:660, 741`, `chat_service.py:934`) update their tuple-unpacking. Closed-set; no back-compat shim. Alternative: keep `(provider, model, base_url)` and pass `runtime_config` as a separate side channel — rejected because more invasive (4 callers vs. 4 callers, same mechanical change).

### Test seam additional coverage

- **D-22 — `FakeProcessingPort` pattern from Phase 225 NOT replicated** (no analogue here — `AIProviderExtension` is name-keyed dispatch; a fake provider can be registered through the entry_points mock, NOT via a constructor parameter). The test in D-15 IS the seam test. Single high-signal test plus D-16's smoke test.

- **D-23 — Existing AI integration tests stay unchanged.** SC#4 binding ("Existing AI integration tests pass unchanged with the default extension wired in"). Test files: `backend/tests/test_ai_chat.py`, `backend/tests/test_ai_router.py`, `backend/tests/test_ai_service.py`, `backend/tests/test_ai_metadata_service.py`, `backend/tests/test_ai_*_chat_service.py`, `backend/tests/test_ai_streaming.py`, `backend/tests/test_chat_*.py`. The 2050/2050 baseline includes these; planner re-runs after migration to confirm zero delta. If any test mocks `_loop_anthropic` / `_loop_openai` directly (post-Phase-225 baseline check: `grep -rn '_loop_anthropic\|_loop_openai' backend/tests/`), the planner refactors those mocks to mock at the `AIProviderExtension.complete()` boundary instead. Likely zero or near-zero hits — the test suite generally mocks `run_tool_loop` itself or the SDK clients (Anthropic/OpenAI), not the internal helpers.

### Verification gates

- **D-24 — Acceptance gate = 2050/2050 backend tests + ruff + alembic check + new architecture-guard test + entry_points test.** Per STATE.md (post-Phase-225 close), the baseline is 2050/2050 passing (Phase 225 added 14 tests: 2036 → 2050). Phase 226 adds at least 2 new tests (D-15, D-16) and possibly a few more for FakeProvider edge cases — final count likely 2052+/2052+. No regression tolerated in the existing 2050.

- **D-25 — Incidental dead-code cleanup is allowed but not required.** If `TOOLS_OPENAI` / `CHAT_TOOLS_OPENAI` constants in `processing/ai/tools.py` become unreferenced after the unified-tool-format migration (D-08), the planner may delete them. Same for the `_cached_anthropic_client` / `_cached_openai_clients` module-level caches at `llm_loop.py:28-29` — if `DefaultAnthropicProvider` / `DefaultOpenAICompatibleProvider` move them inside the class (instance attributes) the module-level singletons disappear. Default: move into provider class as instance attribute or class-level cache. Planner picks; both work.

- **D-26 — No frontend involvement.** `processing/ai/router.py` HTTP contracts are unchanged (the extension shows up only inside the service layer, below the HTTP boundary). `make openapi-check` continues to pass without regenerating `backend/openapi.json`. Frontend SSE consumer of `stream_generate_map` (the `ChatStreamingClient` in `frontend/src/api/...`) sees identical event shapes.

- **D-27 — No Alembic migration.** No DB schema change. Per Phase 225 D-29 / Phase 222 D-12 pattern, post-refactor verification step `cd backend && uv run alembic check` confirms "no new operations." A non-empty diff means the refactor accidentally touched a model and the planner stops.

- **D-28 — Phase 229 verification dependency.** Phase 229 (post-impl audit) reruns `/oc-audit` and confirms Seam Quality grade movement B+ → A− (hold) and Coupling Health B → B+ (hold). Phase 226's contribution: the last 🔴 in audit-26-b §2 Seam #7 (AI provider registry) closes. Phase 226 alone is not sufficient to flip the overall Boundary Integrity grade — Phase 225's cycle inversion is the second lever.

### Claude's Discretion

- **Commit decomposition** — likely 3 atomic commits mirroring Phases 222/223/225: (1) introduce `AIProviderExtension` Protocol in `protocols.py` + `DefaultAnthropicProvider` + `DefaultOpenAICompatibleProvider` in `defaults.py` (move `_loop_anthropic` and `_loop_openai` bodies in) + `get_ai_provider(name)` accessor in `__init__.py` — pure additive at first (the old `run_tool_loop` continues to work in parallel). (2) Migrate the 4 call sites (`run_tool_loop` callers + `_retry_parse_map_spec` + `resolve_provider` runtime-config branch) to dispatch via `get_ai_provider`. Delete `run_tool_loop` and the now-obsolete `_loop_anthropic` / `_loop_openai` definitions (now duplicated). Tool-format unified to canonical Anthropic shape; OpenAI-format constants removed if unreferenced. Update tuple-unpacking at `resolve_provider` callers. (3) Add `test_no_hardcoded_ai_provider_branches` to `test_layering.py` + update module docstring; add `tests/test_ai_provider_extension.py` (entry_points dispatch test + smoke test); negative-control verification of the architecture guard. Planner may collapse, split, or reorder based on dependency ordering and file-size budgets. Whichever decomposition is chosen, every commit must keep the test suite green; the architecture-guard test (commit 3) MUST land last because it fails until the dispatch branches are gone.

- **Module docstring wording for the new Protocol class** — keep the spirit of `protocols.py:43-59` (`AuditSink` docstring) and `:62-83` (`BillingExtension` docstring): credit Phase 226 (and AIEXT-01..05), summarize the dispatch-table shape (D-04), point to the entry-points pattern, note the rejection of the if/elif provider dispatch (D-11). Planner picks exact wording.

- **Method naming** — Protocol method names track the audit's wording (`complete`, `stream`). If the planner finds ambiguity with the existing `client.messages.create` / `client.chat.completions.create` SDK methods, no rename — `complete` is the higher-level abstraction (returns `ToolLoopResult`, runs full loop), distinct from any single-SDK-call name.

- **Whether `run_tool_loop()` is preserved as a thin facade or deleted entirely** — default is delete + update callers (cleaner; matches Phase 223's "remove `core/marketplace.py` entirely" pattern). If the planner sees ergonomic value in a `run_tool_loop(provider, ...)` shorthand that wraps `get_ai_provider(provider).complete(...)`, keep it. Both work.

- **Whether `_cached_anthropic_client` / `_cached_openai_clients` caches move into the provider classes or stay module-level** — default is move into provider class (cleaner encapsulation, gets garbage-collected with the provider instance). Module-level module-singleton caches can stay if the planner finds the move adds risk (e.g., the cache is shared across multiple provider instances today, hypothetically). Planner verifies.

- **Whether the `stream()` Protocol method declares an `AsyncIterator[...]` return type or `ToolLoopResult`** — both work. Default: `ToolLoopResult` (mirrors `complete()` shape, defers the streaming-types question entirely; a future phase can introduce `ToolLoopChunk` and update the Protocol). Planner picks based on stylistic preference.

- **Order of tests in `test_ai_provider_extension.py`** — default: 1) `test_default_providers_registered`, 2) `test_overlay_provider_is_dispatched`, 3) `test_unknown_provider_raises_value_error` (added defensively for D-06). Planner can add `test_default_anthropic_complete_flow` and `test_default_openai_complete_flow` if they cover behavior the existing AI integration tests don't already cover; default = skip (existing tests cover this end-to-end).

- **Whether `resolve_runtime_config` is part of the Protocol or just a community-default convenience method** — default: part of the Protocol. Reason: overlays will need their own runtime config (Bedrock reads AWS creds, Vertex reads GCP creds, Azure reads endpoint+key). Making it a Protocol method forces overlays to think about config explicitly. Cost: one extra method on the Protocol surface. Acceptable.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec

- `docs-internal/audits/oc-separation-audit-20260430-b.md` §2 Seam #7 (🔴 — "AI provider registry — Hardcoded `if/elif` on provider string at `processing/ai/llm_loop.py:117,132` and `service.py:387-398`. Only `'anthropic'` and `'openai_compatible'` recognized. Module-global cached clients. Need `AIProviderExtension` Protocol with `complete()`/`stream()` methods + dispatch table.") — the source spec for Phase 226's existence.
- `docs-internal/audits/oc-separation-audit-20260430-b.md` §7 P1 #2 ("Define `AIProviderExtension` Protocol; consolidate hardcoded `if/elif provider == "anthropic"` dispatch") — binding directive. 5–8d estimate is for the seam only; new provider impls land later.
- `.planning/REQUIREMENTS.md` §AIEXT-01..05 — the five requirements this phase closes.
- `.planning/ROADMAP.md` §Phase 226 — goal statement + 5 success criteria. SC#1 binds Protocol shape (`complete(messages, tools)`, `stream(messages, tools)`). SC#3's grep is binding (`grep -RE "if .*provider *== *['\"](anthropic|openai_compatible)" backend/app/processing/ai/` returns zero hits) — the architecture-guard test (D-11) must enforce. SC#5's "test overlay registered via `importlib.metadata` entry_points is dispatched correctly" is binding (D-15).

### Project / state

- `.planning/PROJECT.md` — milestone overview; v13.4 audit-grade target Seam Quality B+ → **A−** is delivered by Phase 226 (last 🔴 closes).
- `.planning/STATE.md` — confirms 2050/2050 backend test baseline (post-Phase-225 close, 2026-05-01) and v13.4 phase queue.
- `.planning/MILESTONES.md` — milestone closure history.

### Phase 222 AuditSink — the canonical default-impl pattern

- `backend/app/platform/extensions/protocols.py:43-59` (`AuditSink` Protocol) — docstring template Phase 226's `AIProviderExtension` mirrors. Notes the `TYPE_CHECKING` forward reference for `AuditEvent` (line 18-19) — Phase 226 uses the same pattern for `ToolLoopResult` (D-09).
- `backend/app/platform/extensions/defaults.py:46-76` (`DefaultAuditSink`) — the deferred-import pattern. Each method does `from app.modules.X import Y` inside the function body. Phase 226's `Default*Provider.complete()` mirrors this verbatim (deferred import for the Anthropic/OpenAI SDK clients, deferred config reads).
- `backend/tests/test_layering.py:421-491` (`test_no_log_action_calls_outside_audit_service`) — the architecture-guard test pattern Phase 226's `test_no_hardcoded_ai_provider_branches` mirrors verbatim. Same pathspec-exclusion shape, same `_has_git_metadata` / `_has_pathspec_magic` skip guards. **Read end-to-end.**

### Phase 223 BillingExtension — the entry-point dispatch precedent

- `backend/app/platform/extensions/protocols.py:62-83` (`BillingExtension` Protocol) — the docstring shape. Phase 226 follows the same template (credit phase, summarize seam, note the registration discipline, document the dispatch loop guarantee).
- `backend/app/platform/extensions/__init__.py:163-194` (`get_billing_extensions()`) — list-shape accessor. Phase 226 deliberately does NOT use list-shape (D-04 picks dict-shape). Read once to understand the precedent; the new dict-shape derives the per-key `setdefault` discipline (D-05) directly from Phase 223's "setdefault + append."

### Phase 225 ProcessingPort — the most recent precedent (single-slot accessor)

- `.planning/phases/225-processing-port-protocol-cycle-inversion/225-CONTEXT.md` — full context document; D-01 (comprehensive surface), D-09 (deferred-import default), D-10 (Protocol home — Phase 226 differs because the audit explicitly puts AIProviderExtension in `platform/extensions/protocols.py` rather than `core/`), D-12 (single-slot accessor — Phase 226 differs because dispatch fans out by name), D-22 (architecture-guard test pattern), D-26/D-27 (acceptance gate). **Read for the most recent codified extension-Protocol pattern; deviate only where Phase 226's audit-driven shape (Protocol in `platform/extensions/`, dict-keyed by name) requires.**
- `backend/app/platform/extensions/__init__.py:197-218` (`get_processing_port()`) — single-slot accessor pattern. Phase 226's `get_ai_provider(name)` differs (dict-keyed by name) but inherits the docstring template, the `_extensions` lookup pattern, and the lazy-default-fallback discipline. Read once; adapt to dict shape per D-04/D-05.

### Phase 214 IdentityProtocol — the originating pattern

- `backend/app/core/identity.py` — the canonical Protocol-in-core pattern. Phase 226 keeps the Protocol in `platform/extensions/protocols.py` (per ROADMAP SC#1) rather than in `core/` — the AIProviderExtension is more akin to `AuditSink`/`BillingExtension` (overlay-extensible behavior, lives in `platform/extensions/`) than to `IdentityProtocol`/`ProcessingPort` (consumer surface, lives in `core/`). Read once for context; the location decision is set by SC#1.

### Code (current state — what Phase 226 migrates)

- `backend/app/processing/ai/llm_loop.py:117,132` — current dispatch site #1 (the `if provider == "anthropic"`/`elif provider == "openai_compatible"` branch). Lines 117-149.
- `backend/app/processing/ai/llm_loop.py:160-161` — current dispatch site #2 (the `if provider == "openai_compatible":` base_url branch in `resolve_provider()`). Phase 226 migrates per D-10.
- `backend/app/processing/ai/llm_loop.py:179-277` (`_loop_anthropic`) — body moves into `DefaultAnthropicProvider.complete()`.
- `backend/app/processing/ai/llm_loop.py:280-404` (`_loop_openai`) — body moves into `DefaultOpenAICompatibleProvider.complete()`.
- `backend/app/processing/ai/llm_loop.py:32-51` (`get_anthropic_client`, `get_openai_client`) — module-level client singletons. D-25 / "Claude's Discretion" — planner moves into provider classes or keeps module-level. Default: move.
- `backend/app/processing/ai/llm_loop.py:63-69` (`add_tool_cache_control`) — Anthropic-only helper. Moves into `DefaultAnthropicProvider`.
- `backend/app/processing/ai/llm_loop.py:72-79` (`ToolLoopResult` dataclass) — stays per D-09; forward-referenced from `protocols.py`.
- `backend/app/processing/ai/llm_loop.py:54-56` (`ToolExecutor`, `ActionCollector` type aliases) — stay per D-09.
- `backend/app/processing/ai/service.py:383-413` (`_retry_parse_map_spec`) — current dispatch site #3 (the `if provider == "anthropic":` branch at line 394). Phase 226 migrates to `provider_ext.complete(tools=[], max_rounds=1, ...)`.
- `backend/app/processing/ai/service.py:660-715, 723-806` (`generate_map_from_prompt`, `stream_generate_map`) — call `run_tool_loop` today; migrate to `provider_ext.complete()`.
- `backend/app/processing/ai/chat_service.py:934-980` (`chat_edit_map`) — calls `run_tool_loop` today; migrate to `provider_ext.complete()`.
- `backend/app/processing/ai/tools.py` — `TOOLS_ANTHROPIC` / `TOOLS_OPENAI` / `CHAT_TOOLS_ANTHROPIC` / `CHAT_TOOLS_OPENAI` constants. Per D-08/D-20, the OpenAI-format constants become unreferenced; planner verifies and removes if appropriate.
- `backend/app/core/persistent_config.py` — `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_BASE_URL` keys. Read by `resolve_provider()` and (post-migration) by `Default*Provider.resolve_runtime_config()`. **Unchanged** by Phase 226.
- `backend/app/core/config.py:settings.anthropic_api_key, settings.openai_api_key` — env-var-backed keys read by the SDK client constructors. **Unchanged** by Phase 226.

### Code (extension scaffold to extend)

- `backend/app/platform/extensions/__init__.py` — Phase 226 adds `get_ai_provider(name)` accessor here (D-04/D-05), modeled on `get_processing_port()` (lines 197-218) but adapted to dict-shape.
- `backend/app/platform/extensions/protocols.py` — Phase 226 adds `AIProviderExtension` Protocol here (D-01..D-03/D-07). The file's docstring (lines 1-9) explains the typing discipline; Phase 226's `TYPE_CHECKING` forward-ref for `ToolLoopResult` (D-09) follows the same pattern as `AuditEvent` (lines 18-19).
- `backend/app/platform/extensions/defaults.py` — Phase 226 adds `DefaultAnthropicProvider` and `DefaultOpenAICompatibleProvider` here (D-17/D-18). Body migration of `_loop_anthropic` / `_loop_openai` follows Phase 225's `DefaultProcessingPort.create_dataset` etc. pattern (deferred imports preserved).
- `backend/app/platform/extensions/guards.py` — `require_enterprise()`. Not modified by Phase 226 (the AI providers are community-aware; default impls just delegate to existing SDK clients).
- `backend/app/api/main.py:125-135` — application startup wiring: `load_extensions()` → `init_edition()` → mount extension routers. Phase 226's `get_ai_provider()` is consulted lazily on every call (per D-05), not at startup; no startup-wiring change needed.

### Code (architecture-guard test)

- `backend/tests/test_layering.py:421-491` (`test_no_log_action_calls_outside_audit_service`, Phase 222) — the test pattern Phase 226's `test_no_hardcoded_ai_provider_branches` mirrors verbatim. Same `_has_git_metadata()`, `_has_pathspec_magic()`, `subprocess.run(["git", "grep", ...])` shape.
- `backend/tests/test_layering.py:333-420` (`test_no_external_imports_of_dataset_domain_submodules`, Phase 224) — alternative pattern showing allowlist-aware structure. Phase 226 uses the simpler strict-zero-hit form per D-11.
- `backend/tests/test_layering.py:1-38` (module docstring) — Phase 226 updates to credit 226 alongside 212/213/214/222/223/224/225.
- `backend/pyproject.toml` — registers the `architecture` pytest marker. Already done by Phase 212-03; no change.

### Code (entry-points test pattern)

- `backend/tests/test_extensions.py:32, 61, 84, 146, 166, 171` — the established `patch("app.platform.extensions.entry_points", return_value=[mock_ep])` pattern. Phase 226's `tests/test_ai_provider_extension.py` (D-15) reuses this verbatim.
- `backend/tests/conftest.py:114-117` — `entry_points(group="geolens.migrations")` discovery in conftest. Different group; informational only.

### Code (existing AI tests that must stay green per SC#4)

- `backend/tests/test_ai_chat.py`, `test_ai_router.py`, `test_ai_service.py`, `test_ai_metadata_service.py`, `test_ai_streaming.py`, `test_chat_*.py`, `test_ai_*_chat_service.py` — the closed set of AI integration tests. Phase 226 must not break any of them. Planner re-runs after each commit to confirm zero delta from the 2050/2050 baseline.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`backend/app/platform/extensions/protocols.py:43-59` (Phase 222 `AuditSink`)** and **`:62-83` (Phase 223 `BillingExtension`)** — Protocol-class docstring template. Phase 226's `AIProviderExtension` follows the same shape: brief contract statement, registration mechanism note, dispatch loop note (or "raises ValueError on unknown name"), method signatures.
- **`backend/app/platform/extensions/defaults.py:46-76` (Phase 222 `DefaultAuditSink`)** — deferred-import pattern. Phase 226's `Default*Provider.complete()` mirrors verbatim — defer the SDK client import, defer the PersistentConfig read, defer anything that crosses a domain boundary.
- **`backend/app/platform/extensions/__init__.py:43-63` (`load_extensions()`)** — `importlib.metadata.entry_points("geolens.extensions")` registration loop. Phase 226 reuses unchanged. Overlay providers register under `_extensions["ai_providers"]` (D-04).
- **`backend/app/platform/extensions/__init__.py:197-218` (`get_processing_port()`)** — single-slot typed accessor. Phase 226's `get_ai_provider(name)` adapts to dict-keyed shape (D-04/D-05). Same lazy-default-fallback discipline.
- **`backend/tests/test_layering.py:_has_git_metadata()` + `_has_pathspec_magic()` + `_git_grep` helpers** (Phase 212/213/214/222/223/224/225) — Phase 226's new test reuses verbatim. No new helpers needed.
- **`@pytest.mark.architecture` marker** registered in `backend/pyproject.toml` — Phase 226 reuses; no new marker.
- **`backend/tests/test_extensions.py` `patch("app.platform.extensions.entry_points")` pattern** — Phase 226's entry-points dispatch test (D-15) reuses verbatim.
- **`processing/ai/llm_loop.py:32-51` (`get_anthropic_client`, `get_openai_client`)** — module-level SDK client singletons. Phase 226 moves into provider classes (D-25 default). Cache logic preserved.
- **`processing/ai/llm_loop.py:63-69` (`add_tool_cache_control`)** — Anthropic-specific helper that adds `cache_control: {type: "ephemeral"}` to the last tool definition. Moves into `DefaultAnthropicProvider`.
- **`processing/ai/llm_loop.py:165-176` (`build_history_messages`)** — provider-agnostic helper that filters history to user/assistant roles. Stays in `llm_loop.py` (or moves to `service.py`); both providers call it.

### Established Patterns

- **Closed-set caller migration via `git grep`** (Phase 212/213/214/222/225) — Phase 226 inherits. The 4-call-site list (D-19) is enumerated by `git grep -nE 'run_tool_loop\(' backend/app/processing/ai/`. Migrate all hits; do NOT introduce `import-linter` or any architecture-DSL dependency.
- **Hard-cutover migration with NO compat shim** (Phase 212 D-04, Phase 213 D-04, Phase 214 D-10, Phase 222 D-04, Phase 225 D-20) — closed-set codebase, ruff + full pytest is the safety net, architecture-guard test as the regression seal. Phase 226 inherits.
- **Deferred-import discipline** — `platform/extensions/defaults.py` does deferred `from app.modules.X import Y` inside method bodies, never at module load. Phase 226 follows: each `Default*Provider.complete()` defers the SDK import (`from anthropic import AsyncAnthropic`) inside the method body if needed. Actually — the SDK clients are already top-level imports today (`from anthropic import AsyncAnthropic` at `llm_loop.py:14`); these are external libraries, not `app.modules.*`, so no deferred-import discipline applies. Provider classes can import them at module load.
- **`@runtime_checkable` on every Protocol** — `IdentityProtocol`, `RoleProtocol`, `IdentityExtension`, `AuditSink`, `BillingExtension`. Phase 226's `AIProviderExtension` inherits.
- **`from __future__ import annotations`** at the top of every Protocol-bearing module — `protocols.py:11`. Already in place; no change.
- **Per-key `setdefault` for default seeding** — adapted from Phase 222 D-09's "setdefault + append" list-shape discipline to dict-shape (D-05). Order-safe for any overlay registration timing.

### Integration Points

- **`backend/app/api/main.py` startup chain**: `load_extensions()` → `init_edition()` → mount routers. Phase 226's `get_ai_provider(name)` is consulted lazily per-request (per D-05), NOT at startup. No startup-wiring change. The `_loaded` flag at `platform/extensions/__init__.py:40` is set after `load_extensions()` runs; if `get_ai_provider()` is called before `load_extensions()` (shouldn't happen — startup runs `load_extensions()` first), the lazy-seed discipline (D-05) ensures the default providers are still available.
- **AI feature service layer** (`processing/ai/service.py`, `chat_service.py`, `metadata_service.py`): the four files ROADMAP §226 implicitly calls out via the dispatch sites at `llm_loop.py:117,132` + `service.py:387-398`. The `port: ProcessingPort` parameter (Phase 225 D-15) is unaffected by Phase 226. Provider dispatch happens INSIDE these functions via `get_ai_provider(provider).complete(...)`; the port is orthogonal.
- **Procrastinate worker process**: AI features run inside the FastAPI request lifecycle, not the Procrastinate worker. Phase 226 has zero worker-process impact.
- **Frontend SSE consumer** (`stream_generate_map`'s `phase: thinking → ready` event shape): unchanged — the milestone-yielding pattern wraps `provider_ext.complete()` instead of `run_tool_loop()`, but the event shape is identical.
- **OpenAPI snapshot (`backend/openapi.json`)**: unaffected. `AIProviderExtension` is a Python-typing concept; FastAPI generates OpenAPI from request/response Pydantic schemas. Routes that depend on AI service functions emit the same OpenAPI as before.
- **Tests** (`backend/tests/test_ai_*.py`): existing AI integration tests stay green per SC#4. Planner re-runs after each commit.
- **CLAUDE.md "FastAPI trailing slashes" / "OGC routes" rules**: not affected — Phase 226 is below the route layer.

### Risk surfaces

- **Tool-format conversion correctness** (D-08). The OpenAI tool format wraps Anthropic's `{name, description, input_schema}` as `{type: "function", function: {name, description, parameters: input_schema}}`. The conversion is mechanical but test-dependent — the `parameters: input_schema` mapping must preserve the exact JSON Schema. Mitigation: existing AI tests exercise tool-call flows end-to-end; if the conversion is wrong, tool calls fail with parameter-validation errors. The `tools_anthropic` / `tools_openai` constants in `tools.py` today are HAND-MAINTAINED parallel definitions; the migration replaces hand-maintained `tools_openai` with a function call. If the live `TOOLS_OPENAI` definitions don't exactly match the algorithmic conversion of `TOOLS_ANTHROPIC`, the existing OpenAI test path breaks. Planner spot-checks: `assert convert_tools_to_openai(TOOLS_ANTHROPIC) == TOOLS_OPENAI` BEFORE deleting `TOOLS_OPENAI`.
- **`_retry_parse_map_spec` empty-tools edge case** (D-19). The wide-Protocol `complete()` accepts `tools=[]` — both Anthropic and OpenAI SDKs tolerate empty tool lists. But if the existing path uses different defaults (e.g., `max_tokens=1024` for retry vs `4096` for the full loop), the planner threads those through. The `complete()` signature defaults (`max_tokens: int = 4096`) are overridable per call.
- **`ToolLoopResult` typing edge** (D-09). The forward-reference from `protocols.py` to `app.processing.ai.llm_loop.ToolLoopResult` works under `TYPE_CHECKING`, but if a runtime annotation evaluation is needed (e.g., `pydantic` model with the type annotation), the typing-only edge becomes a runtime edge and the import order matters. Phase 226's Protocol method signatures use `from __future__ import annotations` (already in place) so annotations are strings at runtime. No runtime evaluation needed.
- **`stream()` NotImplementedError discoverability** (D-03). If any frontend or test path inadvertently calls `provider_ext.stream(...)` instead of `complete()`, the error surfaces as `NotImplementedError`. Mitigation: Phase 226 verifies via `git grep -n 'provider_ext\.stream\|.stream(' backend/app/processing/ai/` that no caller invokes `stream()` post-migration. The semi-streaming `service.py:stream_generate_map` calls `complete()`, NOT `stream()`. (Trap: if a planner mistakes the SDK's native `client.messages.stream(...)` for the Protocol's `stream()` method, the wires get crossed. Reading both names carefully matters.)
- **`resolve_runtime_config` config drift** (D-10). The Anthropic provider's runtime config is `{"base_url": None, "default_model": "..."}`; the OpenAI-compatible provider's is `{"base_url": <openai_base_url>, "default_model": "..."}`. If a future provider needs different runtime keys (e.g., Bedrock needs `region`, `aws_credentials`), the dict shape extends naturally. Callers extract via `runtime_config.get(key)` — defensive.
- **Module-level client cache vs instance cache** (D-25). If the planner moves `_cached_anthropic_client` from module-level to `DefaultAnthropicProvider`'s instance-level (or class-level) cache, the cache lifetime changes. Today the cache lives for the FastAPI process lifetime (module loaded once). If the provider is registered as a singleton in `_extensions["ai_providers"]["anthropic"]`, the instance is also process-scoped — same lifetime. Move is safe.
- **Test mocking layer** — if any existing test mocks `_loop_anthropic` directly (`with patch("app.processing.ai.llm_loop._loop_anthropic")`), the mock target disappears after the migration. Planner re-greps `backend/tests/` for `_loop_anthropic` / `_loop_openai` and refactors mocks to target `AIProviderExtension.complete()` or the SDK clients. From the codebase scout, this is most likely a small-or-zero count — test suite typically mocks at the SDK client boundary (Anthropic/OpenAI client mocks) or at `run_tool_loop` directly.
- **Phase 225 overlap (zero, but worth noting)** — Phase 225 (ProcessingPort) shipped on 2026-05-01 and touches `processing/ai/{service, router, chat_service, metadata_service}.py`. Phase 226 also touches these files but DIFFERENT lines (provider dispatch vs catalog imports). The architecture-guard test from Phase 225 (`test_no_processing_imports_catalog`) stays green during Phase 226's edits because Phase 226 doesn't add any `from app.modules.catalog` imports. Verified by spot-grep before each commit.

</code_context>

<specifics>
## Specific Ideas

- **Audit phrasing chosen, in their words:** Audit-26-b §2 Seam #7: "Need `AIProviderExtension` Protocol with `complete()`/`stream()` methods + dispatch table. Adding Bedrock/Vertex/Azure/vLLM today touches 5+ files." Phase 226 implements verbatim with name-keyed dict-shape registry (D-04) and wide Protocol (D-01).
- **ROADMAP §226 SC#3's binding regex `if .*provider *== *['\"](anthropic|openai_compatible)`** — the architecture-guard test (D-11) enforces this. Codebase scan today shows hits at `llm_loop.py:117, 132, 160-161` and `service.py:394`. After migration: zero hits.
- **ROADMAP §226 SC#5's binding "test overlay registered via `importlib.metadata` entry_points"** — the test (D-15) registers a fake `TestProvider` via the existing `patch("app.platform.extensions.entry_points")` pattern, exercising `load_extensions()` → `register_extensions(registry)` → `get_ai_provider("test_provider")` → `provider_ext.complete()`.
- **"Ships only the seam — new provider implementations land in overlays or follow-up milestones"** (ROADMAP §226 goal). Phase 226 ships ZERO new providers — only the two community defaults (which encapsulate today's behavior byte-for-byte) plus the seam. Bedrock / Vertex / Azure / vLLM are explicitly out-of-scope.
- **Phase 226 plug-in shape will look like:** an enterprise overlay (e.g., `geolens-enterprise/ai-providers/`) registers via `[project.entry-points."geolens.extensions"]` calling `register_extensions(registry)`. The registry slot is `_extensions["ai_providers"]` (dict-keyed by name); each overlay provider is added under its name (`registry.setdefault("ai_providers", {})["bedrock"] = BedrockProvider()`).
- **Phase 229 audit-grade target:** the post-implementation audit gate for v13.4 verifies Seam Quality grade movement B+ → **A−**. Phase 226's contribution: closing the last 🔴 in audit-26-b §2 Seam #7. Phase 229 reruns `/oc-audit` and confirms grade movement.
- **Phase 226 dependency on Phase 225:** "Both phases touch `processing/ai/`; serializing avoids merge churn and keeps the architecture-guard signal clean while the seam is being cut" (ROADMAP §226). Phase 225 has SHIPPED (2026-05-01); Phase 226 starts on the post-225 baseline (2050/2050 tests).

</specifics>

<deferred>
## Deferred Ideas

- **New provider implementations (Bedrock / Vertex / Azure / vLLM)** — Phase 226 ships only the seam, not the providers. Bedrock and Vertex likely land in `geolens-enterprise/ai-providers/` (cloud-tier feature); Azure OpenAI and vLLM may be community-tier follow-ups. Each provider is its own focused phase (~3-5d).
- **True LLM-token streaming** — D-03 declares `stream()` on the Protocol but defaults raise `NotImplementedError`. A future phase implements true streaming via Anthropic `messages.stream` and OpenAI `chat.completions.create(stream=True)`, propagates `ToolLoopChunk`-style events through `service.py:stream_generate_map`, and updates the frontend SSE consumer to render token-by-token output. Larger UX impact; treated as its own phase.
- **`WorkflowExtension` Protocol** (Phase 999.9 backlog, P1) — `ALLOWED_TRANSITIONS` hardcoded dict at `catalog/datasets/api/router_data.py:210-215`. Same audit, separate seam.
- **`PermissionExtension` Protocol** (Phase 999.8 backlog, P1) — refactor `apply_visibility_filter`, `check_dataset_access`, `get_user_roles` out of `ProcessingPort` into a dedicated `PermissionExtension`. Phase 225 left these on the Port intentionally; Phase 999.8 owns the next move.
- **`Connector` ORM + `ConnectorAdapter` Protocol** (Phase 999.13, P2) — Enterprise-tier persistent connector registry with credential vault. Different domain.
- **`geolens-schemas` package extraction** (Phase 999.16, P2) — separate phase. Phase 226 doesn't touch the cross-cutting schema package question.
- **`geolens.yaml` declarative manifest** (Phase 999.12, P1) — separate ~2-week phase. Phase 226 unrelated.
- **Pyright/mypy CI gate** — Phase 214 D-25 deferred this; Phase 225 D-26 inherited; Phase 226 inherits. The project does not run pyright or mypy in CI. ruff + pytest is the gate.
- **Catalog → processing direction inversion** — explicitly NOT in scope (Phase 225 territory; Phase 225 also did NOT invert this direction; the catalog → processing direction is the legitimate top-down driver shape).
- **Replacing `Default*Extension` no-op shims with `None` returns** — Phase 222 D-04 / Phase 223 D-07 / Phase 225 D-09 / Phase 226 D-17 all keep the Default class shape (vs. returning `None`). Phase 226 inherits; both default providers are real classes with real methods. No change to the discipline.
- **Tightening the architecture-guard regex to be ANY `if .*provider *==` (not just the two community names)** — Phase 226 scopes to the SC#3 binding regex. If a future overlay registers a provider whose name happens to be string-checked elsewhere (unlikely; the dispatch table is the access point), the broader guard catches it. Default: SC#3-bound regex; broader regex is a P3 follow-up.
- **`_cached_anthropic_client` / `_cached_openai_clients` cache lifetime** — D-25 default moves into provider class. If a future phase wants per-tenant provider instances (e.g., different API keys per tenant for Cloud tier), the cache might need rethinking. Phase 999.6 (tenant scoping) territory.
- **Provider configuration UX (admin UI)** — currently provider name + model + base_url are set via PersistentConfig (admin settings UI). Adding new providers via overlays should integrate with the admin UI's provider dropdown (which is hardcoded today to `"anthropic"` / `"openai_compatible"`). Phase 226 doesn't touch the admin UI; if a future phase wants overlays to declare admin-UI metadata (display name, config schema), that's a `ProviderManifest`-style extension. Out of Phase 226's seam-only scope.

</deferred>

---

*Phase: 226-ai-provider-extension-protocol*
*Context gathered: 2026-05-01*
