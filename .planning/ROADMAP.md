# Project Roadmap

This file tracks unsequenced backlog items (999.x). Active milestone roadmaps live at `.planning/milestones/{version}-ROADMAP.md`.

## Backlog

### Phase 999.5: Helm chart for Kubernetes deployment (BACKLOG)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §7 P3
**Estimated effort:** ~1 week

Compose-only deployment today; enterprise prospects in regulated/government markets typically demand K8s. Helm chart enables enterprise adoption at scale and unblocks K8s-first prospects.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the Enterprise tier's "multi-org / tenant isolation" feature can ship. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation.

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)
