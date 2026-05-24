# Phase 1098: OOS Triad Closure - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Retire the 3 long-carried sequential pytest failures so the post-v1023 invariant becomes `sequential failed == 0` literal (not "0 NEW failed"). Test-infra hygiene only — smallest-milestone charter applies (no production-code refactors beyond targeted fixes).

**Confirmed failure shapes** (verified via local repro at discuss time, 2026-05-24):

1. **OOS-01** — `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap`
   - `backend/app/modules/catalog/maps/router.py` = **1807 lines > cap 1800** (7 LOC over)
   - LOC cap history: `1500 → 1700 → 1800` (raised at Phase 276 CODE-01 baseline → v1013 Phase 1060 CTRL-01 close-gate carve-out). Each raise documented "decomposition queued for next phase" — never happened.
   - Test docstring explicitly calls decomposition "preferred" over cap-raise.

2. **OOS-02** — `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact`
   - Asserts README contains "signature stories include:" section + "Manhattan Skyline" canary + 9+ bullets.
   - Section was **intentionally removed in commit `4a7d1a29` ("chore: remove demo overlay apparatus", 2026-05-22)** along with the themed-demo docker overlay + 9 themed map fixtures + `GEOLENS_DEMO_MODE` flag.
   - Test became stale debris of an intentional cleanup. Demo apparatus is gone by design.
   - **8 sibling tests in same file still pass** — only this one asserts a dead invariant.

3. **OOS-03** — `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook`
   - **Passes in isolation**; fails in full sequential pytest; "did not fire" under `-n 4` (flake-class per `PYTEST-XDIST-PERF-v1020.md` Section 2).
   - Test asserts identity (`_revalidate_redirect in client._event_hooks["response"]`) — brittle to any sibling test that monkey-patches `app.modules.catalog.sources.security.*`.
   - Production code at `backend/app/modules/catalog/sources/security.py:107-112` is **correct** — `make_safe_client()` still wires `_revalidate_redirect` into `event_hooks`. SSRF posture has NOT changed.
   - Many sibling tests use `mock.patch("app.modules.catalog.sources.security.validate_url_for_ssrf", ...)` but don't directly touch `_revalidate_redirect`. The contamination source is not obvious from static grep — would require bisect to find.

**Out-of-scope reaffirmations** (from REQUIREMENTS.md):
- Production-code refactors beyond OOS-03's defensive test rewrite + OOS-01's optional LOC trim.
- New retry envelopes / engine wrappers / fixture-isolation surfaces (v1022 closed those).
- Migrations.
- OAuth flakes (Phase 1099).
- CI live-verify (Phase 1100).

</domain>

<decisions>
## Implementation Decisions

### OOS-01 fix shape — hybrid trim-first

- **D-01:** Plan attempts mechanical cleanup of `backend/app/modules/catalog/maps/router.py` first (long docstrings, unused imports, redundant comment blocks, dead code) targeting `-8 LOC` to land at `<=1799` (under the existing 1800 cap). NO behavior change, NO endpoint changes, NO signature changes — purely textual reduction.
- **D-02:** **Fallback (only if trim falls short):** raise cap to **1850** with HARD rationale comment in `test_layering.py` allowlist: *"This is the last raise; if `maps/router.py` regrows past 1850, v1024+ MUST decompose the module per Phase 226/238/252 facade-pattern."* Plus promote `Phase 999.x: maps/router.py decomposition` to `.planning/ROADMAP.md` backlog.
- **D-03:** Full decomposition (facade + sub-routers) is **out of scope** for v1023 — would bloom the smallest-milestone hygiene charter. Documented as the natural v1024+ work if the cap raises again.

### OOS-02 fix shape — remove the test

