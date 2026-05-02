---
status: partial
phase: 226-ai-provider-extension-protocol
source: [226-VERIFICATION.md]
started: 2026-05-01
updated: 2026-05-01
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live LLM dispatch round-trip via dev server
expected: LLM responses complete successfully with no errors; map creation and chat editing produce correct results, confirming no functional regression in the live dispatch path. The CR-01 fix (conditional `tools=` for empty-tools paths) is exercised by `generate_sql` (any SQL query) and `_retry_parse_map_spec` (whenever the LLM emits malformed JSON in the `<map_spec>` block).

steps:
1. Run `docker compose up -d --build api worker frontend` to boot the stack.
2. Sign in to the map builder at http://localhost:8080.
3. Use **Generate map from prompt** to create a map (exercises `generate_map_from_prompt` → `DefaultAnthropicProvider.complete()` or `DefaultOpenAICompatibleProvider.complete()` with tools).
4. Use **chat-edit-map** to refine the generated map (exercises `chat_edit_map` → same provider path).
5. Issue a SQL question via **Query data** (exercises `generate_sql` → `provider_ext.complete(tools=[], max_rounds=1)` — the path that the CR-01 fix unblocked).
6. Confirm responses are identical to pre-Phase-226 behavior; no `BadRequestError: tools: must have at least 1 item` in logs.

result: [pending]

why_human: Live LLM API calls require API keys and network access not available in the automated test suite. The 2054-test suite mocks at the SDK boundary (TestProvider) or the router boundary; only manual testing exercises the real `client.messages.create()` and `client.chat.completions.create()` calls under the new Protocol dispatch.

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
