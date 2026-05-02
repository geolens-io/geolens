# Phase 231: embedding-provider-extension-protocol - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-02
**Phase:** 231-embedding-provider-extension-protocol
**Mode:** `--auto --chain` (autonomous gray-area resolution; auto-advances to plan-phase)
**Areas discussed:** Protocol surface, Default provider shape, Registry shape & accessor, Provider name resolution, Architecture guard, Test seam, Caller migration, Verification gates

---

## Protocol surface

| Option | Description | Selected |
|--------|-------------|----------|
| Batch `embed(texts, model, dimensions, base_url, timeout) -> list[list[float]]` | Matches SC#1 binding signature; supports both call sites + future overlays | ✓ |
| Singular `embed(text, model) -> list[float]` | Simpler for current call sites but forces overlays to add per-string round trips | |
| Combined Protocol with `AIProviderExtension.embed()` | Audit §7 P1 alternative wording | |

**Auto-selected:** Batch shape. Reason: SC#1 binds `texts: list[str]`. Combined Protocol rejected because Anthropic doesn't ship embeddings — folding `embed` onto `AIProviderExtension` would force `DefaultAnthropicProvider` to raise NotImplementedError. Two distinct Protocols, two distinct registries.

**Notes:** D-01, D-02, D-03 (no `stream()` — embeddings are batch-only by API design), D-04 (`resolve_runtime_config` mirrors Phase 226 D-10), D-05 (`@runtime_checkable`).

---

## Default provider shape

| Option | Description | Selected |
|--------|-------------|----------|
| Single `DefaultOpenAIEmbeddingProvider` | Matches SC#2; Anthropic doesn't have embeddings API | ✓ |
| Two defaults (`DefaultAnthropicEmbeddingProvider` + `DefaultOpenAIEmbeddingProvider`) | Mirrors Phase 226's two-default shape | |

**Auto-selected:** Single default. Reason: Phase 226 has two defaults because there are two LLM SDK integrations; embeddings only has one (OpenAI-compatible). The `EmbeddingUnavailableError` message at `service.py:48-53` explicitly calls out that Anthropic has no embedding API.

