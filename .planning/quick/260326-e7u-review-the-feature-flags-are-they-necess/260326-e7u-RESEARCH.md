# Quick Task 260326-e7u: Feature Flag Review - Research

**Researched:** 2026-03-26
**Domain:** PersistentConfig boolean feature flags
**Confidence:** HIGH

## Summary

All 5 boolean feature flags are actively consumed in both backend and frontend, exposed in the admin settings UI, and serve distinct operational purposes. None are dead code. Each gates a real deployment scenario. No flag duplicates another mechanism.

**Primary recommendation:** Keep all 5 flags. No removals warranted under the conservative criteria.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Evaluate each flag for value vs. complexity
- Only recommend removal if literally unused or duplicates another mechanism
- Conservative bar -- do not remove flags with legitimate deployment scenarios
- Recommendation doc only, no code changes

### Claude's Discretion
- Doc format and structure
- Depth of tracing per flag

### Deferred Ideas (OUT OF SCOPE)
None specified.

</user_constraints>

## Flag-by-Flag Analysis

### 1. `registration_enabled` (default: from env, typically `False`)

| Aspect | Finding |
|--------|---------|
| **Backend reads** | `auth/router.py:144` -- gates `/register` endpoint (403 if disabled); `auth/router.py:174` -- exposed via `/auth/config` public endpoint |
| **Frontend reads** | `LoginPage.tsx:109,117` -- shows/hides "Register" link; `RegisterPage.tsx:35` -- redirects away if disabled |
| **Admin UI toggle** | Yes -- `SettingsAuthTab.tsx:614` (checkbox in Auth settings tab) |
| **Deployment scenario** | Private instances where only admin-created accounts are allowed; public instances that open registration |
| **Duplicates?** | No -- only mechanism controlling registration access |
| **Tests** | `test_auth.py` tests both enabled/disabled paths |
| **Repo-split alignment** | Auth seam -- enterprise could overlay with SAML/SCIM, but the basic toggle stays in core |

**Verdict: KEEP.** Core auth control. Every multi-user deployment needs this toggle.

---

### 2. `ai_enabled` (default: `True`)

| Aspect | Finding |
|--------|---------|
| **Backend reads** | `ai/router.py:55` -- `_require_ai()` guard on all AI endpoints (403 if disabled); `embeddings/service.py:162` -- skips embedding generation when disabled |
| **Frontend reads** | `SettingsAITab.tsx:52,124` -- master AI toggle in admin; `AIStatusCard.tsx` reads status |
| **Admin UI toggle** | Yes -- `SettingsAITab.tsx` checkbox + dedicated `PATCH /admin/ai-status/` endpoint |
| **Deployment scenario** | Deployments without LLM API keys; environments where AI cost/privacy concerns require disabling; air-gapped deployments |
| **Duplicates?** | No -- the only kill switch for AI features. Distinct from missing API keys (which cause 503, not 403) |
| **Tests** | `test_embedding_pipeline.py` mocks it extensively; `test_hybrid_search.py` tests AI-off + existing embeddings scenario |
| **Repo-split alignment** | AI policy seam -- enterprise overlay for model routing, allow/deny rules |

**Verdict: KEEP.** Essential operational control. Disabling AI is a first-class deployment scenario (no API keys, cost control, privacy).

---

### 3. `semantic_search_enabled` (default: `False`)

| Aspect | Finding |
|--------|---------|
| **Backend reads** | `search/service.py:781` -- determines whether hybrid RRF search activates; `admin/router.py:472,493` -- included in AI status response |
| **Frontend reads** | `AIStatusCard.tsx:52` -- shows semantic search status; `SettingsAITab.tsx:200` -- toggle in AI tab; `admin/admin.ts:191` -- API call to toggle |
| **Admin UI toggle** | Yes -- in AI settings tab |
| **Deployment scenario** | Requires pgvector + embeddings to be populated. Default off because not every deployment has vector infrastructure. Admin enables after configuring embedding model. |
| **Duplicates?** | No -- distinct from `ai_enabled`. Semantic search can be off while AI (map generation, etc.) is on. Also, semantic search works even when `ai_enabled` is off IF embeddings already exist (tested in `test_hybrid_search.py:321`). |
| **Tests** | `test_hybrid_search.py` tests both on/off paths, including edge case of AI-off + semantic-on |
| **Repo-split alignment** | Stays in core (search is adoption engine) |

**Verdict: KEEP.** Necessary independent control. Semantic search has infrastructure prerequisites (pgvector, embeddings) that make it inappropriate to auto-enable with `ai_enabled`.

---

### 4. `require_metadata_for_publish` (default: `False`)

