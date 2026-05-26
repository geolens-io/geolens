# Requirements: GeoLens v1028 Map Builder Product Polish

**Defined:** 2026-05-25
**Core Value:** Users can find any dataset in the catalog in seconds - search, see it on a map, understand what it is, and get it out in the format they need.

## v1028 Requirements

### Workflow Audit

- [x] **AUDIT-01**: Builder workflow exploration covers add/edit layer flows, layer options menus, save feedback, undo/history, empty/error states, responsive editor behavior, and viewer parity with Playwright MCP evidence.
- [x] **AUDIT-02**: The audit explicitly exercises Builder Notes and AI-assisted builder flows before implementation work is scoped.
- [x] **AUDIT-03**: Console errors, warning noise, failed network requests, and confusing user-visible states found during the sweep are triaged into fix-now, defer, or accepted-with-rationale buckets.
- [x] **AUDIT-04**: The milestone confirms that validation targets the standard GeoLens app/local stack and does not depend on a separate demo instance, demo deployment, or demo compose path.

### Builder Workflow Polish

- [x] **WORKFLOW-01**: High-frequency layer authoring flows have clear save/dirty feedback and no ambiguous intermediate state after layer edits, reorders, duplicate/remove actions, or settings changes.
- [x] **WORKFLOW-02**: Layer options, editor panels, empty states, and error states remain usable and visually stable on desktop and mobile-sized builder viewports.
- [x] **WORKFLOW-03**: Undo/history behavior remains coherent after manual actions, duplicate/remove flows, style edits, Notes interactions where applicable, AI-assisted edits, and map-level saves.
- [x] **WORKFLOW-04**: Focused frontend tests pin any fixed workflow defects without overfitting to v1027 implementation internals.

### Builder Notes

- [x] **NOTES-01**: User can create, edit, and remove builder Notes through the UI without layout overlap, focus traps, or inaccessible controls.
- [x] **NOTES-02**: Notes persist through save/reload when designed to persist, and any intentionally draft-only Notes behavior is documented in the phase summary.
- [x] **NOTES-03**: Notes behavior is verified alongside layer selection, map interaction, and viewer expectations so Notes do not corrupt saved map composition or public viewer rendering.
- [x] **NOTES-04**: Notes empty/error/loading states are clear and do not rely on visible instructional text that duplicates control labels.

### Builder AI

- [x] **AI-01**: AI builder entry points are exercised with realistic prompts for style changes, layer edits, and map-authoring assistance against the target map or a throwaway copy.
- [x] **AI-02**: AI-generated builder actions preserve v1027 command semantics, undo/history expectations, dirty tracking, and save/reload durability.
- [x] **AI-03**: AI disabled, unauthenticated, missing-provider, or request-failure states degrade clearly without console errors or broken builder controls.
- [x] **AI-04**: Any AI prompt/action gap found during Playwright MCP testing is either fixed with regression coverage or logged as a future requirement with concrete reproduction steps.

### Showcase Map Polish

- [x] **SHOWCASE-01**: The target ADK map remains cartographically polished for marketing screenshots: terrain, imagery, DEM/hillshade, labels, lines, points, polygons, and layer ordering look intentional.
- [x] **SHOWCASE-02**: Screenshot capture path is reliable from the product map itself and does not require a separate demo instance or special demo deployment.
- [x] **SHOWCASE-03**: Public viewer and embed viewer remain visually aligned with the builder for the target map after any polish changes.
- [x] **SHOWCASE-04**: Any destructive showcase-map UAT uses a throwaway copy and leaves the canonical target map unchanged unless the change is explicitly intended.

### Quality Sweep and Close Gate

