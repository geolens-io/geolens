# Requirements: GeoLens v13.0 Open-Core Pre-Release

**Defined:** 2026-03-26
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v13.0 Requirements

Requirements for open-core pre-release. Each maps to roadmap phases.

### Extension Architecture

- [x] **EXT-01**: Backend discovers and loads enterprise extensions at startup via `importlib.metadata` entry_points without importing enterprise code from core
- [x] **EXT-02**: Protocol interfaces exist for auth, audit, and branding extension points that enterprise implementations can fulfill
- [x] **EXT-03**: Edition detection (`community` vs `enterprise`) is determined at startup from package presence and/or `GEOLENS_EDITION` env var
- [x] **EXT-04**: Enterprise-gated API endpoints return 404 (not 403) in community mode — no feature leakage
- [x] **EXT-05**: Existing enterprise-boundary code (OIDC advanced config, branding footer) is refactored to use extension seam interfaces

### SAML SSO

- [x] **SAML-01**: Admin can configure a SAML IdP via admin UI (metadata paste, entity ID, ACS URL display)
- [x] **SAML-02**: Users can authenticate via SP-initiated SAML flow with configured IdP
- [x] **SAML-03**: SAML assertions are validated for signatures, expiry, audience, and replay protection
- [x] **SAML-04**: SAML-authenticated users are mapped to existing accounts or auto-provisioned via the existing `find_or_create_oauth_user()` flow
- [x] **SAML-05**: SAML provider appears alongside OIDC providers on the login page

### Compliance

- [x] **COMP-01**: Admin can export audit logs as CSV from the admin UI with date range and event type filters
- [x] **COMP-02**: Admin can export audit logs as JSON from the admin UI with the same filters
- [x] **COMP-03**: Audit export streams results for large datasets (no full materialization in memory)
- [x] **COMP-04**: "Powered by GeoLens" branding in the footer is removable via a `PersistentConfig` toggle in admin settings
- [x] **COMP-05**: Branding toggle is enterprise-gated — only available when enterprise edition is detected

### Enterprise Repo

- [x] **REPO-01**: A `geolens-enterprise` repo scaffold exists with `pyproject.toml` defining entry_points that register with the core extension system
- [x] **REPO-02**: Enterprise repo installs as an editable pip package (`pip install -e`) into the existing Docker Compose setup via a compose override file
- [x] **REPO-03**: Enterprise Alembic migrations use a separate branch label and do not conflict with core migrations
- [x] **REPO-04**: At least one enterprise feature (branding toggle or SAML) lives in the enterprise repo, proving the overlay pattern end-to-end

### Licensing & Documentation

- [x] **DOCS-01**: Apache 2.0 LICENSE file exists at repo root
- [x] **DOCS-02**: README.md is rewritten for public consumption — features, screenshots, quickstart, contributing guidelines link
- [x] **DOCS-03**: Installation quickstart documentation enables a working deployment in under 10 minutes (clone, .env, docker compose up)
- [x] **DOCS-04**: CONTRIBUTING.md exists with development setup, PR guidelines, and code style notes

## v2 Requirements (Deferred)

### Enterprise Auth

- **SAML-06**: IdP-initiated SAML flow support
- **SAML-07**: SAML Single Logout (SLO)
- **SCIM-01**: SCIM user provisioning/deprovisioning from IdP

### Enterprise Features

- **ENT-01**: Multi-organization tenancy
- **ENT-02**: License key validation and expiry enforcement
- **ENT-03**: Usage metering and seat-based limits

### Documentation

- **DOCS-05**: Landing page / marketing site
- **DOCS-06**: Live demo instance with sample data

## Out of Scope

| Feature | Reason |
|---------|--------|
| IdP-initiated SAML | Complexity; SP-initiated covers 95% of use cases |
| SAML SLO | Rarely enforced at evaluation stage; defer to v2 |
| SCIM provisioning | No customer demand yet; manual user management sufficient |
| License key system | Premature; trust-based enterprise licensing first |
| Multi-org tenancy | Major architecture change; not needed for initial enterprise tier |
| Pricing page / landing site | Operational, not code — separate effort |
| Frontend module federation | Over-engineered; simple conditional imports sufficient for 3-4 enterprise components |
| Private PyPI for enterprise distribution | `pip install -e` from local clone or GitHub Packages sufficient initially |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| EXT-01 | Phase 206 | Pending |
| EXT-02 | Phase 206 | Pending |
| EXT-03 | Phase 206 | Pending |
| EXT-04 | Phase 206 | Pending |
| EXT-05 | Phase 206 | Pending |
| COMP-04 | Phase 207 | Pending |
| COMP-05 | Phase 207 | Pending |
| COMP-01 | Phase 208 | Pending |
| COMP-02 | Phase 208 | Pending |
| COMP-03 | Phase 208 | Pending |
| SAML-01 | Phase 209 | Complete |
| SAML-02 | Phase 209 | Complete |
| SAML-03 | Phase 209 | Complete |
| SAML-04 | Phase 209 | Complete |
| SAML-05 | Phase 209 | Complete |
| REPO-01 | Phase 210 | Complete |
| REPO-02 | Phase 210 | Complete |
| REPO-03 | Phase 210 | Complete |
| REPO-04 | Phase 210 | Complete |
| DOCS-01 | Phase 211 | Pending |
| DOCS-02 | Phase 211 | Pending |
| DOCS-03 | Phase 211 | Pending |
| DOCS-04 | Phase 211 | Pending |

**Coverage:**
- v13.0 requirements: 23 total
- Mapped to phases: 23
- Unmapped: 0

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-26 after roadmap creation*
