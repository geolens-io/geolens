# Open-Core Separation — Deferred Items (2026-04-26)

Items from `oc-separation-audit-20260426-b.md` that were **not** addressed in the inline remediation pass. Each is sized > 1 day and should land as its own GSD phase. Sorted by leverage within priority.

## P1 — Should ship before first paid customer

| Action | Audit ref | Effort | Why deferred | Suggested phase |
|---|---|---|---|---|
| **Auto-generate Python + TS SDKs from snapshotted OpenAPI** | §6 / §7 P1 | 3–5 days | Needs SDK tooling decision (openapi-generator vs openapi-typescript-codegen vs custom), publish targets (PyPI, npm), versioning strategy. The OpenAPI snapshot now exists (`backend/openapi.json`) so this is unblocked. | Closed by Phase 215 (2026-04-27) |
| **Ship `geolens` CLI (Apache-2.0)** | §6 / §7 P1 | 1–2 weeks | Largest item in the bucket. Needs scope decision for which commands to ship (`scan`, `publish`, `export stac`, `login`), packaging story, distribution channel. The strategy's adoption wedge. | Closed by Phase 216 (2026-04-27) |
| **Refactor `auth/visibility.py` → `catalog/authorization.py`** | §5 / §7 P1 | 1–2 days | Touches 23 files (15 inbound visibility imports + 8 deferred-import callers). Mechanical but needs careful test coverage to avoid regressing dataset visibility. | Closed by Phase 213 (2026-04-27) |
| **Extract `IdentityProtocol` in `core/identity.py`** | §5 / §7 P1 | 3–5 days | Touches 51 `User` import sites across 11 domains. Prerequisite for any clean enterprise auth overlay (SAML, SCIM, multi-org). | Closed by Phase 214 (2026-04-27) |
| **Reintroduce SAML auth properly** | §3 / §7 P1 | 2–3 weeks | Migration `2026_04_08_0001` removed the dead scaffold. Government buyers mandate SAML. Should land as part of an `auth-saml-overlay` enterprise extension, not back into core. | Closed by Phase 217 (2026-04-29) |
| **Break `core ↔ settings` layering inversion** | §5 (new finding) | 1–2 days | `core/persistent_config.py:30` and `core/public_urls.py:14` import `AppSetting` from `modules/settings`. Either move `AppSetting` to `core/db/models.py` or invert by registering a config provider into core at startup. | Closed by Phase 212 (2026-04-27) |

## P2 — Address as enterprise tier ships

