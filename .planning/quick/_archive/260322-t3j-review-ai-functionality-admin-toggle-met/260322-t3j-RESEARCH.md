# Quick Task 260322-t3j: Review AI Functionality - Research

**Researched:** 2026-03-23
**Domain:** AI features (admin toggle, metadata assist, map chat)
**Confidence:** HIGH

## Summary

The AI subsystem is well-architected with good separation of concerns: persistent config for admin toggles, sandbox-validated SQL execution, dual-provider support (Anthropic/OpenAI), and proper RBAC enforcement. However, the review uncovered several concrete gaps ranging from a missing tool definition to missing error feedback in metadata hooks, plus opportunities for hardening.

**Primary recommendation:** Fix the identified gaps (set_opacity tool definition, metadata error handling, conversation history leak), add experimental badges, and document larger enhancements.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Experimental Badge Style: Subtle badge: small "Experimental" chip/badge next to the chat panel header and chat toggle button. Amber/yellow coloring, rounded corners, matching existing badge styles. NOT a warning banner or tooltip-only approach.
- Review Scope: Full audit covering both UX/functionality gaps AND code quality/security. UX: missing features, broken flows, UX inconsistencies, edge cases. Code: injection risks, error handling gaps, API key exposure, prompt injection vulnerabilities.
- Enhancement Scope: Fix gaps and issues found during review -- implement code changes. Implement the experimental badge. Document larger enhancement suggestions as recommendations (not implemented).

### Claude's Discretion
- Prioritization of which fixes to implement vs document
- Specific wording of experimental badge text
</user_constraints>

## Findings

### 1. MISSING: `set_opacity` Tool Definition (BUG)

**Severity:** Medium
**Location:** `backend/app/ai/tools.py`

The `set_opacity` tool is referenced in:
- `chat_service.py` `_EDIT_TOOLS` set (line 43)
- `constants.py` `TOOL_LABELS` (line 14)
- `schemas.py` `ChatAction` model (line 162)
- System prompt (line 320) tells the LLM to use it for raster layers
- Frontend `ChatPanel.tsx` `handleChatAction` (line 167) handles it

But there is NO tool definition in `CHAT_TOOLS_ANTHROPIC` in `tools.py`. The LLM is instructed to use it but cannot invoke it formally. It may work via XML fallback parsing for some providers, but this is unreliable.

**Fix:** Add `set_opacity` tool definition to `CHAT_TOOLS_ANTHROPIC` in `tools.py` with `layer_id` (string, required) and `opacity` (number 0.0-1.0, required).

### 2. MISSING: Metadata Mutation Error Handling (UX GAP)

**Severity:** Medium
**Location:** `frontend/src/hooks/use-ai-metadata.ts`

All four mutation hooks (`useSummaryDraft`, `useKeywordSuggestions`, `useLineageDraft`, `useQualityStatementDraft`) have no `onError` callback. When the API returns an error (403 AI disabled, 502 provider error, 500 server error), the user gets no feedback -- the button just stops spinning.

**Fix:** Add `onError` with `toast.error()` to each mutation, or let the consuming components handle `mutation.error` state. The consuming tabs (OverviewTab, MetadataTab, SourceQualityTab) call `mutate()` without error handling either.

### 3. Conversation History Includes Raw Table Names (LOW-SEVERITY SECURITY)

**Severity:** Low
**Location:** `backend/app/ai/chat_service.py` `build_chat_system_prompt()`

The system prompt includes `table: {layer.dataset_table_name}` which leaks internal DB table names into the conversation. While these are validated server-side before SQL execution, an attacker with access to the chat could learn table naming patterns. This is defense-in-depth, not a vulnerability, since the sandbox validates all table references.

**Recommendation:** Document only, not worth changing. The table names are already visible to users who own the datasets.

### 4. No `set_opacity` Tool in Tool Definitions Creates Inconsistency

Already covered in finding 1, but noting that the system prompt mentions `set_opacity` for raster layers, creating an expectation the LLM will try to use it. When the tool doesn't exist in the formal definition, Anthropic will ignore it and OpenAI may try XML fallback.

### 5. Experimental Badge Implementation

**Location:** Two places need the badge:

**a) Chat toggle button** in `MapBuilderPage.tsx` (line ~190-203):
The MessageSquare icon button that toggles AI chat. Add a small amber badge next to or overlaying the button. Since this is a tight icon button, a small dot or badge adjacent to the tooltip text is best.

**b) Chat panel header** in `MapBuilderPage.tsx` (lines 355-356 for compact, 382 for wide):
The `<h3>` showing "AI Chat" text. Add a `<Badge>` inline after the text.

**Implementation pattern:**
```tsx
import { Badge } from '@/components/ui/badge';

// In chat panel header (both compact and wide variants):
<h3 className="text-sm font-medium">{t('aiChat')}</h3>
<Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-600 dark:text-amber-400">
  {t('chat.experimental')}
</Badge>
```

