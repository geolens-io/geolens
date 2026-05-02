# Phase 231: embedding-provider-extension-protocol - Context

**Gathered:** 2026-05-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the last direct provider-SDK import in `backend/app/processing/` by introducing an `EmbeddingProviderExtension` Protocol at `backend/app/platform/extensions/protocols.py` and routing the embeddings API call at `backend/app/processing/embeddings/helpers.py:8` (`from openai import OpenAI`) through the extension registry. Ships a single `DefaultOpenAIEmbeddingProvider` that preserves current OpenAI-compatible behavior byte-for-byte; overlays can later register Bedrock / Vertex / Azure / Cohere via `importlib.metadata` entry_points without touching core. The existing architecture guard (`test_no_module_level_provider_sdk_imports_in_processing_ai`, added 2026-05-02 commit `259ebc72`) is renamed/expanded to cover both `processing/ai/` and `processing/embeddings/` and the embeddings carve-out is removed from its docstring.

This is the embeddings sibling of Phase 226 (AIProviderExtension) — same patterns, smaller footprint (one default provider, two callers, no streaming concept, no tool-format conversion).

</domain>

<decisions>
## Implementation Decisions

### Protocol surface

- **D-01 — Single batch method `embed()` on the Protocol.** Per ROADMAP §231 SC#1 binding wording (`embed(texts: list[str], model: str) -> list[list[float]]`). Batch shape from day one — even though both current call sites in `processing/embeddings/service.py` (`generate_embedding`, line 70) pass exactly one string and unwrap `response.data[0].embedding`, the OpenAI embeddings API is natively batch (`client.embeddings.create(input=...)` accepts `str | list[str]`), and Bedrock/Vertex/Cohere overlays will all want batching. Locking the singular shape `embed(text: str, ...)` would force every overlay to add per-string round trips.