| Action | Audit ref | Effort | Why deferred |
|---|---|---|---|
| **Convert `processing/ai/llm_loop.py` provider dispatch into a registry** | §2 / §7 P2 | 1–2 days | Currently `if/elif provider == "anthropic" / "openai_compatible"`. Needs `AIExtension` Protocol design before mechanical refactor. |
| **Extend `BrandingExtension` with logo/colors/favicon/footer fields** | §2 / §7 P2 | 1 day | Today only `show_badge` exists; extension is wired (this remediation pass). Adding more keys requires schema decisions and a migration for `PersistentConfig` entries. |
| **Move `audit.service.log_action` behind `core/audit_port.py`** | §5 / §7 P2 | 1 day | 14 distinct call sites need migration. |
| **Define `geolens.yaml` catalog manifest spec** | §6 / §7 P2 | 1 week design + 2–3 weeks impl | Defer until CLI usage signals shape. |
| **Build dataset-level RBAC admin UI on existing `DatasetGrant` model** | §3 / §7 P2 | 2–3 weeks | DatasetGrant model exists; needs full UI design + grant-management workflow. Frontend-heavy. |
| **Introduce workflow state machine with extension validators** | §2 / §7 P2 | 3–5 days | `ALLOWED_TRANSITIONS` is a dict literal at `catalog/datasets/api/router_data.py:210`. Needs `WorkflowExtension` Protocol design + reviewer/approver model. |
| **Add `PermissionExtension` Protocol with `should_allow()` hook** | §2 / §7 P2 | 2–3 days | Permission checks are static matrix in `auth/permissions.py:28-74`. Field-level RBAC needs hooks. |
| **Frontend code-splitting for enterprise components** | §4 / §7 P2 | 1 day | `vite.config.ts:28-60` `manualChunks` has no enterprise split today. Bundle inflation grows linearly with enterprise UI. |
| **Add `CatalogReadModel` façade for standards & processing** | §5 / §7 P2 | 3–5 days | 15+ direct imports of `catalog.datasets.domain.models` from standards/processing. |
| **Split `catalog/datasets/domain/service.py`** | §5 / §7 P2 | 1 week | Densest cycle hub: 29 function-scoped `from app.` imports. |
| **Persistent connector registry (`SourceAdapter` Protocol + `Connector` model)** | §2 / §7 P2 | 4–5 days | `adapters/__init__.py` is empty; no encrypted credential store; no scheduling. Foundation for the Business-tier "stored-cred connectors" feature. |
| **Schema editor UI (rename + alter type)** | §3 / §7 P2 | 1–2 days | **Backend now exists** (this remediation pass: `PATCH /layers/{id}/columns/{name}/{name,type}`). UI in `frontend/src/components/dataset/SchemaEditor.tsx` still needs the rename/alter affordances. |
| **Publish enterprise via wheel/private index** | §4 / §7 P2 | 2–3 days | Current overlay only works with sibling source clone. |
| **Migration overlay duplicate `uv add` cleanup** | §4 (carried) | 1 hour | `docker-compose.enterprise.yml` `migrate` and `api-entrypoint.sh` both run `uv add --editable`. Drop one. |
| **Move AWS Marketplace billing to enterprise overlay via `BillingExtension.on_startup()` hook** | v13.1-close §1 / Triage #2 | 1–2 days | Demoted from P1 in v13.1 close (oc-separation-audit-v13.1-close.md) — inert when `AWS_MARKETPLACE_PRODUCT_CODE` unset, no community deployment triggers it accidentally. Architectural cleanup, not a v13.1 close blocker. Loci: `core/marketplace.py`, `core/config.py:87-88, 108`, `api/main.py:184-203`, `docker-compose.yml:128-129`. |
| **Activate CLI + SDK distribution to PyPI/npm (org claim + token wire-up + first publish)** | v13.1-close §6 / Triage #6 | 0.5–1 day | Demoted from P1 in v13.1 close — built wheels and npm artifacts exist; gap is one-time PyPI/npm credential setup + first publish run. v13.1 close criterion is "CLI + SDKs exist Apache-2.0" (✓), not "are installable from public registries". Workflow at `.github/workflows/publish-sdks.yml`; no `publish-cli.yml` yet. |

## P3 — Post-traction

| Action | Audit ref | Effort |
|---|---|---|
| **Helm chart for K8s deployment** | §4 / §7 P3 | 1 week |
| **Tenant scoping infrastructure** | §2 (Seam #8) | 1–2 weeks+ (architectural) |

## What was addressed in this pass

See commit log on this date. Briefly:
1. Audit-log export route now requires enterprise edition AND consults `AuditExtension.get_export_formats()` (closes the morning audit's open P0 boundary violation).
2. `_require_enterprise_for_key()` now returns 404 (not 403) with no detail body, matching `guards.py:require_enterprise()` design.
3. `BrandingExtension` Protocol now consulted by `GET /settings/branding/`.
4. Three `*Extension` Protocols now reachable via typed `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` accessors with community-default fallback.
5. OpenAPI snapshot committed at `backend/openapi.json` + `make openapi` / `make openapi-check` targets + CI drift check.
6. GTM `free-vs-enterprise.md` updated with SAML status callout and undocumented-capabilities tier-decision table.
7. `rename_column` + `alter_column_type` backend endpoints added at `PATCH /layers/{id}/columns/{name}/{name,type}` (4-audit-running gap closed on the backend; UI follow-up listed above).

The unchanged audit grades are: Boundary B → **A− once enterprise overlay tests in CI**, Seam Quality C → **B once these P1 items land**, Inventory A−, Deployment A, Coupling C, OSS Surface D → **C once SDK + CLI ship**.
