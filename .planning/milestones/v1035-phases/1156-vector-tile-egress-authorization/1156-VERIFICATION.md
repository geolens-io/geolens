---
phase: 1156-vector-tile-egress-authorization
verified: 2026-05-30T17:31:03Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
human_verification:
  - test: "Anonymous GET /tiles/{table}/{z}/{x}/{y}.pbf on a live public-unpublished dataset returns 404 (not 200 + bytes)"
    expected: "HTTP 404, no MVT bytes delivered"
    why_human: "Live end-to-end path through the running API cannot be verified by grep/import. The regression test covers it programmatically but the live-MCP QA-01 gate (REQUIREMENTS.md line 43) explicitly requires orchestrator-driven Playwright MCP verification of this surface before tagging."
  - test: "Anonymous GET /tiles/token/{id}/ on a live public-unpublished dataset returns 404 (not 200 + HMAC sig)"
    expected: "HTTP 404 with body {detail: 'Dataset not found'}"
    why_human: "Same reason — part of the QA-01 close-gate list. Programmatic regression test passes; live verification required by the milestone gate."
---

# Phase 1156: Vector-Tile Egress Authorization Verification Report

**Phase Goal:** Anonymous callers can no longer obtain MVT feature data or a valid HMAC tile token for a `public`-but-not-`published` (draft/ready/internal) vector dataset — the vector path now enforces the same `visibility=='public' AND record_status=='published'` contract as raster.
**Verified:** 2026-05-30T17:31:03Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | An anonymous `GET /tiles/{table}/{z}/{x}/{y}.pbf` request for a public-unpublished vector dataset returns 401/404 (today returns 200 + 1842 bytes of feature data). | ✓ VERIFIED | `_authorize_vector_tile_request` (router.py:1103-1117) raises `HTTP_404_NOT_FOUND` when `meta.record_status != "published"` and `user is None`; `tile_endpoint` threads `user` (router.py:1302, 1330). `test_anon_raw_pbf_denied_for_public_unpublished` pins this path with a real PostGIS backing table, asserts `== 404`. |
| 2  | An anonymous `GET /tiles/token/{id}/` and the batch-token endpoint for a public-unpublished dataset return 401/404 instead of minting a valid HMAC token. | ✓ VERIFIED | `_enforce_tile_token_access` (router.py:835-874) raises `HTTP_404_NOT_FOUND` for `public + record_status != "published" + user is None`; both `get_tile_token` (line 909) and `get_tile_tokens_batch` (line 976) call it. No HMAC minted for the denied case. `test_anon_single_token_denied_for_public_unpublished` and `test_anon_batch_token_denied_for_public_unpublished` both pass. |
| 3  | Clustered point tiles (`cluster_tile_endpoint`) inherit the same status-aware denial. | ✓ VERIFIED | `cluster_tile_endpoint` calls `_authorize_vector_tile_request(... user=user)` (router.py:1181-1189) after `_ensure_clusterable_dataset`. With a real Point backing table `test_anon_cluster_tile_denied_for_public_unpublished` asserts `== 404` (auth gate fires before MVT query). |
| 4  | A public+published vector dataset still serves tiles + tokens to anonymous callers (no over-gating regression); owner/admin/embed-token paths unchanged. | ✓ VERIFIED | `_enforce_tile_token_access` returns `None` (allows) when `record.record_status == "published"`. `_authorize_vector_tile_request` returns `"public"` on the same branch. `test_anon_single_token_allowed_for_public_published` asserts 200+`sig`; `test_anon_raw_pbf_allowed_for_public_published` asserts 200 + non-empty bytes. Embed-token short-circuit (router.py:1076-1086) and non-public HMAC branch (router.py:1088-1102) are structurally unchanged. |
| 5  | A regression test pins the anonymous tile-token + `.pbf` denial on a public-unpublished dataset. | ✓ VERIFIED | `backend/tests/test_vector_tile_auth.py` — 349 lines, class `TestVectorTileEgressAuthorization`, 6 tests. Covers single token denial, batch token denial, raw `.pbf` denial (real backing table — pinning the exact 1842-byte leak path), cluster `.pbf` denial (real backing table — pins `_authorize_vector_tile_request` auth gate, not the earlier clusterable gate), and two positive over-gating guards. `pytest` is live-used (fixture + mark.usefixtures). |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/processing/tiles/router.py` | Status-aware vector-tile authorization across all five entry points | ✓ VERIFIED | `_DatasetMeta` fields `record_status`+`created_by` present (lines 85-86); `_resolve_dataset_meta` populates both (lines 1052-1053); `_enforce_tile_token_access` helper (lines 835-874) wired to both token endpoints; `_authorize_vector_tile_request` status gate (lines 1103-1117) wired to both `.pbf` call sites. Module imports cleanly (confirmed at runtime). |
| `backend/tests/test_vector_tile_auth.py` | Regression coverage for SEC-01 | ✓ VERIFIED | File exists, 349 lines (exceeds min 80). Class `TestVectorTileEgressAuthorization` with 6 test methods. Contains `record_status` references. Uses real PostGIS point backing tables to reach the auth gate on `.pbf` paths. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_resolve_dataset_meta` | `_DatasetMeta.record_status / _DatasetMeta.created_by` | `record_status=dataset.record.record_status` / `created_by=dataset.record.created_by` (eager-loaded joinedload) | ✓ WIRED | router.py:1052-1053; both substrings confirmed by grep (1 match each) |
| `_authorize_vector_tile_request` | `meta.record_status` | public-branch status guard `record_status != "published"` (lines 1103-1117) | ✓ WIRED | Exact pattern `meta.record_status != "published"` at line 1105; raises 404 for anon (line 1108-1110), 404 for non-owner non-admin (line 1114-1117) — mirrors raster lines 469-480 |
| `get_tile_token` / `get_tile_tokens_batch` | `_enforce_tile_token_access` | Single `await _enforce_tile_token_access(db, dataset, dataset_id, user, port)` call (lines 909, 976) | ✓ WIRED | `check_dataset_access_or_anonymous` import is fully removed (0 occurrences); replaced by `_enforce_tile_token_access` which correctly returns 401 for non-public+anon (preserving pre-existing contract) and 404 for public+unpublished+anon (new SEC-01 gate) |
| `cluster_tile_endpoint` / `tile_endpoint` | `_authorize_vector_tile_request` with `user=user` | `user: Identity | None = Depends(get_optional_user)` in both endpoint signatures; `user=user` passed at call sites (router.py:1188, 1330) | ✓ WIRED | Confirmed by runtime `inspect.signature` check: all three functions have `user` parameter |
| `test_vector_tile_auth.py` | `GET /tiles/token/`, `POST /tiles/tokens/`, `GET /tiles/clusters/...pbf`, `GET /tiles/data...pbf` | AsyncClient requests with no auth header (anonymous) | ✓ WIRED | All four endpoint patterns exercised; `_get_auth_header` is defined but never called inside `TestVectorTileEgressAuthorization` — all requests are truly anonymous |