- **D-02 — Method signature for `embed()`** mirrors today's `client.embeddings.create(...)` call shape, accepting all per-call parameters from the existing flow:
  ```python
  async def embed(
      self,
      *,
      texts: list[str],
      model: str,
      dimensions: int | None = None,
      base_url: str | None = None,
      timeout: float | None = None,
  ) -> list[list[float]]: ...
  ```
  - `dimensions: int | None = None` — required for `probe_embedding_dimensions` (sends `None` to discover the model's natural dim size); `generate_embedding` always passes a concrete int. SC#1's roadmap signature `embed(texts, model)` is not exhaustive — the `dimensions` parameter is implementation-required.
  - `base_url: str | None = None` — caller passes the resolved value from `EMBEDDING_BASE_URL → OPENAI_BASE_URL → "https://api.openai.com/v1"` chain; provider falls back to `settings.openai_base_url` if unset (matches `build_openai_client` behavior).
  - `timeout: float | None = None` — `generate_embedding` uses 130s timeout, `probe_embedding_dimensions` uses 30s. Both pass through; provider falls back to today's `httpx.Timeout(60.0, connect=10.0)` SDK-level default if unset.
  - All kwargs keyword-only (matches Phase 226 D-02 discipline).
  - **Return type:** `list[list[float]]` — caller unwraps `[0]` for the single-text case in `generate_embedding`; preserves today's `list[float]` return shape from `service.py`.

- **D-03 — No `stream()` on the Protocol.** Embeddings are batch-only; streaming a vector makes no sense (the API returns the entire vector at once). Phase 226 D-03 declared `stream()` because LLM completions naturally stream tokens; embeddings don't. Saves one Protocol method, prevents overlay confusion.

- **D-04 — `resolve_runtime_config(db)` Protocol method, mirrors Phase 226 D-10.** Each provider class owns its own runtime-config resolution:
  ```python
  async def resolve_runtime_config(self, db: AsyncSession) -> dict[str, object]:
      """Return provider-specific runtime config: base_url, default_model, default_dims."""
      ...
  ```
  - `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()` returns:
    ```python
    {
        "base_url": <EMBEDDING_BASE_URL.get(db) or OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1">,
        "default_model": <EMBEDDING_MODEL.get(db)>,
        "default_dims": <EMBEDDING_DIMS.get(db)>,
    }
    ```
  - Replaces the `resolve_embedding_base_url` helper in `helpers.py:90-97`. The fallback chain stays identical: `EMBEDDING_BASE_URL` (the dedicated embedding override) → `OPENAI_BASE_URL` (shared with the AI provider's openai_compatible default) → hardcoded `"https://api.openai.com/v1"`.
  - Callers (`generate_embedding`, `probe_embedding_dimensions`) call `provider_ext.resolve_runtime_config(db)` once at the top, then pass `runtime_config["base_url"]`, `runtime_config["default_model"]`, `runtime_config["default_dims"]` (or override) into `provider_ext.embed(...)`.
  - **Forward-compatible:** Bedrock overlays return `{"region": ..., "aws_credentials": ..., "default_model": ...}`; Vertex returns `{"project": ..., "location": ..., "default_model": ...}`. The dict shape extends naturally; callers extract via `runtime_config.get(key)`.

- **D-05 — `@runtime_checkable` on `EmbeddingProviderExtension`** (mirrors `AIProviderExtension`, `IdentityProtocol`, `AuditSink`, `BillingExtension`). Negligible cost; enables `isinstance(provider_ext, EmbeddingProviderExtension)` for future overlay debugging.

### Default provider — single class, not two

- **D-06 — One community default: `DefaultOpenAIEmbeddingProvider`.** Phase 226 ships TWO defaults (`DefaultAnthropicProvider`, `DefaultOpenAICompatibleProvider`) because the AI domain has two SDK-level integrations. The embeddings domain has ONE — Anthropic doesn't ship an embeddings API (see the `EmbeddingUnavailableError` message at `service.py:48-53` which explicitly calls this out). Single default class, single registry key, no naming collision concern.

- **D-07 — Registered under name key `"openai_compatible"`** — same key as the AI provider's `DefaultOpenAICompatibleProvider`. Reasons:
  1. **Shared semantics.** A deployment running Ollama or Together OAI-compatible proxy reuses the same `openai_compatible` provider name across both AI completion and embeddings — operators don't have to remember two different provider names for one underlying API.
  2. **No collision** — the AI registry lives at `_extensions["ai_providers"]["openai_compatible"]`; the embeddings registry lives at `_extensions["embedding_providers"]["openai_compatible"]`. Distinct dicts; the same name in each is allowed by design.
  3. **Forward symmetry** — Bedrock/Vertex overlays would register `_extensions["ai_providers"]["bedrock"]` and `_extensions["embedding_providers"]["bedrock"]` under the same name in both registries.

- **D-08 — Class name `DefaultOpenAIEmbeddingProvider`** — matches ROADMAP §231 SC#2 verbatim. Drops the "Extension" suffix (the Protocol is `EmbeddingProviderExtension`; concrete classes are providers — mirrors Phase 226 D-18 naming discipline).

### Registry shape and accessor

- **D-09 — Name-keyed dispatch table at `_extensions["embedding_providers"]`.** Registry slot is `dict[str, EmbeddingProviderExtension]` — same dict-shape as Phase 226 D-04 (NOT list-shape like `audit_sinks`/`billing_extensions`, NOT single-slot like `processing_port`/`identity`). Even though Phase 231 ships only one community default, the dispatch shape MUST match Phase 226 because:
  1. SC#2 binding wording: "follows the dict-shape pattern from `get_ai_provider(name)` (Phase 226)."
  2. Future overlays will add NEW provider names (Bedrock, Vertex) — same fan-out-by-name semantics as AI providers.
  3. Code symmetry — overlay authors learn ONE pattern and apply it to both AI and embeddings registries.

- **D-10 — `get_embedding_provider(name)` accessor** at `backend/app/platform/extensions/__init__.py`. Body mirrors `get_ai_provider` (D-05 of Phase 226) verbatim, adapted for one default:
  ```python
  def get_embedding_provider(name: str) -> "EmbeddingProviderExtension":
      providers = _extensions.setdefault("embedding_providers", {})
      providers.setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())
      if name not in providers:
          raise ValueError(f"Unknown embedding provider: {name}")
      return providers[name]
  ```
  Per-key `setdefault` discipline (Phase 226 D-05): never overwrites overlay registrations, order-safe regardless of whether the overlay registers BEFORE or AFTER the first `get_embedding_provider()` call.

- **D-11 — `ValueError` on unknown provider** preserves the symmetry with Phase 226 D-06 (also `ValueError`). No silent fallback to default; no `KeyError`. Message: `"Unknown embedding provider: {name}"`.

### Provider name resolution — implicit, not configured

- **D-12 — No `EMBEDDING_PROVIDER` PersistentConfig added.** Phase 226 reuses the existing `LLM_PROVIDER` PersistentConfig (`"anthropic"` or `"openai_compatible"`). The embeddings flow today has NO equivalent — `EMBEDDING_MODEL` / `EMBEDDING_DIMS` / `EMBEDDING_BASE_URL` exist but no provider-name key. Two options considered:
  - **(a) Hardcode `"openai_compatible"` in callers** (`provider_ext = get_embedding_provider("openai_compatible")`). Rejected as scope creep: adding a config key for a single-provider community is unnecessary; overlays that ship Bedrock/Vertex embeddings can introduce `EMBEDDING_PROVIDER` in their own phase if they need user-selectable embedding provider per-deployment.
  - **(b) Add `EMBEDDING_PROVIDER` PersistentConfig.** Rejected — the AI provider's `LLM_PROVIDER` was added when there were already TWO providers (anthropic, openai_compatible) needing user choice. Embeddings community ships ONE; there's no choice to expose.
  - **Decision:** option (a). Callers (`generate_embedding`, `probe_embedding_dimensions`) hardcode `"openai_compatible"` in `get_embedding_provider("openai_compatible")`. If a future enterprise overlay needs Bedrock embeddings, the overlay adds an `EMBEDDING_PROVIDER` PersistentConfig (or uses internal feature gating) and threads it through — out of scope for Phase 231.

### Architecture guard — rename + expand

- **D-13 — Rename `test_no_module_level_provider_sdk_imports_in_processing_ai` → `test_no_module_level_provider_sdk_imports_in_processing`.** Per ROADMAP §231 SC#4 binding wording. Single test rather than two — the existing test's regex `^(from|import) (anthropic|openai)( |$)` already covers both SDKs; only the pathspec changes from `backend/app/processing/ai/` to `backend/app/processing/`. The "Carve-out: `processing/embeddings/helpers.py` is excluded" docstring paragraph is REMOVED entirely (SC#4 binding).

- **D-14 — Pathspec broadens to `backend/app/processing/`.** Today's pathspec is `backend/app/processing/ai/`. After rename: `backend/app/processing/`. The `git grep` invocation still excludes `backend/tests/` (no exclusion is needed — test files don't sit under `processing/`). No new excludes required; the embeddings provider class lives in `app/platform/extensions/defaults.py`, outside `processing/`.

- **D-15 — Negative-control verification** — temporarily reintroduce `from openai import OpenAI` at the top of `backend/app/processing/embeddings/helpers.py`, run the renamed test, confirm it fails with the offending line surfaced. Revert. Mirrors Phase 226 D-14 verbatim.

- **D-16 — Update `test_layering.py` module docstring** to credit Phase 231 alongside 212/213/214/222/223/224/225/226. Same pattern as Phase 226 D-13.

- **D-17 — Test marker `@pytest.mark.architecture`** — already registered in `backend/pyproject.toml`. No new marker.

### Test seam (entry_points dispatch)

- **D-18 — `backend/tests/test_embedding_provider_extension.py` (NEW) registers a fake provider via the `entry_points` mock pattern.** Reuses the established `backend/tests/test_extensions.py` shape (Phase 222/226 precedent — `patch("app.platform.extensions.entry_points", return_value=[mock_ep])`):
  ```python
  @pytest.mark.asyncio
  async def test_overlay_embedding_provider_is_dispatched():
      class TestEmbeddingProvider:
          async def embed(self, *, texts, model, dimensions=None, base_url=None, timeout=None):
              return [[0.1] * (dimensions or 1536) for _ in texts]
          async def resolve_runtime_config(self, db):
              return {"base_url": None, "default_model": "test-emb-model", "default_dims": 1536}

      def register(registry):
          providers = registry.setdefault("embedding_providers", {})
          providers["test_embedding_provider"] = TestEmbeddingProvider()

      mock_ep = MagicMock()
      mock_ep.name = "geolens.embedding-providers.test"
      mock_ep.load.return_value = register

      with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
          load_extensions()
          provider_ext = get_embedding_provider("test_embedding_provider")
          vectors = await provider_ext.embed(texts=["hello"], model="test-emb-model", dimensions=1536)
          assert len(vectors) == 1
          assert len(vectors[0]) == 1536
  ```
  Exercises the FULL chain: `entry_points()` discovery → `register_extensions(registry)` callback → `get_embedding_provider(name)` → `provider.embed(...)`. Satisfies SC#5 verbatim.

- **D-19 — Default-provider smoke test** in the same file: `test_default_embedding_provider_registered` calls `get_embedding_provider("openai_compatible")` after a fresh `load_extensions()` (no overlay) and asserts the returned class is `DefaultOpenAIEmbeddingProvider`. Verifies SC#2.

- **D-20 — Unknown-provider test** added defensively (mirrors Phase 226 D-06 / D-15 implied coverage): `test_unknown_embedding_provider_raises_value_error` confirms `get_embedding_provider("nonexistent")` raises `ValueError`.

### Caller migration (helpers.py + service.py)

- **D-21 — Two call sites migrate to dispatch via the accessor:**
  - `backend/app/processing/embeddings/service.py:46-110` (`generate_embedding`) — replace lines 57 (`base_url = await resolve_embedding_base_url(session)`), 70 (`client = build_openai_client(base_url)`), and the `client.embeddings.create(...)` block (lines 78-87) with:
    ```python
    provider_ext = get_embedding_provider("openai_compatible")
    runtime_config = await provider_ext.resolve_runtime_config(session)
    model = await EMBEDDING_MODEL.get(session) or runtime_config.get("default_model")
    dims = await EMBEDDING_DIMS.get(session) or runtime_config.get("default_dims")
    base_url = runtime_config.get("base_url")
    # ... truncate ...
    vectors = await provider_ext.embed(
        texts=[text],
        model=model,
        dimensions=dims,
        base_url=base_url,
        timeout=130.0,
    )
    return vectors[0]
    ```
    The retry/backoff logic (lines 72-110) MOVES INTO `DefaultOpenAIEmbeddingProvider.embed()` — see D-22. Service callers no longer manage retries; the provider does. This matches Phase 226's pattern of moving the entire `_loop_anthropic`/`_loop_openai` body into the provider class.
  - `backend/app/processing/embeddings/service.py:113-172` (`probe_embedding_dimensions`) — same migration. The "send no `dimensions` parameter to discover natural size" semantics map to `provider_ext.embed(texts=["dimension probe"], model=model, dimensions=None, ...)`. The provider returns a list-of-lists; service unwraps `vectors[0]` and returns `len(vectors[0])`.

- **D-22 — Retry/backoff logic moves into `DefaultOpenAIEmbeddingProvider.embed()`.** Today's `service.py:72-110` retry loop (max 2 attempts, 2.0s backoff with jitter, 130s `asyncio.wait_for` timeout) is provider-implementation-specific — different overlays may have native SDK retry (Bedrock has built-in retries via boto3 config, Vertex has its own). Moving retry into the provider keeps service-level callers thin: they call `provider_ext.embed(...)` and trust the provider to handle transient failures. The provider raises `EmbeddingUnavailableError` (or a Protocol-defined exception) on terminal failure.
  - **Exception type:** `EmbeddingUnavailableError` lives in `service.py:27-28` today. Two options: (a) keep it in `service.py` and have the provider raise it (creates a `defaults.py → service.py` import edge); (b) move it to `protocols.py` (or a sibling exceptions module) so the Protocol contract owns the exception type. **Default: (b)** — move `EmbeddingUnavailableError` into a new `backend/app/platform/extensions/exceptions.py` (or alongside `EmbeddingProviderExtension` in `protocols.py`). Mirrors Phase 226's `ToolLoopExhaustedError` placement (lives near `ToolLoopResult` in `llm_loop.py`). Planner picks final location; both work.

- **D-23 — `helpers.py:8` (`from openai import OpenAI`) is REMOVED.** SC#3 binding. After the migration, `helpers.py` no longer imports the OpenAI SDK at module level — `_cached_openai_clients`, `build_openai_client`, and the `import httpx` (used only by `build_openai_client`'s timeout config) all move into `DefaultOpenAIEmbeddingProvider`. The remaining `helpers.py` content (`set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding`) is provider-agnostic and stays put.

- **D-24 — `resolve_embedding_base_url` (helpers.py:90-97) is REMOVED** — fold into `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()` (D-04). The function has only two callers, both inside `service.py` (lines 57, 128); both migrate to `provider_ext.resolve_runtime_config(session)["base_url"]`.

- **D-25 — `build_openai_client` (helpers.py:100-109) is REMOVED** — body moves into `DefaultOpenAIEmbeddingProvider` as a class-level cache method (mirrors Phase 226 `DefaultOpenAICompatibleProvider._clients` cache at `defaults.py:625`). Same `dict[str, AsyncOpenAI]` keyed by `base_url`. **Note:** Phase 231 uses `AsyncOpenAI` (not the sync `OpenAI` client used today via `asyncio.to_thread`) — the wrapper is unnecessary when calling the SDK from `async def`. Migration: today's `await asyncio.to_thread(client.embeddings.create, ...)` becomes `await client.embeddings.create(...)` (async-native). Same SDK package; different client class. This eliminates the `asyncio.to_thread` overhead per embed call. Phase 226's `DefaultOpenAICompatibleProvider` already uses `AsyncOpenAI` (`defaults.py:646`); same pattern.

- **D-26 — `_cached_openai_clients` (helpers.py:19) module-level cache moves into `DefaultOpenAIEmbeddingProvider._clients` class-level cache.** Lifetime is identical (process-scoped, since the provider instance is registered as a singleton in `_extensions["embedding_providers"]["openai_compatible"]`). Mirrors Phase 226's `DefaultOpenAICompatibleProvider._clients` at `defaults.py:625` verbatim.

### Test mock surface migration

- **D-27 — `tests/test_embedding_service.py` mocks migrate from `service.build_openai_client` / `service.resolve_embedding_base_url` to provider-boundary mocks.** The four existing tests (`test_generate_embedding_returns_float_vector`, `_raises_when_no_openai_key`, `_uses_persistent_config`, `_truncates_long_input`, `_dimension_mismatch`) currently `patch("app.processing.embeddings.service.build_openai_client")`. Post-migration, `build_openai_client` no longer exists in `service.py` (D-25). Two refactor options:
  - **(a) Patch the registry accessor:** `patch("app.processing.embeddings.service.get_embedding_provider")` returning a mock provider whose `embed()` returns the fake vector and whose `resolve_runtime_config()` returns the fake config. Simpler test setup; one patch instead of two.
  - **(b) Use the entry_points pattern:** register a `TestProvider` via `patch("app.platform.extensions.entry_points")` like D-18. More end-to-end but heavier per-test.
  - **Decision: (a)** for the existing 5 tests — they're testing service-layer logic (truncation, error messages, PersistentConfig reads, retry handoff), not the registry mechanism. The registry mechanism is covered by the new `test_embedding_provider_extension.py` (D-18). Mocking at the service-level accessor keeps existing tests fast and focused.
  - **Migration template:**
    ```python
    mock_provider = MagicMock()
    mock_provider.embed = AsyncMock(return_value=[fake_vector])
    mock_provider.resolve_runtime_config = AsyncMock(return_value={
        "base_url": None, "default_model": "text-embedding-3-small", "default_dims": 1536,
    })
    with patch(
        "app.processing.embeddings.service.get_embedding_provider",
        return_value=mock_provider,
    ):
        result = await generate_embedding("test text", mock_session)
    ```
  - Planner picks per-test; both (a) and (b) work.

- **D-28 — `tests/test_embedding_pipeline.py` and `tests/test_hybrid_search.py` patches at `service.generate_embedding` / `search.service.generate_embedding` are UNAFFECTED.** They mock the higher-level service function, not the SDK boundary. SC#5 is satisfied because `generate_embedding`'s signature and return shape are unchanged (`async def generate_embedding(text: str, session: AsyncSession) -> list[float]`).

### Verification gates

- **D-29 — Acceptance gate = full backend test suite (current baseline + ≥3 new tests from D-18/D-19/D-20) + ruff + alembic check + the renamed/expanded architecture-guard test.** Per STATE.md, post-Phase-228 baseline is ~2050+/2050+ passing (Phase 226 added the `test_ai_provider_extension.py` tests; Phase 231 adds `test_embedding_provider_extension.py` with at least 3 tests). The renamed architecture guard `test_no_module_level_provider_sdk_imports_in_processing` MUST stay green throughout the migration sequence (commit-by-commit) because as soon as the test pathspec is widened, the existing `helpers.py:8` import would trip it. Sequencing constraint: rename the test in the SAME commit that removes the offending import (or rename AFTER the import is removed). Default: rename last (mirrors Phase 226 D-11's "architecture-guard test as the regression seal" pattern).

- **D-30 — Existing embeddings tests stay green per SC#5.** Test files: `backend/tests/test_embedding_service.py`, `backend/tests/test_embedding_pipeline.py`, `backend/tests/test_embeddings_*.py`, `backend/tests/test_hybrid_search.py` (the embedding-using subset), `backend/tests/test_semantic_search.py`. Mock-target updates per D-27/D-28 are migration-mechanical, not behavior changes. If any test fails post-migration with a real behavior regression, the planner stops.

- **D-31 — No frontend involvement.** `processing/embeddings/router.py` doesn't exist (embeddings are an internal service, not an HTTP surface). The semantic-search HTTP routes at `modules/catalog/search/router.py` consume `generate_embedding(text)` — its signature is unchanged. `make openapi-check` continues to pass without regenerating `backend/openapi.json`. Frontend search/related-items features see identical API responses.

- **D-32 — No Alembic migration.** No DB schema change. Per Phase 226 D-27 / Phase 225 D-29 pattern, post-refactor verification step `cd backend && uv run alembic check` confirms "no new operations." A non-empty diff means the refactor accidentally touched a model and the planner stops.

- **D-33 — Phase 229 verification dependency.** Phase 229 (post-impl audit for v13.4) reruns `/oc-audit` and confirms Seam Quality grade movement to A− (last 🔴 in audit-26-b §2 closes when Phase 226 + Phase 231 ship together). Phase 231's contribution: closing the embeddings-side residual flagged in `oc-separation-audit-20260502.md` §5 / §7 P1 (action item #4).

### Claude's Discretion

- **Commit decomposition** — likely 3 atomic commits mirroring Phase 226: (1) introduce `EmbeddingProviderExtension` Protocol in `protocols.py` + `DefaultOpenAIEmbeddingProvider` in `defaults.py` (move `build_openai_client` body + retry loop in) + `get_embedding_provider(name)` accessor in `__init__.py` — pure additive at first (the old `build_openai_client` continues to work in parallel). (2) Migrate the 2 call sites (`generate_embedding`, `probe_embedding_dimensions`) to dispatch via `get_embedding_provider`. Delete `build_openai_client`, `resolve_embedding_base_url`, `_cached_openai_clients`, and the `from openai import OpenAI` line in `helpers.py`. Update tests in `test_embedding_service.py` per D-27. (3) Rename `test_no_module_level_provider_sdk_imports_in_processing_ai` → `test_no_module_level_provider_sdk_imports_in_processing`, update pathspec, remove embeddings carve-out from docstring; update module docstring to credit Phase 231; add `tests/test_embedding_provider_extension.py` (D-18/D-19/D-20); negative-control verification. Planner may collapse, split, or reorder — but the architecture-guard rename MUST land last (or in the same atomic commit as the import removal) per D-29.

- **Module docstring wording for `EmbeddingProviderExtension`** — keep the spirit of `protocols.py:91-118` (`AIProviderExtension` docstring): credit Phase 231 (and EMBPROV-01..05), summarize the dispatch-table shape (D-09), point to the entry-points pattern, note the rejection of the helpers.py module-level import. Planner picks exact wording.

- **Whether `EmbeddingUnavailableError` moves to `protocols.py`, `extensions/exceptions.py`, or stays in `service.py`** (D-22). Default: move alongside the Protocol (either `protocols.py` itself or a new `extensions/exceptions.py`) so the Protocol contract owns its exception type. If keeping it in `service.py` minimizes diff, that's also acceptable as long as the provider class can import it without creating a runtime cycle. Planner verifies.

- **Whether to add an `EmbeddingProviderExtension`-level `dimensions: int | None = None` parameter at the Protocol or only at the default** — default: at the Protocol (D-02). Reason: overlays (Bedrock, Vertex) will all want optional dimension override. Cost: one extra kwarg on the Protocol surface. Acceptable.

- **Whether to keep the existing `httpx.Timeout(60.0, connect=10.0)` SDK-level timeout config inside `DefaultOpenAIEmbeddingProvider`'s client construction**, or surface `httpx.Timeout` at the Protocol level. Default: keep it INSIDE the provider class (it's an OpenAI-SDK-specific config; Bedrock has different timeout knobs). The Protocol's `timeout: float | None = None` parameter is the call-level override (used today via `asyncio.wait_for(timeout=130.0)` for embed and `30.0` for probe).

- **Whether to expose a higher-level `embed_one(text: str, ...) -> list[float]` convenience method** alongside the batch `embed()` to make single-text callers simpler. Default: NO — both call sites (`generate_embedding`, `probe_embedding_dimensions`) use single-text today; both can wrap `[text]` and unwrap `[0]` inline. Adding `embed_one` would force overlays to implement two methods. Planner can revisit if the call-site ergonomics suffer.

- **Order of tests in `test_embedding_provider_extension.py`** — default: 1) `test_default_embedding_provider_registered`, 2) `test_overlay_embedding_provider_is_dispatched`, 3) `test_unknown_embedding_provider_raises_value_error`. Planner can add `test_default_provider_embed_returns_list_of_lists` (a contract-shape sanity check) if useful.

