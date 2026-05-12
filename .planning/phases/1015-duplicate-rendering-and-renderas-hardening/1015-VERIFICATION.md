---
phase: 1015-duplicate-rendering-and-renderas-hardening
status: passed
verified: 2026-05-12
requirements: [DUP-01, DUP-02, DUP-03, DUP-04, DUP-05]
---

# Phase 1015 Verification

## Result

Status: passed

Phase 1015 achieved its goal: duplicate renderings are now proven through both browser entry points, and existing renderAs tests continue to prove field discipline and unsupported renderer omissions.

## Requirement Checks

| Requirement | Status | Evidence |
|---|---|---|
| DUP-01 | Passed | Browser test duplicates from row overflow and asserts sibling `MapLayer` creation. |
| DUP-02 | Passed | Browser test duplicates from Add Dataset `another rendering`. |
| DUP-03 | Passed | Browser test asserts dataset-rendering header count updates to 2 and 3; component tests cover group rendering. |
| DUP-04 | Passed | Focused renderAs/hook tests prove patches use writable fields and omit `is_3d`. |
| DUP-05 | Passed | Focused renderAs tests prove v1-punted renderers remain unsupported. |

## Commands

```bash
npx playwright test e2e/builder.spec.ts --project=chromium -g "duplicates dataset renderings"
cd frontend && npm run test -- DatasetSearchPanel MapStackPanel map-stack renderAs use-builder-layers --run
npm run e2e:smoke:builder
```

## Residual Risk

- Browser coverage proves creation and grouping, not every renderAs visual permutation. That remains appropriate for this phase because renderAs mapping itself is covered by focused unit tests and deeper styling behavior is already covered in builder styling smoke.
