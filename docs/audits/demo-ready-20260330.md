# Launch & Demo Readiness Audit — 2026-03-30

## Verdict

### 🟡 LAUNCH READY WITH CAVEATS

GeoLens can ship publicly today. The community edition is feature-complete, well-documented, secure, and deploys in under 3 minutes. Two non-blocking items should be addressed in the first week: version string placeholders and demo-mode automation.

---

## Scorecard

| Dimension | Status | Summary |
|-----------|--------|---------|
| **Cold Start** | ✅ Works | Clone → `.env` → `docker compose up` in ~90-120s. Zero manual intervention. |
| **Security** | ✅ Clean | No secrets exposed, all write endpoints auth-protected, CORS locked down. |
| **Documentation** | ✅ Launch-ready | README 9.5/10, install guide, config reference, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT all present. |
| **Demo Viability** | ⚠️ Partial | Core read-only workflows work today. Missing: demo-specific compose, auto-seed, automated reset. |
| **Branding** | ✅ Present | "Powered by GeoLens" in app footer + public viewer. Enterprise toggle implemented. |
| **Release Readiness** | ⚠️ Needs cleanup | Version strings are placeholders (`0.1.0`/`0.0.0`). All other items pass: license, CI/CD, gitignore, repo hygiene. |

---

## Executive Summary

GeoLens is substantially launch-ready. The community edition delivers all 21 GTM-claimed features. Cold-start deployment works out of the box with sensible defaults. Security posture is strong — no secrets in git, all write endpoints require auth, CORS is locked down. Documentation is comprehensive and professional. "Powered by GeoLens" branding is in place with an enterprise toggle for future monetization. The two caveats are: (1) version strings in `pyproject.toml` and `package.json` need updating from placeholders to match the `v13.0` tag, and (2) a public demo instance needs automation (compose overlay, auto-seed, periodic reset) that can be built in ~1-2 weeks.

---

## 1. Cold-Start Deployment

**Overall: ✅ Works — ~90-120s with cached images**

### Step-by-Step Walkthrough

| Step | Action | Time | Status |
|------|--------|------|--------|
| 1 | `git clone` | 10-30s | 🟢 |
| 2 | `cp .env.example .env` | 0s | 🟢 |
| 3 | `docker compose up -d` | 30-60s | 🟢 |
| 4 | db healthcheck + PostGIS/pgvector init | 10-15s | 🟢 |
| 5 | Alembic migrations (auto, via `migrate` service) | 5-10s | 🟢 |
| 6 | API startup + admin user auto-created | 15-25s | 🟢 |
| 7 | Worker + Titiler startup | 10-18s | 🟢 |
| 8 | Frontend npm ci + Vite dev server | 25-40s | 🟡 |
| 9 | Open `http://localhost:8080`, login `admin`/`admin` | 0s | 🟢 |

**Key Strengths:**
- Clean dependency DAG with explicit healthchecks on all services
- Migrations run automatically before API/worker start (dedicated `migrate` service)
- Admin user auto-created on first run when no users exist
- All ports configurable via `.env` (DB_PORT, API_PORT, FRONTEND_PORT)
- PostGIS, pgvector, pg_trgm extensions auto-installed in custom db Dockerfile

**Minor Issues:**
- 🟡 Frontend build adds 25-40s (acceptable, cached after first run)
- 🟡 API/worker log "WARNING: Alembic migration failed" when migrations already ran via `migrate` service (harmless but confusing)
- 🟡 If user forgets `cp .env.example .env`, error message is cryptic (ValidationError)

**No blocking issues detected.**

---

## 2. Security & Secrets

**Overall: ✅ Clean — no launch blockers**

| Category | Status | Details |
|----------|--------|---------|
| `.env` in git | 🟢 Clean | Properly gitignored, never in history |
| Hardcoded secrets | 🟢 Clean | Only dev defaults in `.env.example`, marked `[CHANGE IN PRODUCTION]` |
| Default credentials | 🟢 Acceptable | `admin`/`admin` + `dev-only-change-me-in-production` JWT secret — clearly marked |
| Write endpoint auth | 🟢 Clean | All POST/PUT/PATCH/DELETE require `require_permission()` or `get_current_active_user` |
| CORS | 🟢 Clean | Default is same-origin only (empty allowlist). Rejects `*`. |
| Security headers | 🟢 Clean | CSP, X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy present |
| Rate limiting | 🟢 Clean | Auth endpoints rate-limited against brute force |
| FastAPI docs | 🟢 Clean | Auto-disabled when `LOG_JSON=true` (production mode) |
| Private keys/certs | 🟢 Clean | None found in repo |
| Database dumps | 🟢 Clean | None found |

