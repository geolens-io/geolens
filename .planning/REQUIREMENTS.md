# Requirements: v13.4 Boundary Closeout

**Milestone goal:** Close the last 🔴 seams from `oc-separation-audit-20260430-b.md` — invert the catalog↔processing cycle, make AI providers extensible, and finish remaining open-core publish hygiene — so v14.0 can launch on architecturally clean ground.

**Audit-grade targets:** Boundary Integrity A+ (hold); Coupling Health B → **B+** (cycle broken); Seam Quality B+ → **A−** (AI seam closes last 🔴).

---

## v13.4 Requirements

### ProcessingPort Protocol (Phase 225)

- [x] **PROCESS-01**: A `ProcessingPort` Protocol exists in `backend/app/core/` mirroring the `IdentityProtocol` pattern from Phase 214
- [x] **PROCESS-02**: The 8 existing `processing/*` → `catalog/*` imports rewire through Protocol-typed boundaries (no direct cross-domain imports)
- [x] **PROCESS-03**: AI features (`processing/ai/chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog data via the Protocol, not direct imports
- [x] **PROCESS-04**: Architecture-guard test `test_no_processing_imports_catalog` fails CI if any `backend/app/processing/` module imports from `backend/app/modules/catalog/` (mirrors Phase 222's AUDIT-02 pattern)
- [x] **PROCESS-05**: Default ProcessingPort implementation preserves all existing behavior with zero functional regressions in the test suite

### AIProviderExtension Protocol (Phase 226)

- [x] **AIEXT-01**: `AIProviderExtension` Protocol added at `backend/app/platform/extensions/protocols.py` exposing `complete(messages, tools)` and `stream(messages, tools)` methods
- [x] **AIEXT-02**: `DefaultAIProviderExtension` maps the 2 community providers (Anthropic native + OpenAI-compatible) via the same accessor pattern as `BillingExtension` and `AuditSink`
- [x] **AIEXT-03**: Hardcoded `if/elif provider == "anthropic"/"openai_compatible"` dispatch (`processing/ai/llm_loop.py:117,132`, `service.py:387-398`) is replaced with extension lookup
- [x] **AIEXT-04**: Overlays can register Bedrock / Vertex / Azure / vLLM via `importlib.metadata` entry_points
- [x] **AIEXT-05**: Architecture-guard test verifies no `if provider ==` branches remain in `processing/ai/` after the migration

### SAML Test Fixture Hygiene (Phase 227)

- [ ] **TESTFIX-01**: `_regenerate_saml_fixtures` autouse fixture writes signed XML responses to a session-scoped pytest `tmp_path` instead of mutating committed `backend/tests/fixtures/saml/idp_response_*.xml.b64` files
- [ ] **TESTFIX-02**: `git status` is clean after a full `pytest backend/tests/test_saml_overlay.py` run (regression: was always-dirty after every test invocation)
- [ ] **TESTFIX-03**: Existing committed `.xml.b64` files are renamed to `.xml.b64.template` (immutable templates) or removed entirely — the docstring's "CI fallback when pysaml2 unavailable" claim is either truly restored or explicitly removed

### Cold Publish Workflows (Phase 228)

- [ ] **PUBLISH-01**: `secrets.PYPI_TOKEN` and `secrets.NPM_TOKEN` are confirmed present (or migrated to PyPI Trusted Publishing via `id-token: write` permission)
- [ ] **PUBLISH-02**: `.github/workflows/publish-sdks.yml` runs end-to-end at least once, publishing `geolens-sdk` to PyPI and `@geolens/sdk` to npm
- [ ] **PUBLISH-03**: `.github/workflows/publish-cli.yml` runs end-to-end at least once, publishing `geolens` CLI to PyPI
- [ ] **PUBLISH-04**: README install instructions are validated against the published artifacts (`pip install geolens-sdk`, `npm install @geolens/sdk`, `pip install geolens` succeed on a clean machine)

### Post-Implementation Audit Gate (Phase 229)

- [ ] **PIAUDIT-01**: A `/post-impl` audit produces a dated `docs-internal/audits/post-impl-2026MMDD-*.md` report covering the v13.4 implementation surface
- [ ] **PIAUDIT-02**: All P1 findings from the audit are either fixed inline or explicitly deferred with rationale + a tracked backlog phase
- [ ] **PIAUDIT-03**: Post-audit re-run holds the milestone audit-grade targets — Boundary Integrity ≥ **A+**, Coupling Health ≥ **B+**, Seam Quality ≥ **A−**

---

## Future Requirements (deferred to later milestones)

- **Phase 999.6**: Tenant scoping infrastructure (Cloud-tier prerequisite — deferred until vendor-hosted multi-tenant SaaS is on the roadmap)
- **Phase 999.8**: PermissionExtension Protocol (P1 — field-level RBAC + ABAC unblocker)
- **Phase 999.9**: WorkflowExtension Protocol (P1 — multi-step approvals, reviewer assignment, custom states)
- **Phase 999.12**: `geolens.yaml` catalog manifest spec (P1 — biggest unshipped open-core adoption wedge, ~2 weeks)
- **Phase 999.13**: Persistent connector registry (P2 — Enterprise-tier scheduled mirroring + credential vault)
- **Phase 999.14**: Helm chart + AMI Packer pipeline (P2 — Marketplace AMI shippability)
- **Phase 999.15**: SBOM + signed image distribution (P2 — enterprise procurement gate)
- **Phase 999.16**: Extract `geolens-schemas` package (P2 — schema/validator OSS adoption)

---

## Out of Scope

- **Tenant isolation / multi-tenant SaaS** — Cloud tier deferred per `docs-internal/GTM/free-vs-enterprise.md` §3
- **Field-level RBAC, ABAC, custom workflow states** — gated on PermissionExtension / WorkflowExtension Protocols (separate milestones)
- **`geolens.yaml` declarative manifest** — separate ~2-week milestone for the open-core adoption wedge
- **New AI provider implementations (Bedrock / Vertex / Azure / vLLM)** — v13.4 ships only the seam; provider implementations land in overlays or follow-up milestones
- **AI policy / governance / BYO-key admin UI** — unblocked by AIEXT but not in v13.4 scope
- **Helm / AMI / SBOM** — distribution work scoped for a later milestone
- **`geolens-schemas` extraction** — OSS surface work scoped for a later milestone

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| PROCESS-01 | Phase 225 | [x] complete — Plan 01 |
| PROCESS-02 | Phase 225 | [x] complete — Plan 02 |
| PROCESS-03 | Phase 225 | [x] complete — Plan 02 |
| PROCESS-04 | Phase 225 | [x] complete — Plan 04 |
| PROCESS-05 | Phase 225 | [x] complete — Plan 01 |
| AIEXT-01 | Phase 226 | [ ] not started |
| AIEXT-02 | Phase 226 | [ ] not started |
| AIEXT-03 | Phase 226 | [ ] not started |
| AIEXT-04 | Phase 226 | [ ] not started |
| AIEXT-05 | Phase 226 | [ ] not started |
| TESTFIX-01 | Phase 227 | [ ] not started |
| TESTFIX-02 | Phase 227 | [ ] not started |
| TESTFIX-03 | Phase 227 | [ ] not started |
| PUBLISH-01 | Phase 228 | [ ] not started |
| PUBLISH-02 | Phase 228 | [ ] not started |
| PUBLISH-03 | Phase 228 | [ ] not started |
| PUBLISH-04 | Phase 228 | [ ] not started |
| PIAUDIT-01 | Phase 229 | [ ] not started |
| PIAUDIT-02 | Phase 229 | [ ] not started |
| PIAUDIT-03 | Phase 229 | [ ] not started |

**Coverage:** 20/20 v13.4 requirements mapped to exactly one phase. No orphans, no duplicates.