### Data-Flow Trace (Level 4)

Not applicable. These are authorization control-flow paths, not data-rendering components. The relevant "data" is whether a denial exception is raised — which is verified by the regression tests and the code inspection above.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `_DatasetMeta` carries `record_status` and `created_by` | `python -c "from app.processing.tiles.router import _DatasetMeta; assert 'record_status' in _DatasetMeta._fields and 'created_by' in _DatasetMeta._fields; print('OK', _DatasetMeta._fields)"` | `OK ('dataset_id', 'record_id', 'table_name', 'visibility', 'record_status', 'created_by', ...)` | ✓ PASS |
| `user` threaded through `_authorize_vector_tile_request`, `cluster_tile_endpoint`, `tile_endpoint` | `python -c "import inspect; from app.processing.tiles.router import _authorize_vector_tile_request as f, cluster_tile_endpoint as c, tile_endpoint as t; assert 'user' in inspect.signature(f).parameters; assert 'user' in inspect.signature(c).parameters; assert 'user' in inspect.signature(t).parameters; print('OK')"` | `OK: user threaded through all three` | ✓ PASS |
| Module imports without error | `python -c "import app.processing.tiles.router; print('module imports OK')"` | `module imports OK` | ✓ PASS |
| `check_dataset_access_or_anonymous` fully removed from router.py | `grep -c "check_dataset_access_or_anonymous" backend/app/processing/tiles/router.py` | `0` | ✓ PASS |
| `record_status != "published"` gate present in both vector surfaces (token + .pbf) | `grep -c "record_status != .published" backend/app/processing/tiles/router.py` | `4` (lines 440, 469 = raster; 865 = token helper; 1105 = .pbf helper) | ✓ PASS |