- **Whether Phase 231 ships `AsyncOpenAI` (replacing today's sync `OpenAI` + `asyncio.to_thread`) per D-25** — default: YES, replace with `AsyncOpenAI`. Reason: Phase 226 already uses `AsyncOpenAI` in `DefaultOpenAICompatibleProvider`; the embeddings provider should match. Eliminates `asyncio.to_thread` overhead; gives true async I/O. Risk: any code path that currently relied on sync-via-to_thread semantics (none identified — embeddings are pure request/response). Planner verifies via test-suite green-light.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec

- `docs-internal/audits/oc-separation-audit-20260502.md` §5 — decoupling rec #3 ("EmbeddingProvider hook"); §7 P1 (action item #4 "Define `EmbeddingProviderExtension` Protocol (or extend `AIProviderExtension` with `embed()`) covering `processing/embeddings/helpers.py:8`"). The single-sourced spec for Phase 231's existence.
- `docs-internal/audits/oc-separation-audit-20260502.md` §2 (Coupling Health row) — describes the residual `processing/embeddings/helpers.py:8` import as the last protocol-uncovered AI surface. Closing it lifts the v13.4 milestone Coupling Health grade.
- `.planning/REQUIREMENTS.md` §EMBPROV-01..05 — the five requirements this phase closes. SC#1 (Protocol shape `embed(texts: list[str], model: str) -> list[list[float]]`) is BINDING. SC#3's grep is BINDING (`git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returns zero hits) — the architecture-guard rename (D-13) enforces. SC#4's "rename to `test_no_module_level_provider_sdk_imports_in_processing`" is BINDING. SC#5's "test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file" is BINDING (D-18).
- `.planning/ROADMAP.md` §Phase 231 — goal statement + 5 success criteria + Source pointer.

### Project / state

- `.planning/PROJECT.md` — milestone overview; v13.4 audit-grade target Seam Quality A− is delivered jointly by Phase 226 + Phase 231 (last 🔴s close).
- `.planning/STATE.md` — confirms current backend test baseline and v13.4 phase queue. STATE.md line 6 explicitly calls out Phase 231 as ready for `/gsd-discuss-phase`; line 47 ties the milestone audit-grade target to Phase 231's contribution.
- `.planning/MILESTONES.md` — milestone closure history (informational).

### Phase 226 AIProviderExtension — the canonical sibling pattern

- `.planning/phases/226-ai-provider-extension-protocol/226-CONTEXT.md` — full context document for Phase 226. Phase 231 mirrors D-01 (Protocol surface), D-02 (method signature shape), D-04 (dict-keyed registry), D-05 (per-key `setdefault` discipline), D-06 (`ValueError` on unknown), D-07 (`@runtime_checkable`), D-10 (`resolve_runtime_config` Protocol method), D-11 (architecture-guard test pattern), D-15 (entry_points dispatch test), D-16 (default-providers smoke test). **Read end-to-end before planning Phase 231.**
- `.planning/phases/226-ai-provider-extension-protocol/226-PLAN.md` (or `226-01-PLAN.md` etc.) — concrete plan structure that Phase 231 should mirror. Read for atomic-commit decomposition + sequencing.
- `.planning/phases/226-ai-provider-extension-protocol/226-VERIFICATION.md` — what verification looked like at Phase 226 close. Phase 231's verification gates (D-29/D-30) match.
- `.planning/phases/226-ai-provider-extension-protocol/226-PATTERNS.md` — pattern audit document if planner needs additional canonical-pattern lookup.
- `backend/app/platform/extensions/protocols.py:91-152` (`AIProviderExtension`) — the actual Protocol class; Phase 231's `EmbeddingProviderExtension` mirrors the docstring + structure verbatim. Note the `@runtime_checkable` decorator, the `from __future__ import annotations` at the top of the file, and the `TYPE_CHECKING` discipline.
- `backend/app/platform/extensions/__init__.py:224-255` (`get_ai_provider`) — the canonical dict-shape accessor. Phase 231's `get_embedding_provider` mirrors the body one-for-one (single default, simpler).
- `backend/app/platform/extensions/defaults.py:428-606` (`DefaultAnthropicProvider`) and `:608-810+` (`DefaultOpenAICompatibleProvider`) — the two community defaults Phase 226 ships. Phase 231's `DefaultOpenAIEmbeddingProvider` follows the same structure: deferred imports inside method body, class-level `_clients` cache, OpenAI-shape internal conversion (not relevant for embeddings — they're already in canonical shape).
- `backend/tests/test_layering.py:778-829` (`test_no_module_level_provider_sdk_imports_in_processing_ai`) — the existing architecture guard Phase 231 RENAMES + EXPANDS. Read for the carve-out paragraph (lines 789-792) that gets removed.