**Notes:** D-06, D-07 (registered under name `"openai_compatible"` matching Phase 226's openai-compatible AI provider name — shared semantics for operators), D-08 (class name per ROADMAP §231 SC#2 verbatim).

---

## Registry shape & accessor

| Option | Description | Selected |
|--------|-------------|----------|
| Dict-keyed `_extensions["embedding_providers"]: dict[str, ...]` | Matches Phase 226 D-04 dispatch-table shape; SC#2 binding | ✓ |
| Single-slot `_extensions["embedding_provider"]` | Simpler for one default; matches `processing_port` shape | |
| List-shape `_extensions["embedding_providers"]: list[...]` | Matches `audit_sinks`/`billing_extensions` shape | |

**Auto-selected:** Dict-keyed. Reason: SC#2 binding wording ("follows the dict-shape pattern from `get_ai_provider(name)` Phase 226"). Even though community ships one default, future overlays will add fan-out by name (Bedrock, Vertex). Code symmetry with Phase 226 — overlay authors learn ONE pattern.

**Notes:** D-09, D-10 (`get_embedding_provider(name)` accessor body mirrors Phase 226 verbatim), D-11 (`ValueError` on unknown — preserves symmetry).

---

## Provider name resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcode `"openai_compatible"` in callers | No new config key; community has only one provider | ✓ |
| Add `EMBEDDING_PROVIDER` PersistentConfig | Matches `LLM_PROVIDER` symmetry | |

**Auto-selected:** Hardcode in callers. Reason: `LLM_PROVIDER` was added when there were already TWO LLM providers needing user choice. Embeddings community has ONE provider; adding a config key for a single-option choice is unnecessary scope. Future overlays can add `EMBEDDING_PROVIDER` if they need user-selectable embedding provider.

**Notes:** D-12.

---

## Architecture guard

| Option | Description | Selected |
|--------|-------------|----------|
| Rename `_processing_ai → _processing` and broaden pathspec to `backend/app/processing/` | SC#4 binding | ✓ |
| Add a NEW test alongside the existing one | Two tests, two pathspecs | |

**Auto-selected:** Rename. Reason: SC#4 binding wording ("renamed/expanded to `test_no_module_level_provider_sdk_imports_in_processing` covering both `processing/ai/` and `processing/embeddings/`"). Single test is cleaner — same regex `^(from|import) (anthropic|openai)( |$)` covers both SDKs.

**Notes:** D-13, D-14 (pathspec broadens to `backend/app/processing/`; remove embeddings carve-out from docstring), D-15 (negative-control verification), D-16 (module docstring updated to credit Phase 231), D-17 (existing `architecture` marker reused).

---

## Test seam (entry_points dispatch)

| Option | Description | Selected |
|--------|-------------|----------|
| `tests/test_embedding_provider_extension.py` with `entry_points` patch | Mirrors Phase 226 D-15; SC#5 binding | ✓ |
| Inline tests in `tests/test_embedding_service.py` | Reuse existing file | |

**Auto-selected:** New dedicated test file. Reason: SC#5 binding wording ("test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file"). Mirrors Phase 226's `test_ai_provider_extension.py`.

**Notes:** D-18 (overlay-dispatch test), D-19 (default-provider smoke test), D-20 (unknown-provider raises `ValueError`).

---

## Caller migration

| Option | Description | Selected |
|--------|-------------|----------|
| Migrate 2 sites + delete `build_openai_client`/`resolve_embedding_base_url`/`_cached_openai_clients` | Hard cutover; matches Phase 222/223/225/226 discipline | ✓ |
| Keep `build_openai_client` as a thin shim | Backward-compatible | |

**Auto-selected:** Hard cutover, no shim. Reason: closed-set codebase, ruff + full pytest is the safety net, architecture-guard test seals the regression. Same discipline as Phase 226 D-25 ("incidental dead-code cleanup"). The shim option is rejected because `helpers.py:8` MUST be removed per SC#3 — keeping `build_openai_client` would force a deferred SDK import inside the shim, defeating the architecture guard's intent.

**Notes:** D-21 (2 call sites: `generate_embedding`, `probe_embedding_dimensions`), D-22 (retry/backoff moves into provider; `EmbeddingUnavailableError` location TBD by planner), D-23 (`from openai import OpenAI` removed — SC#3), D-24 (`resolve_embedding_base_url` folds into `resolve_runtime_config`), D-25 (`build_openai_client` body migrates; switch from sync `OpenAI` + `asyncio.to_thread` to `AsyncOpenAI` to match Phase 226), D-26 (`_cached_openai_clients` → class-level cache), D-27 (test mocks migrate to provider-boundary), D-28 (higher-level service mocks unaffected).

---

## Verification gates

| Option | Description | Selected |
|--------|-------------|----------|
| Full backend test suite + ruff + alembic check + new entry-points tests + renamed architecture guard | Standard Phase 226 acceptance gate | ✓ |
| Stricter (mypy/pyright CI) | Out of scope; not currently in CI | |

**Auto-selected:** Standard. Reason: matches Phase 226 D-24 acceptance gate verbatim. Mypy/pyright deferred (Phase 214 D-25 inheritance).

**Notes:** D-29 (sequencing constraint: architecture-guard rename must land last or in same commit as helpers.py import removal), D-30 (existing embeddings tests stay green per SC#5), D-31 (no frontend impact), D-32 (no Alembic migration), D-33 (Phase 229 audit dependency).

---

## Claude's Discretion

The following decisions were left flexible for the planner — both options work, the planner picks based on diff size, ergonomics, or stylistic fit:

- **Commit decomposition** (3 atomic commits suggested, but planner can collapse/split based on file-size budgets)
- **Module docstring wording for `EmbeddingProviderExtension`** — keep the spirit of Phase 226's `AIProviderExtension` docstring; planner picks exact wording
- **Where `EmbeddingUnavailableError` lives** (D-22) — `protocols.py` vs `extensions/exceptions.py` vs stay in `service.py`; default = move alongside Protocol
- **Whether to expose a higher-level `embed_one(text)` convenience method** alongside batch `embed()` — default NO; both call sites can wrap `[text]` and unwrap `[0]` inline
- **Order of tests in `test_embedding_provider_extension.py`** — default: 1) default registered, 2) overlay dispatched, 3) unknown raises ValueError
- **Whether to switch sync `OpenAI` to `AsyncOpenAI`** (D-25) — default YES (matches Phase 226's `DefaultOpenAICompatibleProvider`); planner verifies via test-suite green-light
- **Whether the `DefaultOpenAIEmbeddingProvider._clients` cache is class-level (`dict` shared across instances) vs instance-level** — default class-level (matches Phase 226 D-25)

---

## Deferred Ideas

(Captured in CONTEXT.md `<deferred>` block — repeated here for audit completeness.)

- New embedding-provider implementations (Bedrock / Vertex / Azure / Cohere) — separate phases
- `EMBEDDING_PROVIDER` PersistentConfig key — when a future overlay needs user-choice
- Combining `AIProviderExtension.embed()` with the LLM provider Protocol — REJECTED (Anthropic has no embeddings API)
- Per-tenant provider instances (Cloud tier) — Phase 999.6 (tenant scoping) territory
- Provider configuration UX (admin UI) — out of seam-only scope
- Provider-side dimension validation — preserves today's pass-through behavior
- True embedding streaming — N/A (embeddings are inherently batch)
- Pyright/mypy CI gate — Phase 214 deferred; inherited
- Tightening architecture-guard regex to ANY provider SDK — Phase 231 stays SC#4-bound
