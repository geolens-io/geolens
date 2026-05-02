---
phase: 226-ai-provider-extension-protocol
reviewed: 2026-05-01T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - backend/app/platform/extensions/__init__.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/platform/extensions/protocols.py
  - backend/app/processing/ai/chat_service.py
  - backend/app/processing/ai/llm_loop.py
  - backend/app/processing/ai/service.py
  - backend/app/processing/ai/sql_generator.py
  - backend/app/processing/ai/streaming.py
  - backend/app/processing/ai/tools.py
  - backend/tests/test_ai_provider_extension.py
  - backend/tests/test_layering.py
  - backend/tests/test_sql_engine.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: fixed
fixed_at: 2026-05-01
fix_commits:
  - 001c030f  # CR-01 — conditional tools= in both providers
  - 716480bf  # WR-01 — early API key check in get_*_client helpers
  - 5b22c385  # WR-02 — sql_generator base_url via resolve_runtime_config
  - b298454e  # IN-01 — drop vacuous :!backend/tests/ pathspec exclusion
fix_verification:
  full_suite: 2054 passed, 19 skipped, 5 deselected
  ruff: clean (app/platform/extensions/ + app/processing/ai/ + tests/test_layering.py)
---

# Phase 226: Code Review Report

**Reviewed:** 2026-05-01
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

The Protocol extraction is structurally sound: `AIProviderExtension` is correctly `@runtime_checkable`, the dict-keyed registry uses per-key `setdefault` seeding, `get_ai_provider()` raises `ValueError` with the expected message, and all four `resolve_provider()` call sites unpack the correct `(name, model, runtime_config)` triple. The architecture guard in `test_layering.py` passes cleanly against the migrated code. The entry-points test exercises the full dispatch chain.

One blocker was found: `DefaultAnthropicProvider.complete()` unconditionally passes `tools=cached_tools` (where `cached_tools` is `[]` when the caller passes `tools=[]`) to the Anthropic API. The Anthropic API rejects an empty tools array with a 400 BadRequestError. This breaks `sql_generator.generate_sql()` and `service._retry_parse_map_spec()` for any deployment using the Anthropic provider — these two callers deliberately pass `tools=[]` for text-only completions.

Two warnings cover a missing API-key guard in `get_anthropic_client()` and a bypass of the `resolve_provider()` pattern in `sql_generator.py` that silently routes the wrong `base_url` to non-default overlay providers.

## Critical Issues

### CR-01: `tools=[]` sent to Anthropic API causes BadRequestError in SQL generation and map-spec retry

**File:** `backend/app/platform/extensions/defaults.py:470-482`
**Issue:** `DefaultAnthropicProvider.complete()` always passes `tools=cached_tools` to `client.messages.create()`. When the caller passes `tools=[]` (no tools needed), `add_tool_cache_control([])` returns `[]` (the guard at `llm_loop.py:93` correctly short-circuits), so `cached_tools = []`. The Anthropic API then receives `"tools": []` in the JSON body. The Anthropic Messages API rejects a present-but-empty tools array with a 400 BadRequestError: "tools: must have at least 1 item."

Two production callers hit this path every time the configured LLM provider is `"anthropic"`:
- `sql_generator.generate_sql()` (`sql_generator.py:357-367`): passes `tools=[]`, `max_rounds=1`.
- `service._retry_parse_map_spec()` (`service.py:384-388`): passes `tools=[]`, `max_rounds=1`.

Both callers pass `tools=[]` intentionally (text-only single-round completion). Neither the SDK (verified against anthropic 0.88.0 — `transform()` sends `"tools": []` verbatim) nor the `add_tool_cache_control` helper strips the empty list. The `test_overlay_provider_is_dispatched` test calls `complete(tools=[])` but uses a `TestProvider` mock that never reaches the real API, so the bug is not caught by the test suite.

**Fix:** Omit `tools` from the Anthropic API call entirely when the list is empty. Replace the unconditional `tools=cached_tools` argument with a conditional keyword-argument dict:

```python
# defaults.py — DefaultAnthropicProvider.complete()

create_kwargs: dict = {
    "model": model,
    "max_tokens": max_tokens,
    "temperature": temperature,
    "system": cached_system,
    "messages": messages,
}
if cached_tools:          # <-- only include tools when non-empty
    create_kwargs["tools"] = cached_tools

response = await client.messages.create(**create_kwargs)
```

Apply the same fix to both `DefaultAnthropicProvider.complete()` (line 477) and verify `DefaultOpenAICompatibleProvider.complete()` (line 654) — the OpenAI API accepts `tools=[]` (it is not rejected) so that provider does not need the guard, but consistency is recommended.

---

## Warnings

### WR-01: `get_anthropic_client()` creates a client with `api_key=None` when key is not configured