**Deployment Security Checklist:**
- [ ] Rotate `POSTGRES_PASSWORD` (default: `geolens`)
- [ ] Rotate `JWT_SECRET_KEY` (default: `dev-only-change-me-in-production`)
- [ ] Rotate `GEOLENS_ADMIN_PASSWORD` (default: `admin`)
- [ ] Set `LOG_JSON=true` in production
- [ ] Configure `CORS_ALLOWED_ORIGINS` if cross-origin needed

---

## 3. README & Documentation

**Overall: ✅ Launch-ready — 9.3/10**

| Section | Status | Notes |
|---------|--------|-------|
| Project description | ✅ | Clear tagline + paragraph |
| Key features | ✅ | 13 categorized bullet points |
| Screenshots | ✅ | 3 hero images (catalog, dataset, map builder) |
| Quick start | ✅ | 4-step Docker Compose setup |
| Prerequisites | ✅ | Docker, RAM, disk, ports documented |
| Configuration | ✅ | Links to dedicated config reference |
| License | ✅ | Apache 2.0 badge + section |
| Contributing | ✅ | Comprehensive CONTRIBUTING.md (dev setup, commit conventions, PR process) |
| Community / Support | ✅ | GitHub Discussions + SUPPORT.md |
| Security policy | ✅ | SECURITY.md with 48-hour SLA |
| Changelog | ✅ | Maintained, v1.0 through v13.0 |
| Standards compliance | ✅ | OGC API Features/Records, STAC 1.1 badges |
| Code of Conduct | ✅ | Contributor Covenant v2.1 |
| Features list | ✅ | Dedicated FEATURES.md |

**Additional docs:** install-guide.md, configuration-reference.md, admin-guide.md, cloud-deployment.md, widget-development.md, resource-sizing.md

**Suggestions (post-launch):**
- Add installation troubleshooting section
- Add upgrade/migration guide for major versions
- Add public roadmap link
- Consider video tutorial for quick adoption

---

## 4. Demo Mode & Sample Data

**Overall: ⚠️ Partial — core workflows work, automation missing**

### What Works Today (No Changes Needed)

