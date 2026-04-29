# /oc-audit — Open-Core Separation Audit

Audit the GeoLens codebase for open-core separation health across two product axes — Community (free, self-hosted) and Enterprise (paid, self-hosted private deployments) — covering boundary integrity, seam quality, inventory accuracy, and prioritized action items.

> **Note:** A hosted SaaS / Cloud tier is *deferred* per `docs-internal/GTM/pricing-to-tiers.md` ("Managed Hosting (Future) — Only do this AFTER traction"). This audit does not currently cover SaaS readiness. If/when that decision changes, the audit will need a 7th subagent (multi-tenancy / metering / billing / per-workspace quota readiness) and a corresponding scoring dimension.

---

## INTAKE (Serial — do this first)

### Step 1: Read the GTM boundary docs

Read these files in order. They define the authoritative free/paid boundary:

1. `docs-internal/GTM/free-vs-enterprise.md`
2. `docs-internal/GTM/pricing-to-tiers.md`
3. `docs-internal/GTM/repo-split.md`
4. `docs-internal/GTM/GTM-EVALUATION.md` (if it exists — this is the prior audit baseline)

If any file is missing, note it and proceed with the embedded boundary rules below.

### Step 2: Read the codebase structure

```bash
find backend/app -type f -name "*.py" | head -200
find frontend/src -type f \( -name "*.tsx" -o -name "*.ts" \) | head -200
ls -la docker-compose*.yml 2>/dev/null
find backend frontend -maxdepth 2 -name "Dockerfile*" 2>/dev/null
ls -la deployment/ 2>/dev/null && echo "deployment/ present" || echo "deployment/ missing — note in Subagent 4"
ls backend/app/modules/settings/ 2>/dev/null
ls backend/app/platform/extensions/ 2>/dev/null
```

Build a mental model of the current domain layout before dispatching subagents. **Verified facts as of v13.1 close (2026-04-29):**
- Backend uses `from app.` import convention (not `from backend.app.`)
- API entry point is `backend/app/api/main.py`
- Extension scaffolding lives at `backend/app/platform/extensions/` (`protocols.py`, `defaults.py`, `guards.py`)
- `backend/app/core/identity.py` defines `IdentityProtocol` + `RoleProtocol` + `IdentityExtension` + `Identity` alias (Phase 214); `get_identity_extension()` accessor at `backend/app/platform/extensions/__init__.py:111`
- `backend/app/modules/catalog/authorization.py` is the canonical home for visibility/authorization (Phase 213 relocated from `auth/visibility.py`, which no longer exists)
- `backend/openapi.json` is committed and is the SDK source of truth (Phase 215)
- `cli/` is an Apache-2.0 standalone package (`geolens` on PyPI) consuming only the generated Python SDK
- `sdks/python/` and `sdks/typescript/` are auto-generated from `backend/openapi.json` via `make sdks`; `make sdks-check` is a CI drift gate
- Apache-2.0 `LICENSE` files exist at: repo root, `cli/LICENSE`, `sdks/python/LICENSE`, `sdks/typescript/LICENSE` — all should be byte-identical
- Enterprise overlay file `docker-compose.enterprise.yml` exists alongside `docker-compose.yml` and `docker-compose.demo.yml`
- The `geolens-enterprise` repo (sibling clone at `~/Code/geolens-enterprise`) contains the SAML overlay implementation; it registers via `importlib.metadata` entry_points dual-binding `AuthExtension` + `IdentityExtension`
- Backend modules: `admin, audit, auth, catalog, embed_tokens, settings` (no `ai` module — AI features are cross-cutting)
- `is_enterprise()` is the canonical runtime gate for community/enterprise feature splits (Phase 219 established the schema-validator + service-entry pattern at `oauth/schemas.py:147,285` and `oauth/service.py:265-270`)

If any of these have changed since the audit was last run, update the assumptions before dispatching subagents.

---

## EMBEDDED BOUNDARY RULES

These are the canonical free/paid boundary definitions. Use these as the source of truth when the GTM docs are ambiguous or missing.

**Guiding principle:** *Free should make a single user successful alone, and a single team collaborating in one deployment. Paid should solve organizational problems — multi-tenant isolation, governance, compliance, control, branding, and scale.*

### MUST remain free (Community Edition)

