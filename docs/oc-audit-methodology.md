# Open-Core Audit Methodology

GeoLens runs periodic open-core separation audits to ensure the boundary between Community and Enterprise editions remains clean. This document describes the methodology, output conventions, and when to use each.

For the executable audit procedure, see [.claude/commands/oc-audit.md](../.claude/commands/oc-audit.md) — it is the slash-command implementation invoked by `/oc-audit`.

## Audit Types

GeoLens runs two distinct flavors of open-core audit:

### 1. Ad-hoc audits

**When**: triggered by a developer running `/oc-audit` to investigate a specific concern, validate a refactor, or confirm an extension seam works as designed.

**Output path**: `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`

**Lifecycle**: kept locally; not committed to the repo (the `docs-internal/` directory is gitignored). Treated as a working artifact for the developer running the audit.

**Use this when**:
- You're hardening a single seam (e.g., the new permission extension) and want a focused report.
- You're investigating a regression and need to compare current state to a baseline.
- You're prepping a milestone-close audit and want a dry-run output to inform planning.

### 2. Milestone-close audits

**When**: triggered as part of a `/gsd-complete-milestone` or pre-tag verification flow.

**Output path**: `.planning/audits/<milestone-version>-oc-audit.md` or `.planning/milestones/<milestone-version>-MILESTONE-AUDIT.md` depending on how the milestone close is structured.

**Lifecycle**: also gitignored (the `.planning/` directory is gitignored), but archived in `.planning/milestones/<milestone-version>-phases/` as part of the milestone snapshot.

**Use this when**:
- Closing a milestone where the open-core boundary was touched (any `v13.x` milestone, future Cloud milestone, etc.).
- Producing a verdict that contributes to milestone acceptance criteria.

## Why two paths

The dual-path split keeps ad-hoc working artifacts (`docs-internal/audits/`) separate from milestone-close formal verdicts (`.planning/audits/`). Milestone audits are timestamped at close and never updated; ad-hoc audits churn during active development.

Both directories are gitignored; the GeoLens convention is that audit output is informational, not normative — the source of truth for the boundary is the codebase itself, not the audit report.

## Cross-checking the convention

The `/oc-audit` slash command currently writes to `docs-internal/audits/`. When milestone-close needs an audit, the operator copies the relevant report (or runs a fresh one) into `.planning/audits/<milestone>-oc-audit.md` for archival.

## Provenance

This methodology is a Phase 275 (v13.13 / API-12 / L-53) artifact documenting the convention that has shipped since v13.1 (April 2026). It does not change behavior — it documents what already happens.

## See also

- [.claude/commands/oc-audit.md](../.claude/commands/oc-audit.md) — the slash-command implementation.
- [docs/api-style.md](api-style.md) — public API conventions (also a Phase 275 artifact).
