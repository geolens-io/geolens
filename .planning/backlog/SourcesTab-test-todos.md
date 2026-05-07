# SourcesTab.test.tsx — Deferred Test Backlog

Migrated from inline `it.todo(...)` placeholders during Phase 278 (TEST-07, 2026-05-07).
Original location: `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx:128-135`.

Original placeholders moved here verbatim. Each represents an untested code path in
`frontend/src/components/dataset/SourcesTab.tsx` that warrants coverage when the
SourcesTab UI surface receives its next feature work or a regression surfaces.

## Pending tests

- [ ] renders source table with rows in position order
- [ ] source title is a clickable link to /datasets/{dataset_id}
- [ ] shows regenerating banner when status === "regenerating"
- [ ] shows failed banner when status === "failed"
- [ ] disables add/remove when regenerating
- [ ] remove button triggers confirm dialog
- [ ] disables remove when only 2 sources
- [ ] add source picker filters out already-linked sources

## How to pick this up

1. Read `frontend/src/components/dataset/SourcesTab.tsx` to identify the props each
   test needs to assert against.
2. Use `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx`'s existing
   mock setup as the harness; add an `it(...)` block per backlog item; remove the
   item from this file's checklist.
3. When all 8 are landed, delete this file.
