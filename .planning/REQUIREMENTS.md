# Requirements: v13.4 Boundary Closeout

**Milestone goal:** Close the last 🔴 seams from `oc-separation-audit-20260430-b.md` and the last residual gaps from `oc-separation-audit-20260502.md` — invert BOTH directions of the catalog↔processing cycle, make AI providers (chat + embedding) extensible, and finish remaining open-core publish hygiene — so v14.0 can launch on architecturally clean ground.

**Audit-grade targets:** Boundary Integrity A+ (hold); Coupling Health B → **A−** (BOTH cycle directions broken via Phase 225 + 230); Seam Quality B+ → **A−** (Phase 226 + 231 close all Enterprise-relevant 🔴 in the AI domain).

**Roster expansion (2026-05-02):** Phase 230 (CatalogPort) + Phase 231 (EmbeddingProviderExtension) added after the 2026-05-02 oc-audit identified residual gaps post-Phase-226: (a) Phase 225 only inverted the `processing → catalog` direction — 17 top-of-file `catalog → processing` imports remained; (b) 1 direct provider-SDK import remained at `processing/embeddings/helpers.py:8`. Both phases promoted from backlog (former 999.20 + 999.19). Coupling Health target lifted from B+ → A− as a result.

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

- [x] **TESTFIX-01**: `_regenerate_saml_fixtures` autouse fixture writes signed XML responses to a session-scoped pytest `tmp_path` instead of mutating committed `backend/tests/fixtures/saml/idp_response_*.xml.b64` files
- [x] **TESTFIX-02**: `git status` is clean after a full `pytest backend/tests/test_saml_overlay.py` run (regression: was always-dirty after every test invocation)
- [x] **TESTFIX-03**: Existing committed `.xml.b64` files are renamed to `.xml.b64.template` (immutable templates) or removed entirely — the docstring's "CI fallback when pysaml2 unavailable" claim is either truly restored or explicitly removed

### Cold Publish Workflows (Phase 228)

- [x] **PUBLISH-01**: `secrets.NPM_TOKEN` is confirmed present and `secrets.PYPI_TOKEN` is absent because PyPI publishes use Trusted Publishing via `id-token: write`
- [x] **PUBLISH-02**: `.github/workflows/publish-sdks.yml` runs end-to-end at least once, publishing `geolens` to PyPI and verifying `@geolens/sdk` on npm
- [x] **PUBLISH-03**: `.github/workflows/publish-cli.yml` runs end-to-end at least once, publishing the `geolens-cli` distribution to PyPI
- [x] **PUBLISH-04**: README install instructions are validated against the published artifacts (`pip install geolens`, `npm install @geolens/sdk`, `pip install geolens-cli` succeed on a clean machine)

### Symmetric CatalogPort Protocol (Phase 230)