**Catalog & Discovery**
- Catalog + search (full-text + semantic)
- Faceted filtering
- Dataset preview (vector, raster, tabular)
- Collections (basic grouping)
- Versioning (basic)

**Ingestion**
- File uploads (Shapefile, GeoJSON, GPKG, CSV, etc.)
- WFS / ArcGIS import (one-shot, user-driven)
- Raster → COG conversion, VRT creation
- Schema preview + diff

**Visualization & Editing**
- Map viewer + map builder (layers, styling, filters, labels)
- Vector tiles + raster rendering
- Basic basemap config
- Geometry editing, attribute editing, schema editing (basic)

**Standards (HARD-FREE — never gate)**
- OGC API Features, OGC API Records, STAC export, DCAT metadata

**Sharing**
- Share links (basic), public/internal visibility toggle, basic embed

**Admin & Identity (single-deployment scale)**
- User accounts with role labels (viewer/editor/admin)
- **Multi-user collaboration in a single deployment** (shared collections, shared maps, role-based access — multiple users on one team, one org's data)
- Basic per-user API keys (no quotas, no usage tracking)
- Basic audit log viewing/searching (no export)
- Basic OIDC / OAuth login

**AI (interactive, single-shot only)**
- Chat-style map generation (one prompt → one map)
- Single styling-suggestion edits
- One-off metadata field assistance during manual editing

**Distribution**
- Docker Compose self-host
- Open-source CLI + SDKs for catalog/ingest/export workflows (when implemented)

### Enterprise Edition (paid, self-hosted)

**Team add-ons ($8K–$15K/yr):**
- SAML SSO (beyond basic OIDC)
- Branding removal toggle ("Powered by GeoLens" removal)
- Audit log export (CSV/JSON)
- Priority support SLA
- Advanced sharing controls (expiring links, domain restrictions)

**Business tier ($25K–$60K/yr):**
- Advanced RBAC (dataset/collection-level admin UI, field-level permissions)
- Approval workflows (draft → review → publish)
- SCIM provisioning
- Full audit logs + compliance reporting
- AI policy controls / provider configuration / model routing
- Org-level tokenized API + embed quota administration
- Persistent external connectors (stored credentials, scheduled mirroring, recurring sync from S3 / WFS / ArcGIS / PostGIS)

**Enterprise tier ($75K–$200K+/yr):**
- White-labeling (full rebrand, custom domain, OEM rights)
- **Multi-tenant isolation** (multiple isolated organizations sharing one deployment with separate users, data, billing, admin)
- Cross-instance federation
- Data lineage tracking (structured)
- Air-gapped deployment packages
- GovCloud-ready configs
- Org-wide AI policies, batch metadata extraction, automated workflow pipelines

### Anti-patterns (things that MUST NOT happen)

- Standards (OGC/STAC/DCAT) behind a paywall
- Per-seat pricing or artificial user caps in Community
- "Crippled" free tier that blocks basic ingest → find → visualize → share workflow
- Multi-user collaboration in a single deployment behind a paywall (only multi-tenant isolation is paid)
- Enterprise logic hardcoded in community modules without extension seams
- Feature flags that degrade community UX to upsell
- AGPL or copyleft on developer-facing surfaces (CLI, SDK, schemas, validators) — scares enterprise + government adopters
- Fully-closed stance on the developer surface — kills adoption

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel. Each produces a standalone findings section.

### Subagent 1: Feature Boundary Leakage Scanner

**Goal:** Find enterprise-tier logic that has leaked into community code, or community features that are accidentally gated.

**Process:**
1. Search for enterprise concepts in community code:
   ```bash
   grep -rn "saml\|scim\|provisioning" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
   grep -rn "white.label\|brand\|powered.by\|oem" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules
   grep -rn "approval\|workflow\|draft.*review\|publish.*state" backend/app/ --include="*.py" | grep -v __pycache__
   grep -rn "federation\|cross.instance\|remote.catalog" backend/app/ --include="*.py" | grep -v __pycache__
   grep -rn "ai.policy\|model.routing\|allow.deny\|ai.governance\|batch.metadata" backend/app/ --include="*.py" | grep -v __pycache__
   grep -rn "airgap\|air.gap\|govcloud\|gov.cloud\|offline.deploy" . --include="*.py" --include="*.yml" --include="*.yaml" | grep -v __pycache__ | grep -v node_modules
   ```
2. Search for **multi-tenant** identifiers (multi-tenant isolation is enterprise-only; multi-user collaboration in a single deployment is fine):
   ```bash
   grep -rn "tenant_id\|multi.tenant\|cross.org\|tenant.isolation" backend/app/ --include="*.py" | grep -v __pycache__
   grep -rn "org_id\|organization" backend/app/ --include="*.py" | grep -v __pycache__
   ```
   Classify each hit:
   - If used for *multi-tenant isolation* (tenant-scoped data partitioning, cross-tenant admin) → **boundary violation in community** unless cleanly behind a seam.
   - If used as *forward-compatible schema scaffolding* (e.g., a nullable `org_id` column with a default of 1) without gating any feature → 🟢 acceptable.
   - If `workspace_id` / `team_id` / similar collaborative scoping → 🟢 fine; that's multi-user, not multi-tenant.
3. Search for accidental gating of community features:
   ```bash
   grep -rn "license\|tier\|plan\|enterprise\|premium\|pro_only\|paid" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v node_modules | grep -v ".pyc"
   ls backend/app/standards/ogc/router.py backend/app/standards/stac/router.py backend/app/standards/dcat/router.py 2>/dev/null && \
     grep -i "permission\|role\|gate\|restrict\|enterprise" backend/app/standards/ogc/router.py backend/app/standards/stac/router.py backend/app/standards/dcat/router.py 2>/dev/null
   ```
4. Search for **persistent external-source credentials** (stored creds for scheduled re-sync are enterprise; one-shot import using transient creds is fine):
   ```bash
   grep -rn "credential\|secret\|connector.*config\|scheduled.*sync\|mirror" backend/app/modules/catalog/ --include="*.py" | grep -v __pycache__
   grep -rn "Credential\|StoredSecret\|ConnectorConfig" backend/app/ --include="*.py" | grep -v __pycache__
   ```
   Hits that *store* credentials for later use → flag as enterprise feature in community without seam.
5. **Verify `is_enterprise()` gating pattern** (Phase 219 canonical pattern). For any feature with both community-acceptable and enterprise-only behaviors (e.g., OAuth IdP→role mapping, attribute-based provisioning, scheduled connectors), check that:
   - **Schema layer** rejects enterprise-only inputs in community: Pydantic `model_validator(mode="after")` raises `ValueError("... requires the GeoLens Enterprise overlay")` when an enterprise-only field is set and `is_enterprise()` is False.
   - **Service layer** wraps enterprise-only logic in `if is_enterprise():` before applying it.
   - **Both layers must agree** — schema-only gating leaves drift via bulk import paths; service-only gating accepts data that can never be applied. Phase 219 reference implementation: `oauth/schemas.py:147,285` + `oauth/service.py:265-270`.

   Hits that gate at only one layer → 🟡 boundary risk; hits that don't gate at all → 🔴 boundary violation.
6. For each hit, classify as:
   - **🔴 Boundary violation** — enterprise logic in community code
   - **🟡 Boundary risk** — community feature with enterprise-suggestive patterns
   - **🟢 Clean** — correctly scoped (including documented carve-outs from `## WHAT NOT TO FLAG`)

**Output:** Table of findings with file:line, classification, and recommendation.

---

### Subagent 2: Extension Seam Quality Audit

**Goal:** Assess the *quality* and *coverage* of the existing extension seam infrastructure. The repo already has `backend/app/platform/extensions/` (protocols.py, defaults.py, guards.py). Audit whether seams exist for every enterprise-relevant domain and whether they're cleanly factored.

**Process:**
1. Inventory the existing seam infrastructure:
   ```bash
   ls backend/app/platform/extensions/
   cat backend/app/platform/extensions/protocols.py
   cat backend/app/platform/extensions/defaults.py
   cat backend/app/platform/extensions/guards.py
   grep -rn "Protocol\|ABC\|abstractmethod\|register_provider\|register_hook\|extensions\." backend/app/ --include="*.py" | grep -v __pycache__
   ```
2. Audit the 9 priority seam areas. For each, locate the existing seam (if any), verify it's wired to a real call site, and rate:
   - **Identity protocol** (v13.1 Phase 214) — Read `backend/app/core/identity.py`. Is `IdentityProtocol` defined? Is `get_identity_extension()` the typed accessor for enterprise overlays? Are 51 cross-domain `User` import sites typed against `Identity` rather than the concrete model? Is the extension hook proven by the SAML overlay's `IdentityExtension` registration?
   - **Auth provider registry** — Read `backend/app/modules/auth/`. Is SAML/SCIM hookable via `AuthExtension` Protocol + `importlib.metadata` entry_points? Does the OAuth provider directory support enterprise IdPs as a drop-in? (v13.1 verified the SAML overlay dual-registers `AuthExtension` + `IdentityExtension` end-to-end.)
   - **Audit sink/export registry** — Read `backend/app/modules/audit/`. Can export targets (S3, SIEM, syslog) be added without modifying `router.py`?
   - **Branding/theme provider** — Read `backend/app/modules/settings/` and `frontend/src/**/theme*`. Is the "Powered by GeoLens" toggle implementable via the seam?
   - **Policy/permission hooks** — Read `backend/app/modules/auth/permissions.py` and `backend/app/modules/catalog/authorization.py` (relocated from `auth/visibility.py` in v13.1 Phase 213). Are permission checks hookable for field-level/dataset-level RBAC?
   - **Workflow / approval hooks** — Is there any state-machine pattern that could support draft → review → publish without core changes?
   - **AI provider registry** — Where are AI calls dispatched from? Is there a provider abstraction allowing enterprise-only model routing / policy enforcement?
   - **Persistent connector registry** — Is there an extension point for adding stored-credential connectors with scheduled sync (S3, WFS, ArcGIS, PostGIS) without modifying the core ingestion path?
   - **Tenant scoping hooks** — If/when multi-tenant isolation lands, are data-access paths factored so a tenant filter can be injected via the seam (rather than hardcoded scoping in queries)?
3. For each seam, rate:
   - **🟢 Ready** — Clean interface exists; enterprise overlay could plug in today.
   - **🟡 Adaptable** — Would need 1–2 days of refactoring to introduce or extend the seam.
   - **🔴 Monolithic** — Tightly coupled; would need significant refactoring.

**Output:** Table of 8 seams with readiness rating, current architecture description (1–2 sentences citing files), and effort estimate.

---

### Subagent 3: Feature Inventory Verification

**Goal:** Verify the GTM docs' feature claims against what actually exists in the codebase. Catch phantom features and undocumented capabilities.

**Process:**
1. For each Community Edition feature in the boundary rules above, verify existence:
   - Find the relevant backend module(s) and frontend component(s).
   - Check if the feature is functional (has routes, services, models, UI) vs. stubbed.
   - Note any gaps between the GTM claim and implementation.
2. For each Enterprise-tier feature (Team / Business / Enterprise), check for partial implementations:
   - Existing code that partially covers the paid feature.
   - Database models or migrations that support paid concepts.
   - Frontend components or routes for paid features.
   - Configuration or environment variables for paid toggles.
3. Look for undocumented features not in the GTM docs:
   ```bash
   grep -l "APIRouter\|router" backend/app/**/*.py 2>/dev/null
   ls frontend/src/**/*Page*.tsx frontend/src/**/*page*.tsx 2>/dev/null
   ```

**Output:** Two tables (don't quote precise feature counts — derive from the boundary rules at runtime):
1. Community features: Feature | Claimed | Actual Status | Evidence (file paths) | Gaps
2. Enterprise features: Feature | Claimed Tier | Current State | Partial Implementations | Distance to MVP

---

### Subagent 4: Deployment Separation Audit

**Goal:** Assess whether the deployment infrastructure supports clean Community / Enterprise packaging.

**Process:**
1. Examine Docker and deployment configuration:
   ```bash
   cat docker-compose.yml
   cat docker-compose.enterprise.yml 2>/dev/null  # known to exist
   cat docker-compose.demo.yml 2>/dev/null
   find backend frontend -maxdepth 2 -name "Dockerfile*" -exec cat {} \;
   ls -la deployment/ 2>/dev/null && echo "deployment/ exists" || echo "deployment/ MISSING — flag as gap"
   find . -name "Chart.yaml" -o -name "values.yaml" -not -path "*/node_modules/*" 2>/dev/null | head -20
   ```
2. **Audit the existing `docker-compose.enterprise.yml` overlay for correctness:**
   - What enterprise services does it add? (List them.)
   - Does it correctly *avoid* hardcoding enterprise modules into the base compose file?
   - Does it use volume mounts / env injection rather than image rebuilds for enterprise features?
   - Does the base `docker-compose.yml` have any enterprise-suggestive references that should be moved into the overlay?
3. Check for environment-driven feature toggling:
   ```bash
   grep -rn "ENTERPRISE\|EDITION\|TIER\|LICENSE_KEY\|FEATURE_FLAG" backend/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.env*" --include="*.yml" | grep -v __pycache__ | grep -v node_modules
   cat .env.example 2>/dev/null || cat .env.sample 2>/dev/null
   ```
4. Check for any Dockerfile multi-stage patterns that suggest a per-edition build.

**Output:** Deployment readiness assessment with:
- Current packaging model (community + enterprise overlay status)
- Correctness of existing `docker-compose.enterprise.yml` (does it follow open-core hygiene?)
- Environment variable strategy assessment
- Conditional module loading feasibility
- Blockers for clean Community / Enterprise packaging

---

### Subagent 5: Codebase Coupling Analysis

**Goal:** Identify tight coupling between domains that would complicate enterprise extraction or overlay.

**Process:**
1. Map cross-domain imports (note: repo uses `from app.`, not `from backend.app.`):
   ```bash
   for dir in backend/app/modules/*/; do
     domain=$(basename "$dir")
     [ "$domain" = "__pycache__" ] && continue
     echo "=== $domain ==="
     grep -rh "^from app\." "$dir" --include="*.py" 2>/dev/null | sort -u
   done
   ```
2. Identify shared models/state that enterprise features would need to modify:
   ```bash
   grep -rn "^from app\..*models import\|^from app\.models" backend/app/ --include="*.py" | grep -v __pycache__ | awk -F: '{print $2}' | sort | uniq -c | sort -rn | head -20
   ```
3. Identify shared dependencies on core/db (use Python to extract domain robustly):
   ```bash
   grep -rln "^from app\.\(core\|db\|platform\)" backend/app/modules/ --include="*.py" 2>/dev/null | python3 -c "
import sys, collections, os
counts = collections.Counter()
for line in sys.stdin:
    parts = line.strip().split(os.sep)
    if 'modules' in parts:
        i = parts.index('modules')
        if i + 1 < len(parts):
            counts[parts[i+1]] += 1
for k, v in counts.most_common():
    print(f'{v:5d} {k}')
"
   ```
4. For the **6 enterprise-relevant surfaces** (auth, audit, admin, settings, catalog, plus AI dispatch wherever it lives — likely `backend/app/services/ai*` or similar; grep to locate), measure:
   - Inbound dependencies (who imports from this domain?)
   - Outbound dependencies (what does this domain import?)
   - Shared models or database tables
5. Flag circular dependencies or domains that cannot be overlaid without modifying core.

**Output:** Dependency matrix for enterprise-relevant domains, coupling risk rating (🟢 Low / 🟡 Medium / 🔴 High), and specific decoupling recommendations.

---

### Subagent 6: Open-Source Surface & Licensing Readiness

**Goal:** Audit the developer-facing open-source surface (CLI, SDKs, schemas, validators) and verify licensing aligns with an open-core strategy. The strategic guidance positions the developer surface as the adoption wedge.

**Process:**
1. Inventory the open-source developer surface:
   ```bash
   ls cli/ sdks/ sdk/ tools/ packages/ 2>/dev/null
   find . -maxdepth 3 -type d \( -name "cli" -o -name "sdk" -o -name "sdks" -o -name "geolens-cli" -o -name "geolens-sdk" \) 2>/dev/null
   ls sdks/python/ sdks/typescript/ 2>/dev/null  # v13.1 added auto-generated SDKs
   find . -maxdepth 3 -name "pyproject.toml" -not -path "*/node_modules/*" -not -path "*/.venv/*" 2>/dev/null
   find . -maxdepth 3 -name "package.json" -not -path "*/node_modules/*" 2>/dev/null
   ls backend/openapi.json 2>/dev/null  # SDK source-of-truth committed in v13.1
   ```
2. Verify licensing — including byte-identity across the OSS surface (the v13.1 close audit established Apache-2.0 as the baseline; CLI + both SDK LICENSE files should be byte-identical):
   ```bash
   ls -la LICENSE* COPYING* 2>/dev/null
   find . -maxdepth 4 -name "LICENSE*" -not -path "*/node_modules/*" -not -path "*/.venv/*" 2>/dev/null
   # Byte-identity check across CLI + SDK LICENSEs (all should be Apache-2.0 byte-identical)
   for L in cli/LICENSE sdks/python/LICENSE sdks/typescript/LICENSE; do
     [ -f "$L" ] && (diff -q "$L" sdks/python/LICENSE 2>/dev/null || echo "$L missing")
   done
   grep -rln "GPL\|AGPL\|copyleft" backend/app/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" 2>/dev/null | head -20
   # OCCLI-06 invariant verify: zero direct HTTP imports in CLI source
   grep -rE '^(import|from) (httpx|requests)' cli/geolens_cli/ 2>/dev/null
   ```
3. Check for declarative-config / catalog-manifest patterns (the strategy suggests a `geolens.yaml` ecosystem artifact):
   ```bash
   find . -maxdepth 3 \( -name "geolens.yaml" -o -name "geolens.yml" -o -name ".geolensrc*" \) 2>/dev/null
   grep -rln "manifest\|geolens.config\|catalog.yaml" backend/app/ --include="*.py" | grep -v __pycache__ | head -10
   ```
4. Rate readiness across these dimensions:
   - **CLI exists?** (Y/N + path) — if N, flag P0 for open-core launch.
   - **SDK exists?** (Y/N + path + language[s]) — if N, flag P1.
   - **Schema/validator package extractable?** — Are dataset/metadata schemas in a directory that could be packaged separately?
   - **License file present + correct?** Apache 2.0 / MIT recommended for developer surface; proprietary expected for enterprise modules.
   - **Copyleft contamination?** Any GPL/AGPL imports in code intended to be permissively licensed?
   - **Catalog manifest?** Does any declarative-config pattern exist that could become the ecosystem artifact?

**Output:** Table of OSS-surface dimensions with readiness rating and specific gaps. Include a separate "License findings" subsection citing each LICENSE file found and any contamination risk.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

Assign a letter grade (A–F) to each dimension:

| Dimension | What it measures |
|-----------|-----------------|
| **Boundary Integrity** | Is enterprise logic cleanly absent from community code? |
| **Seam Quality** | Do existing extension seams cover all enterprise-relevant domains with clean factoring? |
| **Inventory Accuracy** | Do GTM docs match reality? |
| **Deployment Separation** | Can community and enterprise ship as distinct packages? |
| **Coupling Health** | Are enterprise-relevant domains loosely coupled enough to overlay? |
| **OSS Surface Readiness** | Is the developer-facing open-source surface (CLI, SDK, schemas, license) credible? |

Compute an **overall readiness score** as the unweighted average of these grades (A=4, B=3, C=2, D=1, F=0).

### Action Items

Generate a prioritized action item list. Each item must include:

| Field | Description |
|-------|-------------|
| Priority | P0 (do before any open-core launch), P1 (do alongside first paid feature), P2 (do when scaling) |
| Action | Specific, implementable task |
| Domain | Which backend/frontend domain is affected |
| Effort | Hours or person-days estimate |
| Rationale | Why this matters for open-core health |
| Blocks | What product features or tiers this unblocks |

Sort by priority, then by effort (smallest first within each priority level).

---

## DELIVERY

### Output format

Ensure the output directory exists, then write the report:

```bash
mkdir -p docs-internal/audits
```

Write to: `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Open-Core Separation Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades table (6 dimensions) + overall score -->

## Executive Summary
<!-- 3-5 sentences: current state, biggest risks, top recommendation -->

## 1. Feature Boundary Leakage
<!-- Subagent 1 findings -->

## 2. Extension Seam Quality
<!-- Subagent 2 findings -->

## 3. Feature Inventory Verification
### 3a. Community Edition
### 3b. Enterprise Edition
<!-- Subagent 3 findings -->

## 4. Deployment Separation
<!-- Subagent 4 findings -->

## 5. Codebase Coupling
<!-- Subagent 5 findings -->

## 6. OSS Surface & Licensing
<!-- Subagent 6 findings -->

## 7. Prioritized Action Items
<!-- Synthesized action items table -->

## 8. Comparison to Prior Audit
<!-- If GTM-EVALUATION.md or a prior dated audit exists, diff key findings. What changed? What regressed? -->
```

### Post-delivery

After writing the report:
1. Print a one-line summary of the overall score and top P0 action item.
2. If a `lessons.md` exists at the project root, in `.planning/`, or `docs-internal/`, append any reusable architectural insights discovered during this audit (skip silently if no such file exists — do not create one).

---

## WHAT NOT TO FLAG

Avoid false positives. Do NOT flag:

- **Basic OIDC/OAuth in community code** — explicitly free-tier. Only SAML and advanced IdP mapping are enterprise.
- **Basic audit log viewing/searching** — community includes viewing and searching audit events. Only export and compliance reports are paid.
- **Dataset-level grants (DatasetGrant model)** — the model existing in community is fine. The enterprise part is the admin UI and field-level permissions.
- **Single-shot interactive AI (chat-style map generation, one-off styling tweak, manual metadata field assistance)** — these are free. Only batch/automated/policy-controlled AI is paid.
- **Theme provider in frontend** — a general theme system is fine. Only "remove GeoLens branding" toggle and full white-label are paid.
- **Feature flags for internal dev purposes** — only flag feature flags that gate community features for upsell.
- **Settings module having many config options** — settings is inherently a configuration surface. Only flag enterprise-specific policy config in the community settings module.
- **Multi-user collaboration in a single deployment** — multiple users sharing collections/maps in one deployment is FREE. Only multi-*tenant* isolation (multiple separate orgs in one deployment) is enterprise.
- **`org_id` / `workspace_id` columns in core models** — acceptable as forward-compatible scaffolding *if* they don't gate any feature in community. Flag only if used to drive multi-tenant isolation, cross-org admin, or feature gating.
- **`backend/app/platform/extensions/` Protocol files** — these ARE the seams; their existence is a positive signal, not a violation.
- **`docker-compose.enterprise.yml` referencing enterprise services** — that's its job. Flag only if the *base* compose file has enterprise references.
- **API keys / token management infrastructure in Community** — basic per-user keys are free. Flag only if quotas, usage tracking, or admin token management are absent in expected enterprise tiers (gap, not violation).
- **WFS / ArcGIS / S3 import code paths in community** — one-shot user-driven import is free regardless of source. Flag only if the code stores credentials for *scheduled re-sync* (that's enterprise).
- **Pitfall 11 SAML scaffolding in core (v13.1 documented carve-out)** — the v13.1 milestone close audit explicitly accepted SAML-related scaffolding in 5 core files as a HIGH-severity column-not-found mitigation:
  - `backend/app/modules/auth/oauth/models.py` — `saml_*` columns declared with `deferred=True`
  - `backend/app/modules/auth/oauth/schemas.py` — SAML enum literal + 4 SAML fields + per-type `model_validator(mode="after")`
  - `backend/app/modules/auth/oauth/service.py` — SAML enum literal + `is_enterprise()` gate at IdP→role mapping
  - `backend/app/modules/settings/router.py` — `SECRET_FIELDS` / `SECRET_BODY_FIELDS` audit-snapshot redaction including SAML keys
  - `backend/app/modules/auth/dependencies.py` — `get_identity_extension()` consumption (this one is the canonical extension hook, never a violation)

  Flag SAML hits only if scope expands beyond these 5 files OR if the `deferred=True` mitigation is removed without replacement. Cite `oc-separation-audit-v13.1-close.md` §SC#1 for the rationale.
- **CLI lazy `import httpx` for exception types only (v13.1 INTG-02 carve-out)** — `cli/geolens_cli/_sdk_helpers.py:68` contains an *indented* `import httpx` used solely to catch exception types from the SDK-owned client. The CI gate (`^(import|from) (httpx|requests)`) is line-anchored and explicitly allows this carve-out. Module header documents it. Flag only if non-indented top-level `httpx`/`requests` imports appear in `cli/`, OR if the indented import starts constructing `Client` objects (real HTTP).
