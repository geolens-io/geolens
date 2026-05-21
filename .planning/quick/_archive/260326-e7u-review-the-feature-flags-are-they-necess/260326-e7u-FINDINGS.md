# Feature Flag Review: PersistentConfig Boolean Flags

**Date:** 2026-03-26
**Scope:** All boolean PersistentConfig feature flags in GeoLens backend
**Methodology:** Source-code grep + manual verification of every usage site
**Verdict:** All 5 flags are actively used. None should be removed.

---

## Executive Summary

GeoLens defines 5 boolean feature flags as PersistentConfig entries. Each is:
- Declared in `backend/app/persistent_config.py`
- Read in at least one backend code path that gates behavior
- 4 of 5 are exposed in the admin settings UI with a toggle (`ai_send_sample_values` lacks a UI toggle)

None are dead code. None duplicate another mechanism. All serve distinct deployment scenarios.

**Recommendation: KEEP all 5 flags. No removals warranted.**

---

## Per-Flag Analysis

### 1. `registration_enabled`

| Aspect | Detail |
|--------|--------|
| **Declaration** | `persistent_config.py:239-244` -- `PersistentConfig[bool]`, tab=`auth`, default from `settings.registration_enabled` (env) |
| **Backend usage** | `auth/router.py:141` -- gates `/register` endpoint (403 if disabled); `auth/router.py:171` -- exposed via `/auth/config` public endpoint for frontend |
| **Frontend usage** | `LoginPage.tsx:105,113` -- shows/hides "Register" link based on config response; `RegisterPage.tsx:33` -- redirects to login if disabled |
| **Admin UI toggle** | `SettingsAuthTab.tsx:590,607,613-614` -- checkbox in Auth settings tab |
| **Deployment scenario** | Private instances where only admin-created accounts are allowed vs. public instances that open self-registration |
| **Duplicates?** | No -- only mechanism controlling registration access |
| **Test coverage** | `test_auth.py` tests both enabled/disabled paths |
| **Repo-split alignment** | Auth seam -- enterprise could overlay with SAML/SCIM, but the basic toggle stays in core |

**Recommendation: KEEP.** Core auth control. Every multi-user deployment needs this toggle.

---

### 2. `ai_enabled`

| Aspect | Detail |
|--------|--------|
| **Declaration** | `persistent_config.py:323-328` -- `PersistentConfig[bool]`, tab=`ai`, default=`True` |
| **Backend usage** | `ai/router.py:55` -- `_check_ai_available()` guard on all AI endpoints (403 if disabled); `embeddings/service.py:162` -- skips embedding generation when disabled |
| **Frontend usage** | `SettingsAITab.tsx:45,67,74,143-144` -- master AI toggle in admin with source badge and reset support |
| **Admin UI toggle** | `SettingsAITab.tsx` -- dedicated checkbox with label and source badge |
| **Deployment scenario** | Deployments without LLM API keys; environments where AI cost/privacy concerns require disabling; air-gapped deployments |
| **Duplicates?** | No -- the only kill switch for AI features. Distinct from missing API keys (which cause 503, not 403) |
| **Test coverage** | `test_embedding_pipeline.py` mocks it; `test_hybrid_search.py` tests AI-off + existing embeddings scenario |
| **Repo-split alignment** | AI policy seam -- enterprise overlay for model routing, allow/deny rules |

**Recommendation: KEEP.** Essential operational control. Disabling AI is a first-class deployment scenario.

---

### 3. `semantic_search_enabled`

| Aspect | Detail |
|--------|--------|
| **Declaration** | `persistent_config.py:376-381` -- `PersistentConfig[bool]`, tab=`ai`, default=`False` |
| **Backend usage** | `search/service.py:314` -- determines whether hybrid RRF search activates; `admin/router.py:455,476` -- included in AI status response for both GET and PATCH |
| **Frontend usage** | `SettingsAITab.tsx:227` -- toggle in AI tab; `AIStatusCard.tsx:52` -- shows semantic search status; `admin.ts:185` -- API call to toggle |
| **Admin UI toggle** | `SettingsAITab.tsx` -- checkbox in AI settings section |
| **Deployment scenario** | Requires pgvector + embeddings to be populated. Default off because not every deployment has vector infrastructure. Admin enables after configuring embedding model. |
| **Duplicates?** | No -- distinct from `ai_enabled`. Semantic search can be off while AI (map generation, etc.) is on. Semantic search also works when `ai_enabled` is off IF embeddings already exist. |
| **Test coverage** | `test_hybrid_search.py` tests both on/off paths, including edge case of AI-off + semantic-on |
| **Repo-split alignment** | Stays in core -- search is adoption engine, not an enterprise upsell |

**Recommendation: KEEP.** Necessary independent control. Semantic search has infrastructure prerequisites (pgvector, embeddings) that make it inappropriate to auto-enable with `ai_enabled`.

