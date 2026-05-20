---
plan: 1060-01
status: complete
shipped: 2026-05-20
e2e_smoke_status: green
e2e_results:
  passed: 25
  failed: 0
  skipped: 1
  total: 26
  wall_clock_s: 90
dispositions:
  - test: "e2e/builder-v1-5.spec.ts:364 (Test 3) + :478 (Test 4)"
    failure_mode: "test-contract drift"
    fix: "Update aria-selected → data-selected (Phase 1052 dropped listbox/option roles)"
    files: ["e2e/builder-v1-5.spec.ts"]
    real_or_pin: "test-pin (contract update, no code change)"
  - test: "e2e/builder.spec.ts:338"
    failure_mode: "real backend bug — snake_case→camelCase shape drift on duplicate"
    fix: "Backend canonicalize_builder_style_config helper in schemas.py normalizes incoming style_config.builder camelCase keys to snake_case before storage"
    files: ["backend/app/modules/catalog/maps/schemas.py"]
    real_or_pin: "real fix"
commit: a400eb89
---

# Plan 1060-01: E2E Triage + Fix — SUMMARY

## Dispositions

### Failure 1: `e2e/builder-v1-5.spec.ts` Test 3 (line 364) + Test 4 (line 478)

**Disposition:** test-contract update (no code change required).

**Root cause:** Phase 1052 (v1010.1 close-gate) dropped `role="listbox"` and
`role="option"` from `StackRow` because nested-interactive accessibility
issues — each row contains focusable controls (drag handle, eye toggle,
kebab menu). With those roles gone, `aria-selected` is meaningless; the
React code at `frontend/src/components/builder/StackRow.tsx:188` signals
multi-selection via `data-selected="true"`. The e2e tests were not updated
when the roles were dropped, so they kept asserting `aria-selected`.

**Fix:** Updated 4 assertions across Test 3 + Test 4:
- Test 3 (line 390, 393, 418, 419): cmd-click happy path + boundary
- Test 3 (line 434): Escape clear assertion
- Test 4 (line 477, 480): bulk-delete setup

All changed from `aria-selected="true"` to `data-selected="true"`. Added
inline comment block explaining the Phase 1052 contract.

### Failure 2: `e2e/builder.spec.ts:338` duplicate dataset rendering

**Disposition:** real backend fix.

**Root cause:** The frontend's `normalize-style-config.ts:normalizeBuilderStyleConfig`
converts storage-canonical snake_case keys (`outline_color`, `outline_width`,
etc.) to camelCase (`outlineColor`, `outlineWidth`) on layer LOAD. This is
the React-state contract — UI components read `builder.outlineColor`. When
a layer is duplicated, React state passes the camelCase values back through
the POST body, and without a server-side canonicalization step the new
layer was persisted with camelCase while the original (created via
`service_shared.generate_default_style`) kept snake_case in DB.

The `getMapDetails` fetch in the test returned the two layers side-by-side
and `expect(rowDuplicate.style_config).toEqual(originalLayer.style_config)`
blew up on the case-shape difference. Behavior was correct visually (both
render identically through the same adapter), but the DB schema was now
inconsistent — a subtle persistence bug that would manifest in any
byte-equal style-config audit.

**Fix:** New backend helper `canonicalize_builder_style_config()` in
`backend/app/modules/catalog/maps/schemas.py`. It inverts
`style_json._BUILDER_KEY_ALIASES` to rewrite camelCase builder keys to
snake_case before storage. Wired into both `MapLayerInput` and
`MapLayerPatch` `model_validator`s after `split_legacy_builder_paint`.
Idempotent: snake_case input passes through unchanged. Tile-render path
is unaffected (paint/layout were never on this code path).

## Smoke Gate Results

| Gate | Result | Notes |
|---|---|---|
| `npm run e2e:smoke:builder` exit | 0 (green) | Was non-zero before fixes |
| Tests passed | 25/26 | 1 skipped (intentional `it.todo`-style) |
| Tests failed | 0 | Was 2 before fixes |
| Did not run | 0 | Was 13 before fixes (Playwright halts after max-failures) |
| Wall clock | ~90s | First full pass through the suite |

<!-- Plan 01 Task 3 memo -->
<!--
Final e2e:smoke:builder run (Phase 1060 close-gate post-fix):
  exit: 0
  pass: 25
  fail: 0
  skip: 1
  did_not_run: 0
  wall_clock_s: 90
-->

## Verification

- `e2e/builder-v1-5.spec.ts` Test 3 (multi-select boundary): PASS
- `e2e/builder-v1-5.spec.ts` Test 4 (bulk-delete happy): PASS
- `e2e/builder.spec.ts:338` (duplicate dataset renderings): PASS
- Full suite: `npm run e2e:smoke:builder` exits 0 with 25 passing tests

## Files Modified

- `e2e/builder-v1-5.spec.ts` — 6 line changes (4 assertions + 2 comment lines + 1 block comment)
- `backend/app/modules/catalog/maps/schemas.py` — +60 lines (helper + map + 2 validator wirings)

Commit: `a400eb89`
