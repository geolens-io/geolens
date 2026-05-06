---
status: complete
phase: 226-ai-provider-extension-protocol
source: [226-VERIFICATION.md]
started: 2026-05-01
updated: 2026-05-06
related_fixes:
  - e54d3ff2  # fix(ai): guard SSE consumers against same-tick double-fire
  - e7fd5fdb  # fix(ai): handle CRLF line endings in SSE parser (root cause)
  - 8dd83138  # test(ai): lock in SSE parser CRLF fix
---

## Current Test

[testing complete]

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

result: pass

why_human: Live LLM API calls require API keys and network access not available in the automated test suite. The 2054-test suite mocks at the SDK boundary (TestProvider) or the router boundary; only manual testing exercises the real `client.messages.create()` and `client.chat.completions.create()` calls under the new Protocol dispatch.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]

## UAT Result — 2026-05-06

**Mode:** Playwright MCP (live browser via mcp__playwright__*) + live Anthropic API
**Verdict:** PASS — CR-01 fix verified end-to-end against real Anthropic API

**Setup:**
- Stack: `docker compose up -d` (api + worker + db + frontend + titiler all healthy)
- Anthropic API key + OpenAI-compatible API key both present in `.env`; api/worker bounced after env update
- Admin AI config: `provider=anthropic, model=claude-sonnet-4-20250514, enabled=true, configured=true`. SQL generator uses `claude-haiku-4-5-20251001` (separate model)
- New map: `cea9cae6-fd66-435e-9d48-d478bed07146` ("Global Reefs and Country Boundaries")

**Steps observed:**

- **Step 3 (generate-map-from-prompt) — PASS.** Prompt: *"Create a map showing reefs and country boundaries together. Color the reefs cyan and the countries with a light fill."* → 4 LLM rounds via `DefaultAnthropicProvider.complete()` with tools (`search_datasets` invoked 3 times, then `stop_reason=end_turn`). `Map generation complete (streaming)` logged with `input_tokens=1966, output_tokens=694`. Map created with both Admin 0 Countries (10m) and Reefs (10m) layers; canvas renders cyan reefs visibly along Red Sea / Sri Lanka / Indian Ocean. Visual: `phase-226-uat-step1-generated-map.png`.
- **Step 4 (chat-edit-map) — PASS.** Refinement: *"Change the country boundaries to a thicker dark gray line and hide the labels."* → 2 LLM rounds via the same provider path (`Chat stream round` round 1 = tool_use, round 2 = end_turn; `Chat stream complete` with `total_input_tokens=593, total_output_tokens=306`). Visual: `phase-226-uat-step2-chat-edit.png`.
- **Step 5 (CR-01 empty-tools path — the regression-critical path) — PASS.** Prompt: *"How many country features are in the Admin 0 Countries layer?"* → assistant emitted `tool_use` for `query_data`, which routed through `app.processing.ai.sql_generator.generate_sql` → `provider_ext.complete(tools=[], max_rounds=1)`. Anthropic returned `HTTP/1.1 200 OK`; `SQL generated` logged with `model=claude-haiku-4-5-20251001, sql_length=64`. Chat completed successfully (`Chat stream complete`). **This is the exact call that, pre-CR-01, would have produced `BadRequestError: tools: must have at least 1 item` — and it succeeded cleanly.** Visual: `phase-226-uat-step3-sql-result.png`.
- **Step 6 (log audit) — PASS.** Across the full UAT window in api+worker logs:
  - **0** occurrences of `BadRequestError`, `tools: must have`, or `at least 1 item`
  - **0** non-200 responses on `/ai/*` endpoints
  - **9** Anthropic API calls — all `HTTP/1.1 200 OK`
  - `Generating SQL` + `SQL generated` confirmed for the empty-tools path

**Frontend bugs found, root-caused, and fixed during the UAT:** the dialog showed a transient "Failed to generate map" toast and the Ask AI panel never rendered the assistant message bubble — even though the backend created the map and emitted a perfect `done` SSE event. Initial hypothesis was a React-StrictMode dev-mode dual-POST; the actual root cause was a CRLF-handling bug in the frontend SSE parser. Both fixes shipped on `main`:

- `e54d3ff2 fix(ai): guard map+chat SSE consumers against same-tick double-fire` — `useRef` inflight lock at the top of `handleAiGenerate` / `handleSend`; `streamGenerateMap` now accepts an `AbortSignal`; MapCreateDialog wires an `AbortController` per submit and aborts on dialog close + unmount. Defense-in-depth against same-tick double-fire (StrictMode dev double-invoke, browser double-submit). Reduced the network signature from 2 POSTs/submit to 1, but did NOT eliminate the toast.
- `e7fd5fdb fix(ai): handle CRLF line endings in SSE parser` — **the actual fix.** `sse-starlette` emits `\r\n` line terminators per spec, but both `streamGenerateMap` and `streamChatMessage` split the buffer on `\n` only, leaving every line with a trailing `\r`. The frame-boundary check `if (line === '')` therefore never matched (`line` was `'\r'`), the `done` event was never yielded, and the consumer fell through to the "stream ended without done event" branch. Surgical per-line `\r` strip in both parsers. Re-verified live against the Anthropic API: `/maps` "Generate Map" closes the dialog and navigates on success; the Ask AI panel renders the assistant bubble + "Applied N changes / Undo" chip and the map canvas live-updates.
- `8dd83138 test(ai): lock in SSE parser CRLF fix with stream consumer regression tests` — 5 new tests in `frontend/src/api/__tests__/maps-stream.test.ts` exercising the parser against real `ReadableStream` bytes (CRLF, LF-only, mid-CRLF chunk split, AbortSignal threading, ChatPanel parity). The pre-existing `ChatPanel.test.tsx` mocks `streamChatMessage` at the function boundary, so the parser was never exercised against real SSE bytes — these tests would have caught the original bug.

**Visual evidence (initial UAT, before frontend fix — backend dispatch was already clean here):**
- `.playwright-mcp/phase-226-uat-step1-generated-map.png` — generated map with reefs + country boundaries rendered correctly (after manual navigation to `/maps/{id}` despite the toast)
- `.playwright-mcp/phase-226-uat-step2-chat-edit.png` — chat-edit-map prompt visible in Ask AI panel after backend completion (no assistant bubble due to parser bug)
- `.playwright-mcp/phase-226-uat-step3-sql-result.png` — SQL question prompt visible in Ask AI panel; CR-01 path fired in backend (`Generating SQL` → `SQL generated`, `sql_length=64`)

**Visual evidence (re-verification, after `e7fd5fdb`):**
- `.playwright-mcp/phase-226-uat-rerun-step1-success.png` — dialog closes cleanly, navigates to `/maps/6222fe45-…` ("World Countries"), green country fill rendered as requested
- `.playwright-mcp/phase-226-uat-rerun-step2-chat-success.png` — assistant bubble *"Done! The countries are now filled with red color while maintaining the same opacity level."* rendered, "Applied 1 change · Undo" chip present, map canvas live-updated to red fill

**Sign-off:** Live LLM dispatch round-trip works end-to-end with no provider-API regressions. The CR-01 conditional-`tools=` fix is verified against the real Anthropic API. Frontend SSE consumers (Generate Map + Ask AI) now render the success path correctly. Phase 226 is closeable on the human-verification axis.