### Phase 222 / 223 / 225 — earlier extension precedents

- `backend/app/platform/extensions/protocols.py:43-89` (`AuditSink`, `BillingExtension`) — earlier Protocol templates. Read for docstring shape + `TYPE_CHECKING` import discipline.
- `backend/app/platform/extensions/defaults.py:46-97` (`DefaultAuditSink`, `DefaultBillingExtension`) — deferred-import pattern. Each method does `from app.modules.X import Y` inside the function body.
- `backend/tests/test_extensions.py` — the established `patch("app.platform.extensions.entry_points", return_value=[mock_ep])` pattern. Phase 231's `test_embedding_provider_extension.py` (D-18) reuses verbatim.

### Code (current state — what Phase 231 migrates)

- `backend/app/processing/embeddings/helpers.py` — the migration target. Specifically:
  - Line 8: `from openai import OpenAI` — REMOVED per SC#3.
  - Line 19: `_cached_openai_clients: dict[str, OpenAI] = {}` — moves to `DefaultOpenAIEmbeddingProvider._clients`.
  - Lines 90-97: `resolve_embedding_base_url` — folds into `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()`.
  - Lines 100-109: `build_openai_client` — body moves to `DefaultOpenAIEmbeddingProvider.embed()` (or a private `_get_client(base_url)` method on the class).
  - Lines 26-87, 112-119: non-provider helpers (`set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding`) — stay put.