**File:** `backend/app/processing/ai/llm_loop.py:42-60`
**Issue:** `get_anthropic_client()` calls `AsyncAnthropic(api_key=reveal(settings.anthropic_api_key), ...)` without first checking `if not settings.anthropic_api_key`. `reveal(None)` returns `None`, and `AsyncAnthropic(api_key=None)` is accepted by the SDK constructor (lazy auth validation). The resulting client object is cached at class level on `DefaultAnthropicProvider._client`. Any future caller that reaches `get_anthropic_client()` without an upstream key guard will get a silently invalid client; the failure surfaces only at the first API call as an `AuthenticationError` rather than a clear `ValueError("Anthropic API key not configured")`.

`streaming.py` currently has its own guard at line 527 before calling `get_anthropic_client()`, so the streaming path is safe. But the pattern diverges from `DefaultAnthropicProvider.complete()` which correctly raises `ValueError` before creating the client (line 451). The two code paths that share the cache should have identical guard semantics.

**Fix:**
```python
# llm_loop.py — get_anthropic_client()
def get_anthropic_client() -> AsyncAnthropic:
    from app.platform.extensions.defaults import DefaultAnthropicProvider

    if DefaultAnthropicProvider._client is None:
        if not settings.anthropic_api_key:          # <-- add guard
            raise ValueError("Anthropic API key not configured")
        DefaultAnthropicProvider._client = AsyncAnthropic(
            api_key=reveal(settings.anthropic_api_key),
            timeout=_LLM_TIMEOUT,
            max_retries=2,
        )
    return DefaultAnthropicProvider._client
```

Apply the same guard to `get_openai_client()` for `settings.openai_api_key`.

---

### WR-02: `sql_generator.generate_sql()` bypasses `resolve_provider()` and unconditionally passes `OPENAI_BASE_URL` to all providers

**File:** `backend/app/processing/ai/sql_generator.py:337-366`
**Issue:** `generate_sql()` reads `LLM_PROVIDER` and `OPENAI_BASE_URL` directly from `PersistentConfig`, always passes `base_url=<openai_url>` to `provider_ext.complete()`, and skips the `resolve_provider()` / `resolve_runtime_config()` pattern that all other callers use (service.py:639,719; chat_service.py:935; streaming.py:514). Two consequences:

1. When `LLM_PROVIDER = "anthropic"`, `OPENAI_BASE_URL` is fetched unnecessarily (an extra DB round-trip) and passed to `DefaultAnthropicProvider.complete()` where the `base_url` parameter is silently ignored (it appears in the signature at line 427 but is never referenced in the method body). This is harmless for the community provider but incorrect for an overlay that registers a custom `"anthropic"`-keyed provider that actually routes requests to a non-standard endpoint (e.g., AWS Bedrock Anthropic) — `sql_generator` would always pass the OpenAI URL.

2. `sql_generator` uses `LLM_MODEL_LIGHT` (intentionally, for the lighter SQL model) rather than `LLM_MODEL`, but it does not go through `resolve_runtime_config()`. If an overlay provider exposes `resolve_runtime_config()` that sets provider-specific runtime fields beyond `base_url` and `default_model`, `sql_generator` bypasses them entirely.

**Fix:** Adopt the `resolve_provider()` pattern, then pass only provider-appropriate fields. Since `sql_generator` intentionally uses `LLM_MODEL_LIGHT` instead of `LLM_MODEL`, a minimal fix is to call `resolve_runtime_config()` for the `base_url` and suppress the model from `runtime_config`:

```python
# sql_generator.py — generate_sql()
from app.processing.ai.llm_loop import resolve_provider  # add import

# Replace lines 337-366 with:
provider = await LLM_PROVIDER.get(db)
model = await LLM_MODEL_LIGHT.get(db)
provider_ext = get_ai_provider(provider)
runtime_config = await provider_ext.resolve_runtime_config(db)

result = await provider_ext.complete(
    model=model,
    system_prompt=prompt,
    user_message=question,
    tools=[],
    tool_executor=_noop_executor,
    max_rounds=1,
    max_tokens=2048,
    temperature=0.0,
    base_url=runtime_config.get("base_url"),
)
```

This eliminates the unconditional `OPENAI_BASE_URL` fetch for Anthropic deployments and makes the routing correct for future overlays.

---

## Info

### IN-01: Architecture guard `test_no_hardcoded_ai_provider_branches` includes a vacuous pathspec exclusion

**File:** `backend/tests/test_layering.py:753`
**Issue:** The git grep command scans `"backend/app/processing/"` and includes `":!backend/tests/"` as an exclusion pathspec. Because `backend/tests/` is entirely outside the scanned tree (`backend/app/processing/`), the exclusion has no effect — no file under `backend/tests/` would ever appear in results from scanning `backend/app/processing/`. The exclusion is dead code.

The guard itself is correct (the meaningful exclusions `":!backend/app/processing/ai/streaming.py"` and `":!backend/app/processing/ai/metadata_service.py"` do suppress the deferred-scope files). The vacuous exclusion only adds noise and may confuse readers into thinking tests are scanned.

**Fix:** Remove the dead `":!backend/tests/"` entry from the pathspec list. The docstring already correctly describes only `streaming.py` and `metadata_service.py` as excluded paths.

---

_Reviewed: 2026-05-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
