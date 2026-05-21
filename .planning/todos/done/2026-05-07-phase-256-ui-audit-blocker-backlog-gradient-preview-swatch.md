---
created: 2026-05-07T00:15:49.470Z
closed: 2026-05-07T07:35:00Z
status: closed
title: Phase 256 UI audit BLOCKER carried as backlog text only
area: ui
resolves_phase: 258
shipped_in: v13.11
files:
  - frontend/src/components/builder/LineGradientControls.tsx
  - .planning/phases/256-line-gradient-builder-ui/256-UI-REVIEW.md
---

## Closure note (2026-05-07)

**Closed in v13.11 Phase 258.** All 7 Phase 256 UI audit findings shipped:

- **POLISH-01 (BLOCKER — gradient preview swatch):** commit `a3098856` (Plan 258-01 Task 1 Step 1) — `data-testid="line-gradient-preview-swatch"` div with inline `linear-gradient(to right, ...)` style; renders only in canonical gradient mode.
- **POLISH-02..05, POLISH-07, COPY-01:** same commit — Color label, toggle focus + cursor, w-full disclosure, pos prefix span, trash tooltip, advancedHint rewrite.
- **POLISH-06 (stable React keys):** commit `cc5a7138` (Plan 258-02) — optional `id?: string` field on builder JSONB shape with `crypto.randomUUID()` at addStop + hydration; canonical paint expression byte-identity preserved per v13.9 GRAD-05/06.
- **WR-01 (`applyAdvanced` missing nextPaint composition):** code-review surface; fixed inline in commit `fe50961c`.

Verified: 42 vitest tests in `LineGradientControls.test.tsx` (29 pre-existing v13.9 invariants + 13 new `polish-0*:` cases) + full frontend suite (1183 tests) all green; `tsc --noEmit` exit 0; `eslint` clean. See `.planning/phases/258-line-gradient-ui-closeout/258-VERIFICATION.md` for full REQ-by-REQ landing notes.

## Problem

The Phase 256 UI audit (`.planning/phases/256-line-gradient-builder-ui/256-UI-REVIEW.md`) scored the line-gradient builder UI 18/24 across the 6-pillar review and flagged one BLOCKER as the top-priority visual fix:

> **Missing gradient preview swatch above stop list** — Users activating Gradient mode see two color swatches and two numbers with no visual representation of the resulting gradient. The CONTEXT.md explicitly recommended a thin gradient bar above the stops list. Without it, the relationship between stop positions and the rendered line color is opaque, forcing mental simulation. (Pillar 2: Visuals — 2/4)

Today, this BLOCKER lives only as prose inside the UI-REVIEW.md and a one-line note in `~/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md` ("UI audit 18/24 with 1 BLOCKER (gradient preview swatch) deferred as polish backlog"). There is no structured todo, no ROADMAP backlog entry (999.x), and no phase ticket capturing the work. The risk is straightforward: backlog text in an archived phase folder is easy to lose track of, and the next milestone planning round will not surface it as a candidate item.

The other UI audit findings — "Color" label noise per stop row, missing focus rings on toggle buttons, disclosure button missing `w-full`, position input missing visible label, `key={idx}` anti-pattern on stop rows — were also captured as backlog text only and have the same visibility problem, but the gradient preview swatch is the named BLOCKER and the highest-priority visual gap.

## Solution

Two-step closure (pick one, do not need both):

1. **Promote to ROADMAP backlog (preferred):** Run `/gsd-capture --backlog` to add a 999.x entry titled "Map builder polish — line-gradient preview swatch + UI audit follow-ups (Phase 256)". Body summarizes the 7 UI audit findings, links back to `.planning/phases/256-line-gradient-builder-ui/256-UI-REVIEW.md`, and is sized for a small dedicated polish phase (~1-2 plans). This puts it in the parking lot where the next milestone planning sweep will see it.

2. **Or fix inline as a quick polish phase now:** Add a `<div>` with `style={{ background: \`linear-gradient(to right, ${stops.map(s => \`${s.color} ${s.position*100}%\`).join(', ')})\` }}` as an `h-3 rounded w-full` bar between the Solid/Gradient toggle and the stops list in `LineGradientControls.tsx`. ~2 lines of code per the UI-REVIEW.md fix #1 prescription. While there, knock off the cheap wins: `cursor-pointer` + `focus-visible:ring-*` on the toggle buttons (Pillar 6 fix), `w-full` on the disclosure button (Pillar 2 fix), and consider passing `#${idx+1}` instead of `t('style.lineGradient.color')` to the per-stop `StyleColorPicker.label` to kill the "Color" label repetition (Pillar 2 fix).

Either way, after closure, update the MEMORY.md note from "deferred as polish backlog" to either "promoted to ROADMAP 999.x" or "shipped in Phase NNN" so the trail stays current.

Reference: `.planning/phases/256-line-gradient-builder-ui/256-UI-REVIEW.md` Top 3 Priority Fixes section, Pillar 2 (Visuals) findings.