The existing `Badge` component supports `variant="outline"` which gives a bordered look. Custom amber classes match the warning pattern used elsewhere (e.g., `SettingsAITab.tsx` line 304).

For the toggle button tooltip, append the experimental note to the tooltip content.

**i18n keys needed:** Add `chat.experimental` to builder locale files (en, es, fr, de).

### 6. Admin Settings Tab is Well Built

**Assessment:** No significant issues found.
- Properly syncs from settings, tracks dirty state, handles save/discard
- Shows dimension change warning when embeddings exist
- API key status display is clear
- Semantic search toggle works independently from save flow
- `SettingSourceBadge` shows env vs DB vs default provenance

### 7. AI Availability Check is Robust

**Assessment:** `_check_ai_available()` in `router.py` properly checks:
- Admin toggle (AI_ENABLED persistent config) -- 403
- Provider-specific API key presence -- 503
- No keys at all -- 503

Frontend `useAIAvailability()` correctly gates on both `enabled` and `configured`. The builder page gates the chat button on `aiStatus?.configured && aiStatus?.enabled && can('use_ai_chat')`.

### 8. SQL Sandbox is Properly Layered (SECURITY: GOOD)

**Assessment:** The SQL execution path has proper defense-in-depth:
1. `sqlglot` AST parsing -- rejects non-SELECT, multi-statement, SELECT INTO
2. RBAC table allowlist -- only user-visible datasets
3. Schema enforcement -- all tables must be in `data.` schema
4. Read-only transaction execution with timeout and row limit
5. Additional: `_validate_chat_layers()` in router.py overwrites client-supplied table names with DB values

No SQL injection risk via the AI path.

### 9. Prompt Injection Surface (SECURITY: ACCEPTABLE)

The LLM receives user messages directly. A user could attempt prompt injection to:
- Make the LLM call tools on layers they don't own -- **mitigated** by `_validate_chat_layers()` which validates map ownership and dataset access
- Extract system prompt details -- **low impact**, system prompt contains no secrets
- Generate harmful SQL -- **mitigated** by sandbox validation

The `query_data` tool passes the user's question as a `question` field to a separate SQL-generation LLM call. The SQL generation prompt is well-constructed with clear constraints. The generated SQL goes through the sandbox before execution.

**Risk level:** Acceptable for an experimental feature. No action needed.

### 10. Missing `get_dataset_details` in Chat Tools

**Severity:** Low
**Location:** `backend/app/ai/tools.py`

The `get_dataset_details` tool schema is defined in `tools.py` (lines 47-64) but is NOT included in `CHAT_TOOLS_ANTHROPIC` list. It IS used in the map generation flow (`service.py`) but not in the chat flow. The chat system prompt provides column info directly from the layer context, so this is not a bug -- it's by design. The tool definition exists for the generate-map service, not chat.

No action needed.

### 11. Streaming Error Boundary

**Assessment:** The streaming implementation properly handles:
- Abort/cancel (AbortController)
- Stream interruption with partial actions applied
- Fallback to non-streaming on stream failure (only when no actions applied)
- Known API error codes (401, 403, 502, 503) mapped to user-friendly messages
- Progressive timeout indicators (5s, 15s, 30s)

Well implemented, no gaps found.

## Recommended Enhancements (Document Only)

These are larger improvements not worth implementing in this task:

1. **Chat history persistence:** Currently in-memory only. Refreshing the page loses all chat history. Could persist in localStorage or backend.

2. **Token usage display:** The backend logs input/output tokens but the frontend never shows cost/usage information to the user.

3. **Undo for chat actions:** When chat applies filter/style changes, there's no undo button. The user must manually revert or ask the AI to undo.

4. **Rate limiting on AI endpoints:** The AI endpoints use `require_permission("use_ai_chat")` but have no per-user rate limiting. A user could spam expensive LLM calls. Consider adding slowapi limits.

5. **Metadata assist for non-spatial tables:** The metadata service loads `geometry_type`, `srid`, spatial extent -- it will work fine for non-spatial datasets but the prompts are geospatial-focused. May want to adjust prompt language for tables.

## Action Items for Implementation

| Priority | Item | Type |
|----------|------|------|
| 1 | Add `set_opacity` tool definition to `CHAT_TOOLS_ANTHROPIC` | Bug fix |
| 2 | Add experimental badge to chat panel header (both compact/wide) | Feature |
| 3 | Add experimental badge indicator to chat toggle button tooltip | Feature |
| 4 | Add error handling (toast) to metadata mutation hooks | UX fix |
| 5 | Add i18n keys for "Experimental" in all 4 locale files | i18n |

## Sources

### Primary (HIGH confidence)
- Direct code review of all files listed in focus section
- Existing Badge component at `frontend/src/components/ui/badge.tsx`
- Existing amber warning pattern in `SettingsAITab.tsx`