- `backend/app/processing/embeddings/service.py:31-110` (`generate_embedding`) — current dispatch site #1. Uses `build_openai_client`, `resolve_embedding_base_url`, `client.embeddings.create` via `asyncio.to_thread`. Migrates per D-21.
- `backend/app/processing/embeddings/service.py:113-172` (`probe_embedding_dimensions`) — current dispatch site #2. Same migration pattern.
- `backend/app/processing/embeddings/service.py:27-28` (`EmbeddingUnavailableError`) — exception class that may move per D-22.
- `backend/app/core/persistent_config.py:427-456` — `OPENAI_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS`, `EMBEDDING_BASE_URL` keys. Read by `resolve_embedding_base_url()` today and (post-migration) by `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()`. **Unchanged** by Phase 231.
- `backend/app/core/config.py:55-57, 91` — `embedding_model`, `embedding_dims`, `embedding_base_url` env-backed settings. **Unchanged**.

### Code (extension scaffold to extend)

- `backend/app/platform/extensions/__init__.py` — Phase 231 adds `get_embedding_provider(name)` accessor here (D-10), modeled on `get_ai_provider(name)` (lines 224-255).
- `backend/app/platform/extensions/protocols.py` — Phase 231 adds `EmbeddingProviderExtension` Protocol here (D-01..D-05). The file already has `from __future__ import annotations` (line 11) and `TYPE_CHECKING` discipline (lines 18-24).
- `backend/app/platform/extensions/defaults.py` — Phase 231 adds `DefaultOpenAIEmbeddingProvider` here (D-08). Body migrates `build_openai_client` + retry loop from `helpers.py`/`service.py` (deferred imports preserved).
- `backend/app/api/main.py:125-135` — application startup wiring (informational only; Phase 231's `get_embedding_provider()` is consulted lazily on every call, no startup-wiring change needed).

### Code (architecture-guard test)

- `backend/tests/test_layering.py:778-829` (`test_no_module_level_provider_sdk_imports_in_processing_ai`, Phase 226-era — added 2026-05-02 commit `259ebc72`) — Phase 231 RENAMES this test (D-13). Note the helper functions `_has_git_metadata()`, `_has_pathspec_magic()`, `subprocess.run(["git", "grep", ...])` at the top of the file (lines ~30-110); reused unchanged.
- `backend/tests/test_layering.py:1-38` (module docstring) — Phase 231 updates to credit 231 alongside 212/213/214/222/223/224/225/226. Same pattern as Phase 226 D-13.
- `backend/pyproject.toml` — registers the `architecture` pytest marker. Already done; no change.

### Code (entry-points test pattern)

- `backend/tests/test_extensions.py:32, 61, 84, 146, 166, 171` — the established `patch("app.platform.extensions.entry_points", return_value=[mock_ep])` pattern. Phase 231's `tests/test_embedding_provider_extension.py` (D-18) reuses verbatim.

### Code (existing embeddings tests that must stay green per SC#5)

- `backend/tests/test_embedding_service.py` — 5 tests (`test_generate_embedding_returns_float_vector`, `_raises_when_no_openai_key`, `_uses_persistent_config`, `_truncates_long_input`, `_dimension_mismatch`). Mock targets migrate per D-27. **Behavior must stay green.**
- `backend/tests/test_embedding_pipeline.py` — patches `service.generate_embedding`; UNAFFECTED per D-28.
- `backend/tests/test_hybrid_search.py` — patches `search.service.generate_embedding`; UNAFFECTED per D-28.
- `backend/tests/test_semantic_search.py` (if present) — UNAFFECTED.

### Phase 226 commit history (for sequencing reference)

- Commit `259ebc72` (2026-05-02) — added the `test_no_module_level_provider_sdk_imports_in_processing_ai` architecture guard with the embeddings carve-out. Phase 231 removes the carve-out and renames the test.
- Phase 226 plan files (`.planning/phases/226-*/226-0{1,2,3,4}-PLAN.md`) — atomic commit sequence Phase 231 should mirror at smaller scale (~2 plans likely; possibly 3 if the architecture-guard rename gets its own commit).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`backend/app/platform/extensions/protocols.py:91-152` (Phase 226 `AIProviderExtension`)** — Protocol-class docstring template. Phase 231's `EmbeddingProviderExtension` follows the same shape: brief contract statement, registration mechanism note, dispatch-table-by-name note, method signatures.
- **`backend/app/platform/extensions/defaults.py:608-810+` (Phase 226 `DefaultOpenAICompatibleProvider`)** — class-level `_clients: dict[str, AsyncOpenAI]` cache pattern. Phase 231's `DefaultOpenAIEmbeddingProvider` mirrors verbatim — same `dict[str, AsyncOpenAI]` keyed by `base_url`, same `setdefault`-on-first-use discipline.
- **`backend/app/platform/extensions/__init__.py:43-66` (`load_extensions()`)** — `importlib.metadata.entry_points("geolens.extensions")` registration loop. Phase 231 reuses unchanged. Overlay providers register under `_extensions["embedding_providers"]` (D-09).
- **`backend/app/platform/extensions/__init__.py:224-255` (`get_ai_provider()`)** — dict-keyed accessor template. Phase 231's `get_embedding_provider(name)` is structurally identical with one default instead of two.
- **`backend/tests/test_layering.py:_has_git_metadata()` + `_has_pathspec_magic()` + `subprocess.run(git grep ...)` pattern** (Phase 212/213/214/222/223/224/225/226) — Phase 231's RENAMED test reuses verbatim. No new helpers needed.
- **`@pytest.mark.architecture` marker** registered in `backend/pyproject.toml` — Phase 231 reuses; no new marker.
- **`backend/tests/test_extensions.py` `patch("app.platform.extensions.entry_points")` pattern** — Phase 231's entry-points dispatch test (D-18) reuses verbatim.
- **`processing/embeddings/helpers.py:19` (`_cached_openai_clients`)** — module-level SDK client singleton. Phase 231 moves into provider class (D-26). Cache logic preserved.
- **`processing/embeddings/helpers.py:90-97` (`resolve_embedding_base_url`)** — fallback chain `EMBEDDING_BASE_URL → OPENAI_BASE_URL → "https://api.openai.com/v1"`. Phase 231 moves into `resolve_runtime_config` (D-04). Behavior preserved byte-for-byte.

### Established Patterns

- **Closed-set caller migration via `git grep`** (Phase 212/213/214/222/225/226) — Phase 231 inherits. The 2-call-site list (D-21) is enumerated by `git grep -nE 'build_openai_client\(|resolve_embedding_base_url\(' backend/app/processing/embeddings/`. Migrate all hits; do NOT introduce `import-linter` or any architecture-DSL dependency.
- **Hard-cutover migration with NO compat shim** (Phase 222/223/225/226) — closed-set codebase, ruff + full pytest is the safety net, architecture-guard test as the regression seal. Phase 231 inherits.
- **Deferred-import discipline** — `platform/extensions/defaults.py` does deferred `from app.modules.X import Y` inside method bodies. Phase 231 follows: `DefaultOpenAIEmbeddingProvider.embed()` defers the SDK import (`from openai import AsyncOpenAI`) inside the method body. (External library imports, not `app.modules.*` — but the discipline applies anyway for consistency with Phase 226's `DefaultOpenAICompatibleProvider`.)
- **`@runtime_checkable` on every Protocol** — `IdentityProtocol`, `RoleProtocol`, `IdentityExtension`, `AuditSink`, `BillingExtension`, `AIProviderExtension`. Phase 231's `EmbeddingProviderExtension` inherits.
- **`from __future__ import annotations`** at the top of every Protocol-bearing module — already in place at `protocols.py:11`; no change.
- **Per-key `setdefault` for default seeding** — Phase 226 D-05 dict-shape discipline; Phase 231 mirrors with one key (`"openai_compatible"`).
- **Architecture-guard rename = sequencing constraint** — when widening a guard's pathspec, the existing import being widened-into must be removed FIRST (or in the same commit). Phase 231 D-29 captures this.

### Integration Points

- **`backend/app/api/main.py` startup chain**: `load_extensions()` → `init_edition()` → mount routers. Phase 231's `get_embedding_provider(name)` is consulted lazily per-call (D-10), NOT at startup. No startup-wiring change.
- **Embeddings call sites** (`processing/embeddings/service.py`): `generate_embedding`, `probe_embedding_dimensions`. Both migrate to `provider_ext.embed(...)` per D-21.
- **Search service consumer** (`backend/app/modules/catalog/search/service.py:48,261`): calls `generate_embedding(query_text, session)`. UNCHANGED — `generate_embedding`'s signature stays the same.
- **Settings router consumer** (`backend/app/modules/settings/router.py:112,114,333,337`): calls `probe_embedding_dimensions(db)`. UNCHANGED — `probe_embedding_dimensions`'s signature stays the same.
- **Procrastinate worker process** (`processing/embeddings/tasks.py:embed_record`): runs in worker, calls `generate_embedding`/`generate_and_store_embedding`. UNCHANGED — service-layer signatures stay stable.
- **OpenAPI snapshot (`backend/openapi.json`)**: unaffected. `EmbeddingProviderExtension` is Python-typing only.
- **CLAUDE.md "FastAPI trailing slashes" / "OGC routes" rules**: not affected — Phase 231 is below the route layer.

### Risk surfaces

- **`AsyncOpenAI` vs sync `OpenAI` swap** (D-25). Today `service.py` calls `await asyncio.to_thread(client.embeddings.create, ...)` with the sync client. Switching to `AsyncOpenAI` and `await client.embeddings.create(...)` removes the to_thread overhead. Risk: if any test fixture or mock relies on the sync client object's interface (e.g., asserts `client.embeddings.create.return_value` not `AsyncMock`), it breaks. Mitigation: D-27 already specifies `mock_provider.embed = AsyncMock(return_value=[fake_vector])` — tests mock at the provider boundary, not the SDK boundary. Validates at the existing 5 `test_embedding_service.py` tests.
- **`EmbeddingUnavailableError` location move** (D-22). If moved to `protocols.py` or a new `extensions/exceptions.py`, callers (`service.py:46-53, 122-125`) update imports. Risk: any test that patches `service.EmbeddingUnavailableError` breaks. Mitigation: re-export from `service.py` for back-compat (`from app.platform.extensions.exceptions import EmbeddingUnavailableError`). Or just keep it in `service.py` — both work; D-22 default is "move alongside the Protocol" but planner can stay if the diff is smaller.
- **Architecture-guard rename ordering** (D-29). If the test pathspec is widened BEFORE the `helpers.py:8` import is removed, CI fails. Sequencing: import removal commit MUST precede or be combined with the test rename commit. Plan order: (1) introduce Protocol + default + accessor (additive only); (2) migrate callers + remove helpers.py provider artifacts; (3) rename test + add new entry-points test.
- **Retry-loop semantics moving into provider** (D-22). Today's `service.py:72-110` retry runs INSIDE `generate_embedding` (caller-side). Moving into `DefaultOpenAIEmbeddingProvider.embed()` means overlays must implement their own retry logic. Risk: a Bedrock overlay implementer who skips retry sees worse reliability. Mitigation: documented in the Protocol docstring — "the provider is responsible for transient-failure handling; community defaults retry up to 2 times with 2.0s+jitter backoff." The two community-default tests (D-19, D-27 migration) verify retry behavior is preserved.
- **Tests that mock `service.build_openai_client` directly (D-27)**. The 5 tests in `test_embedding_service.py` get rewritten. Risk: if a test asserts a call shape that no longer exists post-migration (`mock_client_instance.embeddings.create.assert_called_once_with(model=..., input=..., dimensions=...)`), the assertion needs to move to the mock provider's `embed` call instead (`mock_provider.embed.assert_called_once_with(texts=[...], model=..., dimensions=...)`). Mechanical migration; small surface (5 tests).
- **Phase 226 overlap** — Phase 226 (AI provider) shipped on `protocols.py`, `defaults.py`, `__init__.py` — Phase 231 touches the same three files. Conflict surface: zero, because Phase 231 ADDS new symbols (`EmbeddingProviderExtension`, `DefaultOpenAIEmbeddingProvider`, `get_embedding_provider`) without modifying Phase 226's. Verified by file-section analysis: Phase 226 occupies lines 91-152 of `protocols.py`; Phase 231 appends after.

</code_context>

<specifics>
## Specific Ideas

- **Audit phrasing chosen, in their words:** `oc-separation-audit-20260502.md` §5: "EmbeddingProvider hook (P2). `processing/embeddings/helpers.py:8` is currently outside the AI provider seam." Phase 231 closes this exact line.
- **ROADMAP §231 SC#1's binding signature** — `embed(texts: list[str], model: str) -> list[list[float]]` — the architecture-guard rename + new entry-points test enforces. Codebase scan today: 1 hit (`helpers.py:8 from openai import OpenAI`). After migration: zero hits.
- **ROADMAP §231 SC#5's binding "test overlay registered via `importlib.metadata` entry_points"** — D-18 registers a fake `TestEmbeddingProvider` via the existing `patch("app.platform.extensions.entry_points")` pattern, exercising `load_extensions()` → `register_extensions(registry)` → `get_embedding_provider("test_embedding_provider")` → `provider_ext.embed()`.
- **"Ships only the seam — new provider implementations land in overlays or follow-up milestones"** (mirrors Phase 226 goal). Phase 231 ships ZERO new providers — only `DefaultOpenAIEmbeddingProvider` (which encapsulates today's behavior byte-for-byte) plus the seam. Bedrock / Vertex / Azure / Cohere embeddings are explicitly out-of-scope.
- **Phase 231 plug-in shape will look like:** an enterprise overlay (e.g., `geolens-enterprise/embedding-providers/`) registers via `[project.entry-points."geolens.extensions"]` calling `register_extensions(registry)`. The registry slot is `_extensions["embedding_providers"]` (dict-keyed by name); each overlay provider is added under its name (`registry.setdefault("embedding_providers", {})["bedrock"] = BedrockEmbeddingProvider()`).
- **Phase 229 audit-grade target:** Phase 229 reruns `/oc-audit` and confirms Seam Quality grade A− (last 🔴 closes when both Phase 226 and Phase 231 ship). Phase 231's contribution: closing the embeddings residual flagged in `oc-separation-audit-20260502.md` §5 / §7 P1 (action item #4).
- **No Phase 226 dependency** — ROADMAP §231 explicitly says "Depends on: None — independent of Phase 225/226/230 (different file scope: `processing/embeddings/`). Can ship in parallel." Phase 226 has SHIPPED; Phase 231 starts on the post-226 baseline.

</specifics>

<deferred>
## Deferred Ideas

- **New embedding-provider implementations (Bedrock / Vertex / Azure / Cohere)** — Phase 231 ships only the seam, not the providers. Bedrock and Vertex likely land in `geolens-enterprise/embedding-providers/` (cloud-tier feature); Azure OpenAI and Cohere may be community-tier follow-ups. Each provider is its own focused phase (~2-3d).
- **`EMBEDDING_PROVIDER` PersistentConfig key** — Phase 231 hardcodes `"openai_compatible"` in callers (D-12). When a future overlay ships a second embedding provider that needs deployment-level user choice, the config key gets added in that phase.
- **Combining `AIProviderExtension.embed()` with the LLM provider Protocol** (audit §7 P1 alternative wording — "or extend `AIProviderExtension` with `embed()`"). REJECTED in Phase 231 — see D-06 rationale (Anthropic doesn't ship embeddings; folding embed into AIProviderExtension would force Anthropic's provider class to raise NotImplementedError on embed). Two distinct Protocols, two distinct registries — cleaner separation.
- **Per-tenant provider instances (Cloud tier)** — `DefaultOpenAIEmbeddingProvider._clients` cache is process-scoped today (D-26). When Cloud tier needs different OpenAI API keys per tenant, the cache might need rethinking. Phase 999.6 (tenant scoping) territory.
- **Provider configuration UX (admin UI)** — currently embedding `model`/`dims`/`base_url` are set via PersistentConfig (admin settings UI). Adding new embedding providers via overlays should integrate with the admin UI's provider dropdown. Phase 231 doesn't touch the admin UI; if a future phase wants overlays to declare admin-UI metadata (display name, config schema), that's a `ProviderManifest`-style extension. Out of Phase 231's seam-only scope.
- **Provider-side dimension validation** — D-25's removal of `service.py`'s dimension-mismatch test behavior (the test currently verifies the service passes through whatever the API returns, even if length differs from configured `EMBEDDING_DIMS`). Phase 231 preserves this behavior — the provider does NOT enforce dimension match; that's a downstream pgvector-INSERT concern. A future phase may add provider-side dim validation (e.g., raise `EmbeddingDimensionMismatchError` if the returned vector length differs from the requested `dimensions`).
- **True embedding streaming / chunked delivery** — embeddings are inherently batch-only; no streaming concept applies. Out of scope forever (unlike Phase 226 D-03 which left `stream()` declared on the AI Protocol for future implementation).
- **Pyright/mypy CI gate** — Phase 214 D-25 / Phase 225 D-26 / Phase 226 D-25 deferred this; Phase 231 inherits. The project does not run pyright or mypy in CI. ruff + pytest is the gate.
- **Replacing `Default*Provider` no-op shims with `None` returns** — Phase 222 D-04 / Phase 223 D-07 / Phase 225 D-09 / Phase 226 D-17 all keep the Default class shape. Phase 231 inherits; `DefaultOpenAIEmbeddingProvider` is a real class with real methods.
- **Tightening the architecture-guard regex to ANY `from <provider-sdk>` import (not just `anthropic`/`openai`)** — Phase 231 keeps the SC#4-bound regex (`^(from|import) (anthropic|openai)( |$)`). When a future Bedrock/Vertex provider class ships in `defaults.py`, those SDKs are NOT in `processing/`, so the guard correctly ignores them. If a future overlay accidentally adds an SDK import inside `processing/`, the broader pattern catches it as a P3 follow-up.

</deferred>

---

*Phase: 231-embedding-provider-extension-protocol*
*Context gathered: 2026-05-02*
