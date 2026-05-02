---
phase: 231
slug: embedding-provider-extension-protocol
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-02
---

# Phase 231 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (`uv run pytest`) |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/test_embedding_provider_extension.py tests/test_embedding_service.py tests/test_layering.py -x -q` |
| **Full suite command** | `cd backend && uv run pytest --tb=short -q` |
| **Estimated runtime** | quick: ~5–10s · full: ~3–5 min |

---

## Sampling Rate

- **After every task commit:** Run quick command (~5–10s)
- **After every plan wave:** Run wave-merge command — `cd backend && uv run pytest tests/test_embedding_provider_extension.py tests/test_embedding_service.py tests/test_embedding_pipeline.py tests/test_hybrid_search.py tests/test_layering.py tests/test_extensions.py tests/test_ai_provider_extension.py -x -q` (~30s)
- **Before `/gsd-verify-work`:** Full suite must be green (baseline ~2050+/2050+ from STATE.md; Phase 231 adds ≥3 new tests via D-18/D-19/D-20)
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 231-01-* | 01 | 1 | EMBPROV-01 | — | Protocol class is `@runtime_checkable`, no logging of API key value | unit | `cd backend && uv run pytest tests/test_embedding_provider_extension.py::test_default_embedding_provider_registered -x` | ❌ W0 (D-18/D-19) | ⬜ pending |
| 231-01-* | 01 | 1 | EMBPROV-02 | — | Registry singleton; per-key `setdefault` cannot overwrite overlays | unit | `cd backend && uv run pytest tests/test_embedding_provider_extension.py::test_default_embedding_provider_registered -x` | ❌ W0 (D-19) | ⬜ pending |
| 231-01-* | 01 | 1 | EMBPROV-02b | — | `ValueError("Unknown embedding provider: ...")` preserved | unit | `cd backend && uv run pytest tests/test_embedding_provider_extension.py::test_unknown_embedding_provider_raises_value_error -x` | ❌ W0 (D-20) | ⬜ pending |
| 231-01-* | 01 | 1 | EMBPROV-05b | T-OVERLAY | entry_points overlay dispatched without core file changes | integration | `cd backend && uv run pytest tests/test_embedding_provider_extension.py::test_overlay_embedding_provider_is_dispatched -x` | ❌ W0 (D-18) | ⬜ pending |
| 231-02-* | 02 | 2 | EMBPROV-03 | T-SDK-IMPORT | `from openai import OpenAI` removed from `processing/embeddings/`; service routes via registry | architecture + integration | `git grep -E "^(from\|import) openai" backend/app/processing/embeddings/` returns empty `&&` `cd backend && uv run pytest tests/test_embedding_service.py -x` | ❌ helpers.py edit + D-27 mock migration | ⬜ pending |
| 231-02-* | 02 | 2 | EMBPROV-05a | — | 5 existing `test_embedding_service.py` tests stay green with provider-boundary mocks | unit | `cd backend && uv run pytest tests/test_embedding_service.py -x` (5 tests pass) | ✅ exists; mock migration per D-27 | ⬜ pending |
| 231-02-* | 02 | 2 | EMBPROV-05c | — | Service-boundary mock tests (`test_embedding_pipeline.py`, `test_hybrid_search.py`) stay green | integration | `cd backend && uv run pytest tests/test_embedding_pipeline.py tests/test_hybrid_search.py -x` | ✅ exists; UNAFFECTED per D-28 | ⬜ pending |
| 231-03-* | 03 | 3 | EMBPROV-04 | T-ARCH-GUARD | Renamed guard catches reintroduced SDK imports anywhere in `processing/` | architecture | `cd backend && uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing -x` | ✅ exists as `_in_processing_ai`; rename per D-13 | ⬜ pending |
| 231-03-* | 03 | 3 | EMBPROV-04b | T-NEG-CONTROL | Negative-control: temporarily reintroducing `from openai import OpenAI` in `helpers.py` causes the renamed test to fail with the offending line surfaced | architecture (manual) | Manual: insert `from openai import OpenAI` at top of `helpers.py`, run `cd backend && uv run pytest tests/test_layering.py -k architecture`, confirm fail, revert | manual per D-15 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_embedding_provider_extension.py` — new file; covers EMBPROV-01, EMBPROV-02, EMBPROV-02b, EMBPROV-05b (D-18/D-19/D-20). Mirrors `backend/tests/test_ai_provider_extension.py` shape.
- [ ] `backend/tests/test_layering.py` rename — `test_no_module_level_provider_sdk_imports_in_processing_ai` → `test_no_module_level_provider_sdk_imports_in_processing` (D-13/D-14/D-16). Removes the carve-out paragraph at lines 789-792; pathspec broadens from `backend/app/processing/ai/` to `backend/app/processing/`.
- [ ] `backend/tests/test_embedding_service.py` mock migration — 5 tests update from `patch("app.processing.embeddings.service.build_openai_client")` to `patch("app.processing.embeddings.service.get_embedding_provider")` returning a mock provider whose `embed()` returns the fake vector (D-27). Mechanical migration; no behavior change.
- [x] No new pytest framework / config files needed; `architecture` marker already registered at `backend/pyproject.toml:74`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Negative-control: architecture-guard test catches a reintroduced `from openai` import | EMBPROV-04b | Test must be reverted after the demonstration; cannot be automated without permanent test artifact | 1) Edit `backend/app/processing/embeddings/helpers.py` adding `from openai import OpenAI` at the top. 2) Run `cd backend && uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing -x`. 3) Confirm test FAILS with `Module-level provider-SDK import found in backend/app/processing/.` and the offending line surfaced. 4) Revert the edit. 5) Confirm test PASSES. (D-15) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (per-task map above)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (architecture-guard rename is the only manual-leaning task and is bracketed by automated coverage on either side)
- [ ] Wave 0 covers all MISSING references (`test_embedding_provider_extension.py` new; `test_layering.py` renamed; `test_embedding_service.py` mock-migrated)
- [ ] No watch-mode flags (all commands use `-x -q`, no `--watch`)
- [ ] Feedback latency < 30s per wave merge (~5–10s per task commit)
- [ ] `nyquist_compliant: true` set in frontmatter once all Wave 0 tasks are written and the per-task map is fully assigned

**Approval:** pending