| Aspect | Finding |
|--------|---------|
| **Backend reads** | `datasets/service.py:446` -- validation gate on record status transition to "published". When true, calls `validate_record()` and blocks publish if metadata is incomplete. |
| **Frontend reads** | `DatasetPage.tsx:279` -- reads from unified settings to display validation warnings; `ValidationStatus.tsx:30` -- same pattern |
| **Admin UI toggle** | Yes -- `SettingsGeneralTab.tsx:45` (checkbox in General settings tab) |
| **Deployment scenario** | Data governance: organizations that require complete metadata (title, description, source, license, etc.) before records go public. Casual deployments leave it off. |
| **Duplicates?** | No -- the only mechanism gating publish on metadata completeness |
| **Tests** | `test_validation.py:230,432` tests both enabled and disabled paths |
| **Repo-split alignment** | Governance seam -- enterprise could add stricter compliance validation, but this basic toggle belongs in core |

**Verdict: KEEP.** Clean data governance control with real operational value.

---

### 5. `ai_send_sample_values` (default: `True`)

| Aspect | Finding |
|--------|---------|
| **Backend reads** | `ai/service.py:156-158` -- `_should_send_sample_values()` determines whether actual data samples are included in LLM prompts for map generation |
| **Frontend reads** | Not directly consumed in frontend UI (no toggle visible in settings tabs from grep) |
| **Admin UI toggle** | Exposed via unified settings API (it is a PersistentConfig with `tab="ai"`, so it appears in the `GET /settings/all/` response and can be toggled via `PUT /settings/`). However, no dedicated UI checkbox was found in `SettingsAITab.tsx`. |
| **Deployment scenario** | Privacy/compliance: organizations that want AI map generation but cannot send actual data values to third-party LLMs. Disabling sends schema-only context to the LLM. |
| **Duplicates?** | No -- finer-grained than `ai_enabled` (AI stays on, but data exposure is limited) |
| **Tests** | No dedicated test found for this flag's behavior |

**Verdict: KEEP, but note gaps.** The privacy use case is legitimate and the flag works. Two gaps worth noting:
1. No dedicated admin UI toggle in `SettingsAITab.tsx` (only accessible via the raw unified settings API)
2. No test coverage for the behavior change when disabled

These are polish items, not reasons to remove the flag.

---

## Summary Table

| Flag | Active? | Admin UI? | Real Scenario? | Duplicates? | Recommendation |
|------|---------|-----------|----------------|-------------|----------------|
| `registration_enabled` | Yes | Yes | Yes | No | **KEEP** |
| `ai_enabled` | Yes | Yes | Yes | No | **KEEP** |
| `semantic_search_enabled` | Yes | Yes | Yes | No | **KEEP** |
| `require_metadata_for_publish` | Yes | Yes | Yes | No | **KEEP** |
| `ai_send_sample_values` | Yes | Partial | Yes | No | **KEEP** (add UI toggle + test) |

## Repo-Split Alignment

Per `docs/GTM/repo-split.md`, the planned enterprise extension seams are: auth, audit, settings/branding, ai policy. The flags map as follows:

- `registration_enabled` -- auth seam (core toggle, enterprise adds SAML/SCIM overlay)
- `ai_enabled` / `ai_send_sample_values` -- ai policy seam (core toggles, enterprise adds model routing / allow-deny)
- `semantic_search_enabled` -- stays in core (search is adoption engine)
- `require_metadata_for_publish` -- governance seam (core toggle, enterprise adds compliance validation)

All flags are reasonable extension points. None should be removed before the repo split; they are the exact kind of "deployment/runtime flags" the repo-split doc identifies as a priority seam.

## Suggested Follow-Up (Optional)

1. **Add `ai_send_sample_values` toggle to `SettingsAITab.tsx`** -- currently only accessible via raw settings API
2. **Add test for `ai_send_sample_values`** -- verify that disabling it actually omits sample values from LLM prompts
3. No flags need removal or consolidation

## Sources

- `backend/app/persistent_config.py` -- all 5 flag declarations
- `backend/app/auth/router.py` -- registration_enabled usage
- `backend/app/ai/router.py`, `backend/app/ai/service.py` -- ai_enabled, ai_send_sample_values usage
- `backend/app/embeddings/service.py` -- ai_enabled embedding gate
- `backend/app/search/service.py` -- semantic_search_enabled usage
- `backend/app/datasets/service.py` -- require_metadata_for_publish usage
- `frontend/src/components/admin/settings/` -- all admin UI toggles
- `docs/GTM/repo-split.md` -- enterprise extension seam strategy