- [ ] **CATPORT-01**: A `CatalogPort` Protocol exists at `backend/app/core/catalog_port.py` mirroring the `ProcessingPort` shape from Phase 225, opposite direction (exposes processing-owned types catalog modules need)
- [ ] **CATPORT-02**: The 17 existing top-of-file `catalog/*` → `processing/*` imports rewire through Protocol-typed boundaries (no module-level cross-domain imports). Function-local deferred imports inside catalog are explicitly permitted (mirror Phase 225 scoping)
- [ ] **CATPORT-03**: High-leverage call sites consume processing data via the Port: `catalog/maps/service.py:25` (RasterAsset), `catalog/layers/service.py:15-26`, `catalog/search/service.py:44-46`, `catalog/features/service.py:12`, plus the 5 `catalog/datasets/api/router_*.py` files
- [ ] **CATPORT-04**: Architecture-guard test `test_no_catalog_imports_processing` fails CI if any `backend/app/modules/catalog/` module has a top-of-file import from `backend/app/processing/` (mirrors Phase 225's `test_no_processing_imports_catalog` pattern)
- [ ] **CATPORT-05**: Default `CatalogPort` implementation delegates to `app.processing.*` via deferred imports inside method bodies (mirror `DefaultProcessingPort` pattern); single-slot `get_catalog_port()` accessor lives at `backend/app/platform/extensions/__init__.py`; full backend test suite passes with zero functional regressions

### EmbeddingProviderExtension Protocol (Phase 231)

- [x] **EMBPROV-01**: `EmbeddingProviderExtension` Protocol added at `backend/app/platform/extensions/protocols.py` exposing `embed(texts: list[str], model: str) -> list[list[float]]` (or equivalent batch-embedding shape that matches existing call sites)
- [x] **EMBPROV-02**: `DefaultOpenAIEmbeddingProvider` at `backend/app/platform/extensions/defaults.py` resolves the community provider; `get_embedding_provider(name)` accessor follows the dict-shape pattern from `get_ai_provider(name)` (Phase 226)
- [x] **EMBPROV-03**: `backend/app/processing/embeddings/helpers.py:8` (`from openai import OpenAI`) is removed; embedding callers route through the registry. `git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returns zero hits
- [ ] **EMBPROV-04**: The existing architecture guard `test_no_module_level_provider_sdk_imports_in_processing_ai` (added 2026-05-02 commit `259ebc72`) is renamed/expanded to `test_no_module_level_provider_sdk_imports_in_processing` covering both `processing/ai/` and `processing/embeddings/`; the embeddings carve-out is removed from the guard's docstring
- [x] **EMBPROV-05**: Existing embeddings tests pass unchanged with the default provider wired (no behavior delta for community); a test overlay registered via `importlib.metadata` entry_points is dispatched correctly without modifying any core file

### Post-Implementation Audit Gate (Phase 229)

- [ ] **PIAUDIT-01**: A `/post-impl` audit produces a dated `docs-internal/audits/post-impl-2026MMDD-*.md` report covering the v13.4 implementation surface (Phases 225–228 + 230 + 231)
- [ ] **PIAUDIT-02**: All P1 findings from the audit are either fixed inline or explicitly deferred with rationale + a tracked backlog phase
- [ ] **PIAUDIT-03**: Post-audit re-run holds the milestone audit-grade targets — Boundary Integrity ≥ **A+**, Coupling Health ≥ **A−**, Seam Quality ≥ **A−**

---

## Future Requirements (deferred to later milestones)

- **Phase 999.6**: Tenant scoping infrastructure (Cloud-tier prerequisite — deferred until vendor-hosted multi-tenant SaaS is on the roadmap)
- **Phase 999.8**: PermissionExtension Protocol (P2 — field-level RBAC + ABAC unblocker)
- **Phase 999.9**: WorkflowExtension Protocol (P2 — multi-step approvals, reviewer assignment, custom states)
- **Phase 999.12**: `geolens.yaml` catalog manifest spec (P2 — biggest unshipped open-core adoption wedge, ~2 weeks)
- **Phase 999.13**: Persistent connector registry (P2 — Enterprise-tier scheduled mirroring + credential vault)
- **Phase 999.14**: Helm chart + AMI Packer pipeline (P2 — Marketplace AMI shippability)
- **Phase 999.15**: SBOM + signed image distribution (P2 — enterprise procurement gate)
- **Phase 999.16**: Extract `geolens-schemas` package (P2 — schema/validator OSS adoption)
- **Phase 999.21**: Split `catalog/maps/service.py` (P2 — 1297 LOC, next god-module candidate per `oc-separation-audit-20260502.md`)
- **Phase 999.22**: Split `catalog/search/service.py` (P2 — 1312 LOC, next god-module candidate per `oc-separation-audit-20260502.md`)
- **Phase 999.23**: Share/embed token expiration gating — product decision (P2, decision-blocked — pick Branch A "apply Phase-219 gates" or Branch B "drop from GTM Team tier"; strip-the-copy stopgap landed in commit `6db19582`)

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
| PUBLISH-01 | Phase 228 | [x] complete — Plan 02 / 228-VERIFICATION |
| PUBLISH-02 | Phase 228 | [x] complete — Plan 03 |
| PUBLISH-03 | Phase 228 | [x] complete — Plan 03 |
| PUBLISH-04 | Phase 228 | [x] complete — Plan 04 |
| CATPORT-01 | Phase 230 | [ ] not started |
| CATPORT-02 | Phase 230 | [ ] not started |
| CATPORT-03 | Phase 230 | [ ] not started |
| CATPORT-04 | Phase 230 | [ ] not started |
| CATPORT-05 | Phase 230 | [ ] not started |
| EMBPROV-01 | Phase 231 | [ ] not started |
| EMBPROV-02 | Phase 231 | [ ] not started |
| EMBPROV-03 | Phase 231 | [ ] not started |
| EMBPROV-04 | Phase 231 | [ ] not started |
| EMBPROV-05 | Phase 231 | [ ] not started |
| PIAUDIT-01 | Phase 229 | [ ] not started |
| PIAUDIT-02 | Phase 229 | [ ] not started |
| PIAUDIT-03 | Phase 229 | [ ] not started |

**Coverage:** 30/30 v13.4 requirements mapped to exactly one phase. No orphans, no duplicates. (Original 20 + 10 added 2026-05-02 with Phase 230/231 promotions.)