- [x] **QUALITY-01**: Playwright MCP close gate covers the target map, a throwaway editable copy, Builder Notes, Builder AI, layer options, save/reload, viewer parity, and console/network hygiene.
- [x] **QUALITY-02**: Frontend gates pass for touched areas, including focused Vitest coverage plus `npm run typecheck`, `npm run lint`, and `npm run build`.
- [x] **QUALITY-03**: Backend, OpenAPI, SDK, or CLI gates run if the milestone touches those surfaces; otherwise the no-backend/API-change decision is recorded.
- [x] **QUALITY-04**: Active planning/docs references created or touched by this milestone consistently state that GeoLens no longer maintains a separate demo instance.
- [x] **QUALITY-05**: Phase summaries, CHANGELOG entry, and milestone audit document workflow impact, Notes impact, AI impact, showcase-map evidence, accepted limitations, and follow-up requirements.

## Future Requirements

### Builder Follow-Ups

- **BUILDER-FU-01**: Consider a fuller user-facing builder onboarding pass only after this milestone identifies which polish gaps remain after Notes, AI, and workflow sweep fixes.
- **BUILDER-FU-02**: Consider broader AI chat UX redesign separately if AI action reliability is healthy but prompt composition or conversational affordances remain weak.

### Completed Follow-Ups

- **AI-FU-01**: Completed 2026-05-25 after provider keys were added and the Anthropic key was refreshed. Anthropic runtime AI (`anthropic` / `claude-sonnet-4-20250514`) returned a `set_style` action for the throwaway ADK copy, the builder applied it, dirty state appeared, Save completed, reload preserved `line-color: #00AEEF`, and the copy was deleted. An interim OpenAI-compatible check also passed while the first Anthropic key was invalid.
- **ERROR-FU-01**: Completed 2026-05-25. The global React app error page and route error page now include a GitHub bug-report action that opens the repository's `bug_report.yml` issue template.

### CI Infrastructure

- **CI-01-v1028**: Live-verify `pytest-parallel-isolation` on real GitHub Actions infrastructure after geolens-io billing is resolved. This rolling external blocker remains outside the map-builder product-polish invariant.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Separate demo instance, demo deployment, or demo compose maintenance | The standard GeoLens app/local stack is the validation target; showcase-map work happens in-product. |
| Broad map-builder architecture rewrite | v1027 already established the architecture boundaries; v1028 should polish product workflows using those boundaries. |
| New LLM provider or AI backend redesign | AI is in scope as builder workflow validation and bug fixing, not platform expansion. |
| New cartographic feature family | Polish existing target-map and builder controls before adding new renderer capabilities. |
| Closing the GitHub Actions billing blocker | CI live-verify remains an external operator prerequisite carried forward from earlier milestones. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUDIT-01 | Phase 1124 | Complete |
| AUDIT-02 | Phase 1124 | Complete |
| AUDIT-03 | Phase 1124 | Complete |
| AUDIT-04 | Phase 1124 | Complete |
| WORKFLOW-01 | Phase 1125 | Complete |
| WORKFLOW-02 | Phase 1125 | Complete |
| WORKFLOW-03 | Phase 1125 | Complete |
| WORKFLOW-04 | Phase 1125 | Complete |
| NOTES-01 | Phase 1126 | Complete |
| NOTES-02 | Phase 1126 | Complete |
| NOTES-03 | Phase 1126 | Complete |
| NOTES-04 | Phase 1126 | Complete |
| AI-01 | Phase 1126 + AI-FU-01 | Complete |
| AI-02 | Phase 1126 + AI-FU-01 | Complete |
| AI-03 | Phase 1126 | Complete |
| AI-04 | Phase 1126 | Complete |
| SHOWCASE-01 | Phase 1127 | Complete |
| SHOWCASE-02 | Phase 1127 | Complete |
| SHOWCASE-03 | Phase 1127 | Complete |
| SHOWCASE-04 | Phase 1127 | Complete |
| QUALITY-01 | Phase 1128 | Complete |
| QUALITY-02 | Phase 1128 | Complete |
| QUALITY-03 | Phase 1128 | Complete |
| QUALITY-04 | Phase 1128 | Complete |
| QUALITY-05 | Phase 1128 | Complete |

**Coverage:**
- v1028 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-05-25*
*Last updated: 2026-05-25 after v1028 close*