- **D-04:** **Delete** `test_readme_signature_maps_list_intact` from `backend/tests/test_phase_275_readme_accuracy.py` entirely.
- **D-05:** Rationale (inline at deletion site in SUMMARY.md, NOT as a residual comment in the test file): *"Removed 2026-05-24 — the API-04/M-23 invariant this pinned (themed-demo signature-maps in README) was retired in commit 4a7d1a29 ('remove demo overlay apparatus', 2026-05-22). 8 sibling tests in this file still pin load-bearing README invariants (utf8, FR accents, badge, cold-build-time, examples-manifests directory)."*
- **D-06:** **No README content change** (don't restore the signature-stories section). The demo apparatus removal was intentional cleanup; restoring docs to reference stranded fixtures would be a doc-lying regression.
- **D-07:** Sibling tests in the same file are NOT swept for staleness — they all pass and pin real invariants per discuss-time spot-check.

### OOS-03 fix layer — defensive behavioral rewrite

- **D-08:** Replace the identity check (`_revalidate_redirect in client._event_hooks["response"]`) with a **behavioral assertion**:
  - Spin up a `make_safe_client()` instance.
  - Construct an `httpx.Response` simulating a `302` redirect with `Location` pointing to a private IP (e.g., `http://127.0.0.1/internal`).
  - Assert `SSRFError` is raised when the response flows through the client's hook pipeline.
- **D-09:** This tests the SSRF-revalidation **contract** (the client refuses to follow a 3xx redirect to a private IP) rather than the **wiring** (function-identity in a private list). Immune to any monkey-patching of the `security` module — the test now exercises behavior end-to-end.
- **D-10:** **Do NOT hunt for the leaker.** Bisecting 70+ test files for the contamination source is high-effort and the defensive rewrite makes the leaker irrelevant. Document the brittleness root cause inline in SUMMARY.md (test was checking WIRING, not BEHAVIOR; identity checks are brittle to module-level mock.patch contamination).
- **D-11:** Preserve `follow_redirects is True` + `max_redirects == 5` assertions if cheap to keep — these are still wiring checks but they're checking CONSTRUCTOR ARGS, not patchable module attributes, so they're not flake-prone. Optional — drop if they complicate the behavioral test.

### Plan structure — 1 plan / 3 atomic edits / 1 verify gate

- **D-12:** **Plan 1098-01: OOS Triad Closure** — single plan, 5-6 tasks:
  - T1: Pre-flight (re-confirm pin line numbers via `git grep`; spot-check stack health).
  - T2: OOS-01 trim attempt → measure → cap-raise + backlog fallback if needed.
  - T3: OOS-02 test deletion + commit message rationale.
  - T4: OOS-03 behavioral rewrite.
  - T5: Verify gate — sequential `pytest` reports `3063+ passed / 0 failed / 38 skipped` (literal zero — no OOS rows) + `-n 4` reports `3063+ passed / 0 failed / 38 skipped` (literal zero) + `-n auto` 3-run measurement table shows `≤30` distinct (failed+errors) per run + zero `InvalidCatalogNameError` cascade frames (PARA-01 preservation).
  - T6: Atomic commit + flip REQUIREMENTS.md OOS-01/OOS-02/OOS-03 `[ ]` → `[x]` + Pending → Complete in same commit as SUMMARY.md (per v1019 TD-13 traceability rule).
- **D-13:** Matches Phase 1096 precedent (1 plan / 4 sub-items / shared measurement gate). File-disjoint surfaces — no contention between OOS sub-edits.
- **D-14:** Verify-gate wallclock budget: ~9 min sequential + ~6 min `-n 4` + ~22 min `-n auto` 3-run (~7 min/run) = ~37 min total. Single gate amortized vs 3× gate cost (~111 min) if split into 3 plans.

### Meta-instruction — autonomous lifecycle

- **D-15:** User directive: **`/gsd-autonomous` + Playwright MCP** for full v1023 lifecycle (Phase 1098 → 1099 → 1100 → audit → complete → cleanup). Downstream orchestration:
  - Use `--use-playwright-mcp` for any browser-driven verification (e.g., Phase 1100 close-gate health spot-check at `http://localhost:8080`).
  - Autonomous-mode-safe choices preferred at every fork (e.g., D-01's trim-with-fallback over decompose; D-08's behavioral rewrite over leaker-hunt).
  - All 3 phases of v1023 should chain without manual checkpoints unless the autonomous loop hits a genuine deviation.

### HARD INVARIANTS (carried from v1019 TD-13)

- **D-16:** Sequential pytest `failed == 0` is non-negotiable. v1098 close target: **literal** zero (no OOS rows), not "0 NEW".
- **D-17:** REQ citation pinning: planner MUST validate `path::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plan commits. Applies to all 3 OOS pins:
  - `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` (line 833)
  - `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` (line 116) — REMOVED post-fix
  - `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` (line 100) — REWRITTEN post-fix
- **D-18:** Traceability flip: executor MUST flip `REQUIREMENTS.md` OOS-01/02/03 `[ ]` → `[x]` + `Pending` → `Complete` in the SAME commit as `1098-01-SUMMARY.md`.

### Claude's Discretion

- Specific LOC reduction technique for OOS-01 trim (whether to delete dead imports first, collapse multi-line docstrings, remove explanatory comment paragraphs, etc.) — planner picks the lowest-risk shape.
- Exact private IP / 3xx test fixture shape for OOS-03 behavioral test — planner mirrors existing `tests/test_ssrf_redirect.py` test patterns (e.g., `test_redirect_to_private_ip_blocked` at line 22).
- Whether to keep or drop the `follow_redirects is True` + `max_redirects == 5` constructor-arg assertions in OOS-03 (D-11 says optional).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements + roadmap

- `.planning/REQUIREMENTS.md` — v1023 milestone requirements. OOS-01/02/03 acceptance criteria. Hard invariants (sequential `failed == 0` literal). Out-of-scope reaffirmations.
- `.planning/ROADMAP.md` §"Phase 1098" — phase goal + success criteria + dependency map.
- `.planning/STATE.md` — v1023 starting baselines (sequential 3060/3 OOS/38; `-n 4` 3059/4 OOS+oauth/38).

### v1022 close-gate evidence (the OOS triad source-of-truth)

- `.planning/milestones/v1022-phases/1097-live-verify-close-gate/1097-01-CLOSE-GATE.md` — verbatim sequential + `-n 4` + `-n auto` baselines that defined the OOS triad. Section "CLOSE-01 (a)" lists the 3 OOS pin paths exactly. Section "CLOSE-01 (b)" notes `test_ssrf_redirect` "did not fire under `-n 4` this run (flake-class behavior)".
- `.planning/audits/PYTEST-XDIST-PERF-v1020.md` §2 — flake taxonomy (referenced by close-gate for OOS-03 classification + Phase 1099 OAuth flakes).

### OOS-01 — LOC cap test

- `backend/tests/test_layering.py:833-884` — `test_router_orchestrator_modules_stay_within_loc_cap` source. Allowlist comment block at line 851-867 documents the cap-raise history (1500→1700→1800).
- `backend/app/modules/catalog/maps/router.py` — the 1807-LOC file being trimmed.

### OOS-02 — README accuracy test

- `backend/tests/test_phase_275_readme_accuracy.py:116-134` — `test_readme_signature_maps_list_intact` source (to be deleted).
- Commit `4a7d1a29` ("chore: remove demo overlay apparatus", 2026-05-22) — the intentional removal that made this test stale. Diff: 51 files / -4882 lines / +61 lines. Mentions surgical test edits to `test_phase_272_compose.py`, `test_phase_275_compose_alignment.py`, and `test_phase_275_demo_cluster.py` but missed `test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact`.
- `README.md` — current state (NO signature-stories section). Do NOT modify.

### OOS-03 — SSRF flake test

- `backend/tests/test_ssrf_redirect.py:100-108` — `test_make_safe_client_has_event_hook` source (to be rewritten behaviorally).
- `backend/tests/test_ssrf_redirect.py:22-97` — existing behavioral test patterns to mirror (`test_redirect_to_private_ip_blocked`, `test_redirect_to_link_local_blocked`, etc.). Already use the `_revalidate_redirect`-via-mock-httpx.Response pattern.
- `backend/app/modules/catalog/sources/security.py:70-112` — production `_revalidate_redirect` + `make_safe_client` definitions. Read-only; SSRF posture is correct.
- `backend/app/modules/catalog/sources/security.py:107-112` — the exact `httpx.AsyncClient(event_hooks={"response": [_revalidate_redirect]}, ...)` construction the test is meant to validate.

### Project conventions (carried)

- `.planning/PROJECT.md` — project-level patterns.
- v1019 TD-13 rules (REQ citation pinning + traceability flip) — documented in `.planning/STATE.md` "Accumulated Context > Decisions" and in 3 global GSD skill files; load-bearing for executor commits.
- Atomic-N-file commit pattern (carried from v1010+ closes).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **Behavioral SSRF test pattern** (`tests/test_ssrf_redirect.py:22-97`) — 6 existing async tests already exercise `_revalidate_redirect` directly with constructed `httpx.Response` objects. OOS-03 rewrite can mirror this shape exactly (use `make_safe_client()` as the client + drive a 3xx through `_event_hooks` invocation OR just call `_revalidate_redirect` after `make_safe_client()` is constructed).
- **LOC cap allowlist pattern** (`test_layering.py:851-867`) — explicit per-file entries with inline rationale comments. OOS-01 fallback can extend this exact pattern with a new comment block dated 2026-05-24.
- **`git grep` pin validation idiom** — used by every v1019+ planner per TD-13. Already documented; planner reuses verbatim.

### Established Patterns

- **Hygiene-milestone fix shape** (v1018 / v1019 / v1020-v1022) — atomic per-finding edits + single shared verify-gate at plan close. Phase 1096 (4 sub-items, 1 plan) is the closest precedent.
- **`pytest.mark.architecture` marker** (`test_layering.py:832`) — OOS-01 test is architecture-tagged; runs in the default `pytest` invocation (no opt-out in CI). Do not change marker.
- **Sibling-test sweep restraint** (Phase 1018 TD-01 / TD-07 precedent) — when one test in a file is stale, only that test is removed; sibling tests stay untouched unless they also fail. OOS-02 follows this — 8 siblings pass, leave them.

### Integration Points

- **REQUIREMENTS.md flip site:** `.planning/REQUIREMENTS.md` lines 76-83 (Traceability table). OOS-01, OOS-02, OOS-03 rows flip `Pending` → `Complete` atomic with SUMMARY.md.
- **Backlog promotion site** (OOS-01 fallback only): `.planning/ROADMAP.md` "Backlog" section. New entry `### Phase 999.x: maps/router.py decomposition (BACKLOG — P2)` if cap is raised.
- **CHANGELOG.md** — NO `[1.5.8]` entry for Phase 1098 (that's Phase 1100's work per CLOSE-01).

### Verification gate commands

```bash
# Sequential — expect 3063+ passed / 0 failed / 38 skipped
cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/

# -n 4 — expect 3063+ passed / 0 failed / 38 skipped (literal zero — OOS rows retired)
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 tests/

# -n auto 3-run (stale-DB cleanup between runs per PYTEST-XDIST-PERF-v1020.md §1)
docker compose exec -T db psql -U geolens -d geolens -At -c \
  "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';" \
  | xargs -I{} docker compose exec -T db psql -U geolens -d geolens -c "DROP DATABASE IF EXISTS \"{}\" WITH (FORCE);"
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n auto tests/  # ×3
```

</code_context>

<specifics>
## Specific Ideas

### OOS-01 trim hunting ground (suggestions for planner)

The 7-LOC deficit in `maps/router.py` is small enough that a few of these likely clear it:
- **Long inline docstrings on private helpers** (4-6 line docstrings on internal-only functions can often compress to 1-2 lines).
- **Redundant import groupings** (e.g., split `from foo import a, b, c, d` across 4 lines that could be 1).
- **Comment paragraphs explaining what code already says** (the "Phase XXX did Y" tombstone comments).
- **Trailing-blank-line / leading-blank cleanup at top/bottom of class methods.**

If trim fails, the cap-raise to 1850 should land in the allowlist with a comment block dated 2026-05-24 referencing this phase + this decision (D-02).

### OOS-03 behavioral test sketch

Approximate shape (planner to refine):

```python
@pytest.mark.anyio
async def test_make_safe_client_blocks_private_ip_redirect():
    """make_safe_client returns a client whose hook pipeline rejects SSRF redirects.

    Behavioral test for the SSRF revalidation contract — supersedes the
    pre-2026-05-24 identity check (which was brittle to module-level
    mock.patch contamination from sibling tests).
    """
    client = make_safe_client()
    response = httpx.Response(
        302,
        headers={"Location": "http://127.0.0.1/internal"},
        request=httpx.Request("GET", "https://attacker.example/redirect"),
    )
    # Drive the response through the client's hook pipeline.
    with pytest.raises(SSRFError):
        for hook in client._event_hooks.get("response", []):
            await hook(response)
    # Optional: keep wiring checks that aren't patchable
    assert client.follow_redirects is True
    assert client.max_redirects == 5
```

Planner may simplify further — calling `_revalidate_redirect(response)` directly (already covered by sibling tests at line 22-97) PLUS asserting `_event_hooks["response"]` is non-empty might be enough to dodge the identity-check brittleness.

### Plan task sequencing rationale

Run OOS-02 (test deletion) FIRST in T3 — smallest blast radius (1 test removed), reduces noise in T5's verify gate. Then OOS-01 (T2 — file-edit + cap fallback decision), then OOS-03 (T4 — most novel rewrite, do last so prior verifications are warm).

Actually — **reverse**: do OOS-01 first since it has the highest uncertainty (trim might fail → cap-raise + backlog branch). Then OOS-02 + OOS-03 in either order (both are deterministic edits).

### Out of phase 1098 scope (explicit guard-rails for planner)

- NO OAuth fix work (Phase 1099).
- NO CI live-verify work (Phase 1100).
- NO production-code refactor of `security.py` (production SSRF posture is correct per D-08).
- NO README content edits (D-06).
- NO new test pins beyond the OOS-03 rewrite (D-08).
- NO CHANGELOG entry for v1.5.8 (Phase 1100).
- NO sibling-test sweep in `test_phase_275_readme_accuracy.py` (D-07).

</specifics>

<deferred>
## Deferred Ideas

### Phase 999.x — maps/router.py decomposition (BACKLOG)

**Promote IFF OOS-01 trim falls short** and cap is raised to 1850. Backlog entry shape:

```
### Phase 999.x: maps/router.py decomposition (BACKLOG — P2)

**Goal:** Decompose backend/app/modules/catalog/maps/router.py (currently ~1850 LOC) into facade + cohesive sub-routers per Phase 226/238/252 patterns. Likely split candidates: maps_crud.py (create/read/update/delete), maps_layers.py (layer CRUD + reordering), maps_thumbnails.py (capture/serve), maps_public.py (share-link + embed-token surfaces).
**Source:** v1023 Phase 1098 OOS-01 fallback. Cap raised 4× now (1500→1700→1800→1850); test was DESIGNED to force decomposition, raising the cap erodes its intent.
**Estimated effort:** 0.5-1 day (refactor + OpenAPI snapshot regen + frontend SDK regen + smoke).
**Triggered when:** maps/router.py crosses 1850 LOC OR before next major Map Builder phase.

Plans:
- [ ] TBD
```

### OOS-03 leaker hunt (DEFERRED — possibly never)

If the defensive behavioral rewrite (D-08) holds across all 3 verification runs, the leaker becomes irrelevant. If we ever DO need to identify it:

- Run sequential pytest with `--collect-only` + binary-bisect via `pytest -k 'not <first_half>' tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` to narrow which test file contaminates.
- Likely culprits: tests that use `mock.patch("app.modules.catalog.sources.security.*", ...)` without `with` blocks (none found via grep, but `mock.patch.object` or context-manager-but-leaks shapes possible).
- Could surface as a v1024+ test-isolation audit if other tests start showing similar brittleness patterns.

Cost-of-investigation is high (multi-hour bisect) and value-of-fix is low (defensive rewrite addresses the symptom permanently). Park indefinitely.

### Sibling test_phase_275_readme_accuracy.py sweep (DEFERRED — never needed)

D-07 — the 8 sibling tests all pass per discuss-time spot-check. If any future README change breaks one, address it then; don't proactively sweep.

</deferred>

---

*Phase: 1098-oos-triad-closure*
*Context gathered: 2026-05-24*
*Meta: User directive — autonomous lifecycle via `/gsd-autonomous --use-playwright-mcp` for full v1023 close*