| Workflow | Status | Notes |
|----------|--------|-------|
| **Find data** | ✅ | Full-text + semantic search works anonymously on public datasets |
| **Visualize data** | ✅ | Map viewer + builder render public datasets. Vector + raster tiles served without auth. |
| **Share data** | ✅ | Share tokens + embed tokens work. `/m/{token}` route, `?embed=true` support. |
| **Standards** | ✅ | OGC `/collections`, STAC `/stac/`, DCAT `/api/catalog/dcat` all return real data when seeded. |
| **AI features** | ⚠️ Optional | Requires `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. Gracefully disabled when absent. |

### Sample Data Available

| Dataset | Format | Mechanism | Time |
|---------|--------|-----------|------|
| Natural Earth 1:10m (130 datasets) | GeoJSON/Shp ZIP from NACIS CDN | `scripts/seed-natural-earth.py` | ~5 min |
| E2E fixtures (2 datasets) | GeoJSON | `scripts/seed-e2e.py` | ~30s |
| ArcGIS Online public data | Feature Services | `scripts/seed-ago-data.py` | Variable |

### What's Missing

| Gap | Impact | Effort | Priority |
|-----|--------|--------|----------|
| Demo-specific compose overlay (`docker-compose.demo.yml`) | Manual config for demo deployment | 2h | P1 |
| Auto-seed service on startup | Demo launches with empty catalog | 2h | P1 |
| Automated 24h data reset | Demo data accumulates / gets polluted | 4h | P2 |
| `DEMO_MODE=true` env var (skip OAuth/email config) | Minor config friction | 2h | P2 |
| Pre-generated demo API key | Public API callers need auth workaround | 3h | P2 |

### Resource Requirements

| Service | Idle RAM | Under Load |
|---------|----------|-----------|
| db (PostGIS + pgvector) | 30MB | 200-400MB |
| api (FastAPI + GDAL) | 150MB | 200-300MB |
| worker (Procrastinate) | 50MB | 100-150MB |
| titiler (raster tiles) | 40MB | 80-150MB |
| frontend (nginx) | 10MB | 10MB |
| **Total** | **~280MB** | **~600MB-1GB** |

A $5-10/mo VPS (2GB RAM, 1 vCPU) is viable for a public demo.

---

## 5. Branding & Monetization Precursors

**Overall: ✅ Present — monetization-ready**

### "Powered by GeoLens" Badge

| Location | Present | Details |
|----------|---------|---------|
| App footer | ✅ Yes | `AppLayout.tsx:25-43` — link to GitHub, i18n text |
| Public map viewer | ✅ Yes | `PublicViewerPage.tsx:131-143` — bottom-right badge |
| Community edition | ✅ Always shown | `!isEnterprise` forces display |
| Enterprise edition | ✅ Configurable | Admin → Appearance toggle (`BRANDING_SHOW_BADGE`) |

### Branding Consistency

| Element | Status | Location |
|---------|--------|----------|
| App title | ✅ Consistent | "GeoLens" everywhere |
| Logo | ✅ Component | `GeoLensLogo.tsx` — custom SVG, swappable |
| Favicon | ✅ Present | `frontend/public/favicon.svg` — globe + lens icon |
| Theme system | ✅ Ready | Light/dark modes, injectable for white-label |
| i18n app name | ✅ Ready | `common.json` → `appName: "GeoLens"` |
| OG meta tags | ⚠️ Minimal | Only viewport tag; no og:image, og:description |

### Code Quality

| Check | Status |
|-------|--------|
| Placeholder text (lorem, TODO, FIXME) | ✅ Zero found |
| Error boundaries | ✅ 4 boundaries (App, Route, Map, LazyLoad) |
| Empty states | ✅ Handled (no maps, no results, no collections) |
| Loading states | ✅ Skeleton + spinner components |

### White-Label Readiness

Logo, theme, and app name are all component/config-driven. Future enterprise white-labeling would require:
- `instance_name` and `instance_logo_url` PersistentConfig settings
- Frontend boot-time branding config loading
- Subscription enforcement

---

## 6. Release & Distribution Readiness

**Overall: ⚠️ Needs cleanup — version strings only**

| Item | Status | Details |
|------|--------|---------|
| License file | ✅ Pass | Apache 2.0, full text, copyright "Carto Concepts, LLC" |
| License in metadata | ✅ Pass | Both `pyproject.toml` and `package.json` declare Apache-2.0 |
| Git tags | ✅ Pass | 27 tags, v1.0 through v13.0 |
| Backend version | ❌ Placeholder | `pyproject.toml`: `version = "0.1.0"` (should be `13.0.0`) |
| Frontend version | ❌ Placeholder | `package.json`: `version = "0.0.0"` (should be `13.0.0`) |
| .gitignore | ✅ Complete | .env, __pycache__, node_modules, .DS_Store, IDE files, .planning/ |
| No secrets in repo | ✅ Clean | No private IPs, personal emails, internal domains |
| No large binaries | ✅ Clean | All >5MB in node_modules/.venv/.git (not distributed) |
| CI/CD | ✅ Excellent | `ci.yml` (lint/test/security), `release.yml` (notes), `publish.yml` (Docker + SBOM) |
| Security scanning | ✅ Present | bandit, pip-audit, Trivy in CI |
| SBOM attestation | ✅ Present | anchore/sbom-action in publish workflow |

---

## 7. GTM Checklist Reconciliation

| Checklist Item | Status | Evidence | Action Needed |
|----------------|--------|----------|---------------|
| Public GitHub repo with clean README | ✅ | Comprehensive README with badges, screenshots, quick start | None |
| Apache 2.0 license file | ✅ | `/LICENSE` — full Apache 2.0 text | None |
| Installation quickstart (<10 min) | ✅ | 4-step: clone → env → compose up → working in ~2 min | None |
| v1.0 tag with release notes | ✅ | v13.0 is latest; v1.0 exists; CHANGELOG maintained | None |
| No default credentials committed | ✅ | `.env` gitignored; defaults in `.env.example` marked `[CHANGE IN PRODUCTION]` | None |
| Demo instance viable | ⚠️ | Core workflows work. Missing: auto-seed, reset automation | Build demo compose overlay (~2 weeks) |
| "Powered by GeoLens" in footer | ✅ | App footer + public viewer, always shown in community edition | None |
| GitHub Discussions enabled | ✅ | Discussion templates present (Ideas, Q&A) | None |
| CONTRIBUTING.md | ✅ | 132-line guide with dev setup, commit conventions, PR process | None |
| Sample datasets loadable | ✅ | `seed-natural-earth.py` (130 datasets), `seed-e2e.py` (2 datasets) | None |
| Version strings consistent | ⚠️ | pyproject.toml `0.1.0`, package.json `0.0.0` vs tag `v13.0` | Update to `13.0.0` |

---

## 8. Prioritized Action Items

| Priority | Action | Effort | Rationale |
|----------|--------|--------|-----------|
| **P0** | Update `backend/pyproject.toml` version to `13.0.0` | 5 min | Version mismatch visible in `pip show`, package metadata |
| **P0** | Update `frontend/package.json` version to `13.0.0` | 5 min | Version mismatch visible in build artifacts |
| **P1** | Create `docker-compose.demo.yml` overlay | 2h | Enables one-command demo deployment |
| **P1** | Add auto-seed service to demo compose | 2h | Demo launches with populated catalog instead of empty |
| **P1** | Add OG meta tags to `index.html` (og:title, og:description, og:image) | 30 min | Link previews in Slack/Twitter/LinkedIn when sharing demo URL |
| **P2** | Create `.env.demo` template with demo-safe defaults | 30 min | Reduces demo config friction |
| **P2** | Add automated 24h data reset for demo | 4h | Prevents demo data pollution |
| **P2** | Add installation troubleshooting section to docs | 1h | Addresses common cold-start confusion |
| **P2** | Update Alembic warning log message in entrypoints | 15 min | "Migrations already applied" instead of "migration failed" |
| **P2** | Add upgrade/migration guide for major versions | 2h | Helps users upgrading between releases |

**Total effort to address all items: ~13 hours**
- P0 blockers: 10 minutes
- P1 items: ~4.5 hours
- P2 improvements: ~8 hours

---

## 9. Demo Deployment Recipe

### Recommended Demo Deployment

**Target:** $5-10/mo VPS (2GB RAM, 1 vCPU, 50GB disk) — e.g., Hetzner CX22, DigitalOcean Basic, AWS t3.small

**Steps:**

1. **Provision server** with Docker + Docker Compose installed
2. **Clone and configure:**
   ```bash
   git clone https://github.com/geolens-io/geolens.git && cd geolens
   cp .env.example .env
   # Edit .env:
   #   POSTGRES_PASSWORD=<random-24-char>
   #   JWT_SECRET_KEY=<random-32-hex>
   #   GEOLENS_ADMIN_PASSWORD=<strong-password>
   #   PUBLIC_APP_URL=https://demo.geolens.io
   #   PUBLIC_API_URL=https://demo.geolens.io/api
   #   LOG_JSON=true
   ```
3. **Start services:**
   ```bash
   docker compose up -d
   # Wait ~2 minutes for all services healthy
   docker compose ps  # Verify all green
   ```
4. **Seed sample data:**
   ```bash
   # Generate admin API key via UI or API
   curl -X POST http://localhost:8000/api/api-keys/ \
     -H "Authorization: Bearer <admin-jwt>" \
     -H "Content-Type: application/json" \
     -d '{"name": "seed-script"}'

   # Seed Natural Earth datasets (130 datasets, ~5 min)
   python scripts/seed-natural-earth.py --api-key <key> --theme all
   ```
5. **Configure reverse proxy** (nginx/Caddy) with TLS termination pointing to port 8080
6. **Set all seeded datasets to public visibility** via Admin UI or API

**Required env vars:**
- `POSTGRES_PASSWORD` — strong random value
- `JWT_SECRET_KEY` — `openssl rand -hex 32`
- `GEOLENS_ADMIN_PASSWORD` — min 8 chars
- `PUBLIC_APP_URL` — public-facing URL
- `PUBLIC_API_URL` — public-facing API URL

**Security hardening for public demo:**
- Set `LOG_JSON=true` (disables interactive API docs)
- Create a `viewer` role demo user (can browse but not upload/edit)
- Set `UPLOAD_MAX_SIZE_MB=50` to limit abuse
- Configure `CORS_ALLOWED_ORIGINS` to demo domain only
- Consider rate limiting at reverse proxy level

**Estimated monthly cost:** $5-10 (VPS) + $0 (domain via existing DNS) = **$5-10/mo**

---

## 10. Comparison to Prior Audit

No prior demo-ready audit exists. This is the baseline.
