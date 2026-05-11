# Phase 1006: Responsive, Accessibility, and Copy Hardening - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning
**Source:** Roadmap, requirements, Phase 1002 implementation inventory, Phase 1003-1005 summaries

<domain>
## Phase Boundary

Bring touched builder and public map surfaces up to current GeoLens accessibility, responsive, touch-target, copy, and i18n standards. Keep scope focused on surfaces already touched by v1001 builder polish: auth shell classification around `/maps/:id`, builder mobile sidebar/rail/inspector shell, visible/collapsed focus behavior, and basemap/network recovery copy.

</domain>

<decisions>
## Implementation Decisions

### Requirement Coverage
- A11Y-01: desktop, tablet, and mobile builder layouts must avoid inaccessible controls, off-screen panels, and unreadable dense rows.
- A11Y-02: hidden/collapsed builder content must not remain reachable to keyboard or screen-reader users.
- A11Y-03: touched dialogs, menus, icon buttons, sliders, tablists, and switches must keep accessible names and sufficient visible focus.
- A11Y-04: touched builder copy must use user-facing GIS/product language and recovery-oriented validation wording.
- A11Y-05: all touched builder copy must be complete across en, es, fr, and de.
- A11Y-06: common mobile controls need 44px touch targets and stable dimensions.

### Routed Phase 1002 Findings
- F-1002-02: harden authenticated builder shell state so token/user mismatches do not show editor chrome with signed-out nav/footer artifacts.
- F-1002-03: Phase 1003 added a data-first empty builder prompt; Phase 1006 should preserve copy and focus order.
- F-1002-06: tighten mobile inspector/sheet sizing, footer suppression, focus restoration, and map context.
- F-1002-08: add non-blocking basemap/network recovery copy that distinguishes map background failures from data-layer authoring.

### Carry-Forward Context
- Phase 1003 added the data-first empty stack prompt, row state badges, and visible inspector tab/back focus.
- Phase 1004 clarified selected-layer scope and recoverable style/filter/label/popup copy.
- Phase 1005 stabilized public/shared/embed layer identity and save/share publication state.

### Claude's Discretion
- Prefer targeted component fixes and focused tests over a broader design-system refactor.
- Use existing UI primitives, builder namespace strings, and current testing conventions.
- Keep Playwright evidence deferred to Phase 1007 unless a responsive issue cannot be verified through focused component tests.

</decisions>

<specifics>
## Specific Ideas

- Restore `user` from `getMe` when a persisted token exists, and classify authenticated map routes consistently while the user payload is loading.
- Keep anonymous `/maps/:id` public viewer behavior, but prevent token/user-null states from downloading editor code or showing footer artifacts.
- Increase mobile builder sheet save/rail controls to 44px and leave more map context visible beside mobile sheets.
- Add a scoped, dismissible or persistent non-blocking basemap recovery notice inside `BuilderMap` for style/tile failures.
- Add focused Vitest coverage for auth restoration, route gate behavior, footer suppression, mobile touch target classes, and basemap recovery copy.

</specifics>

<deferred>
## Deferred Ideas

- Broad screenshot QA and Playwright responsive assertions remain Phase 1007.
- Full accessibility scan automation remains Phase 1007 QA-04.
- Server-side thumbnails and durable gallery output remain OPS-01/NEXT-04.

</deferred>

---

*Phase: 1006-responsive-accessibility-copy-hardening*
*Context gathered: 2026-05-11*