---

### 4. `require_metadata_for_publish`

| Aspect | Detail |
|--------|--------|
| **Declaration** | `persistent_config.py:293-298` -- `PersistentConfig[bool]`, tab=`general`, default=`False` |
| **Backend usage** | `datasets/service.py:441-453` -- validation gate on record status transition to "published". When true, calls `validate_record()` and blocks publish if metadata is incomplete. |
| **Frontend usage** | `DatasetPage.tsx:279` -- reads from unified settings to display validation warnings; `ValidationStatus.tsx:30` -- same pattern for status display |
| **Admin UI toggle** | `SettingsGeneralTab.tsx:22,39,45-46` -- checkbox in General settings tab with source badge |
| **Deployment scenario** | Data governance: organizations that require complete metadata (title, description, source, license) before records go public. Casual deployments leave it off. |
| **Duplicates?** | No -- the only mechanism gating publish on metadata completeness |
| **Test coverage** | `test_validation.py` tests both enabled and disabled paths |
| **Repo-split alignment** | Governance seam -- enterprise could add stricter compliance validation, but this basic toggle belongs in core |

**Recommendation: KEEP.** Clean data governance control with real operational value.

---

### 5. `ai_send_sample_values`

| Aspect | Detail |
|--------|--------|
| **Declaration** | `persistent_config.py:383-388` -- `PersistentConfig[bool]`, tab=`ai`, default=`True` |
| **Backend usage** | `ai/service.py:153-158` -- `_should_send_sample_values()` reads the flag; called at `ai/service.py:490` (map generation context), `ai/service.py:577` (map edit context), and `ai/chat_service.py:534` (chat context). When disabled, sample data values are omitted from LLM prompts. |
| **Frontend usage** | None -- backend-only control. Not consumed by any frontend component. |
| **Admin UI toggle** | **Missing** -- not exposed in `SettingsAITab.tsx`. Can only be changed via the unified settings API directly. |
| **Deployment scenario** | Privacy/compliance: organizations that don't want actual data values sent to third-party LLM providers. Particularly relevant for PII-sensitive datasets. |
| **Duplicates?** | No -- distinct from `ai_enabled`. AI can be on but sample values suppressed. |
| **Test coverage** | No dedicated tests for the toggle behavior |
| **Repo-split alignment** | AI policy seam -- enterprise could add fine-grained data masking on top of this basic toggle |

**Recommendation: KEEP.** Legitimate privacy control with active backend enforcement. However, it has two gaps (see below).

---

## Summary Table

| Flag | Active? | Admin UI? | Real Scenario? | Duplicates? | Recommendation |
|------|---------|-----------|----------------|-------------|----------------|
| `registration_enabled` | Yes | Yes | Yes | No | **KEEP** |
| `ai_enabled` | Yes | Yes | Yes | No | **KEEP** |
| `semantic_search_enabled` | Yes | Yes | Yes | No | **KEEP** |
| `require_metadata_for_publish` | Yes | Yes | Yes | No | **KEEP** |
| `ai_send_sample_values` | Yes | **No** | Yes | No | **KEEP** |

---

## Repo-Split Alignment

Per `docs/GTM/repo-split.md`, the project plans enterprise extension seams for auth, audit, settings/branding, and AI policy. The flags map as follows:

- `registration_enabled` -- auth seam (core toggle, enterprise could overlay with SAML/SCIM)
- `ai_enabled` -- AI policy seam (core toggle, enterprise adds model routing / allow-deny)
- `semantic_search_enabled` -- stays in core (search is adoption engine)
- `require_metadata_for_publish` -- governance seam (core toggle, enterprise adds compliance validation)
- `ai_send_sample_values` -- AI policy seam (core toggle, enterprise adds fine-grained data masking)

All flags are reasonable extension points. None should be removed before any repo split; they are exactly the kind of deployment/runtime flags that belong at extension seams.

---

## Identified Gaps

4 of 5 flags are fully wired (backend enforcement, frontend consumption, admin UI toggle, test coverage). `ai_send_sample_values` has two gaps:

1. **Missing admin UI toggle** -- The flag exists in the backend and is enforced in 3 code paths, but there is no toggle in `SettingsAITab.tsx` for admins to control it through the UI. It can only be changed via direct API call.
2. **Missing test coverage** -- No dedicated tests verify that disabling the flag actually suppresses sample values in LLM prompts.

---

## Optional Follow-Up Ideas

1. **Add admin UI toggle for `ai_send_sample_values`** in `SettingsAITab.tsx` -- straightforward checkbox addition consistent with the existing `ai_enabled` and `semantic_search_enabled` toggles.
2. **Add test coverage for `ai_send_sample_values`** -- verify that when disabled, `_should_send_sample_values()` returns `False` and sample values are omitted from LLM context.
3. No existing flags need removal or consolidation.