### Probe Execution

No probe scripts (`scripts/*/tests/probe-*.sh`) are declared in the plan or exist for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SEC-01 | 1156-01-PLAN.md, 1156-02-PLAN.md | Anonymous callers denied MVT + HMAC tokens for public+unpublished vector datasets | ✓ SATISFIED | All five entry points gated; regression test with 6 cases passes; REQUIREMENTS.md traceability table marks Phase 1156 / SEC-01 as Complete |

No orphaned requirements: the REQUIREMENTS.md traceability table assigns all other requirements (BLDR-*, EXP-*, MAPS-*, API-*, HYG-*, QA-01) to later phases (1157–1160). Only SEC-01 is mapped to Phase 1156.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| No blocker-level markers found | — | Scanned both modified files for `TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER` | — | None |

One note: the REVIEW.md (code review) documents that WR-01 (cluster test false-positive pass) and WR-02 (raw `.pbf` path uncovered) were active at review time — both were resolved inline by commit `c3e29cd7`, which added real PostGIS point backing tables to reach the actual auth gate. The current test file reflects the post-review strengthened state.

### Human Verification Required

The automated regression tests pass (6 tests, confirmed by the orchestrator and structurally verified here). The phase goal is technically achieved in the codebase. However, the milestone's own QA gate (REQUIREMENTS.md QA-01, to be executed in Phase 1160) requires orchestrator-driven live Playwright MCP verification of the SEC-01 surface before tagging. This is a milestone-level close-gate, not a gap in this phase's implementation.

### 1. Live Anonymous Vector-Tile Denial (SEC-01 smoke)

**Test:** With the API running, make an anonymous `GET /api/tiles/token/{id}/` request for a known public-but-unpublished dataset (e.g., flip `record_status` to `"internal"` on any existing public dataset, request the token endpoint, then restore).
**Expected:** HTTP 404 with `{"detail": "Dataset not found"}`. No HMAC `sig` in the response body.
**Why human:** Live MCP end-to-end path through the running API+DB, required by REQUIREMENTS.md QA-01. The regression test passes against the test DB; the live check confirms no misconfiguration or startup-state difference.

### 2. Live Anonymous Raw `.pbf` Denial

**Test:** Same setup — anonymous `GET /api/tiles/data.{table_name}/0/0/0.pbf` for the public+internal dataset.
**Expected:** HTTP 404, zero bytes.
**Why human:** Same QA-01 gate rationale. This was the original 1842-byte leak path; confirming it live is the intended close-gate verification before tagging v1035.

## Gaps Summary

No gaps. All five implementation truths are verified in the codebase:

- `_DatasetMeta` carries `record_status` and `created_by` (runtime-confirmed).
- `_enforce_tile_token_access` correctly mirrors `_resolve_raster_access`: non-public+anon → 401; public+unpublished+anon → 404; public+published → allow.
- `_authorize_vector_tile_request` has the `record_status != "published"` gate on the public branch, mirroring raster lines 465-479 exactly.
- Both `.pbf` call sites (`tile_endpoint`, `cluster_tile_endpoint`) inject `user` via `Depends(get_optional_user)` and pass `user=user`.
- The regression test covers the token path (single + batch), the literal `.pbf` leak path (real backing table), the cluster `.pbf` path (real backing table), and two positive over-gating guards. Code-review findings WR-01/WR-02/IN-01 were all resolved inline before the phase was submitted for verification.

The two items in "Human Verification Required" are live-smoke checks that belong to the Phase 1160 QA-01 close-gate — not gaps in this phase's implementation.

---

_Verified: 2026-05-30T17:31:03Z_
_Verifier: Claude (gsd-verifier)_
