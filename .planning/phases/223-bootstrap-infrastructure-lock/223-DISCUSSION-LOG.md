# Phase 223: Bootstrap & Infrastructure Lock - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-25
**Phase:** 223-bootstrap-infrastructure-lock
**Areas discussed:** CI/deploy workflow shape, Custom domain timing & visibility, Skeleton content & brand depth, _redirects stub + legacy URL inventory

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| CI/deploy workflow shape | Workflow file structure, path filtering, project naming, wrangler config | ✓ |
| Custom domain timing & visibility | When to map docs.getgeolens.com; robots/noindex posture during bootstrap | ✓ |
| Skeleton content & brand depth | How much customCss / homepage / sidebar / fonts ship in 223 vs 224 | ✓ |
| _redirects stub + legacy URL inventory | What goes in MIG-02 stub; trailing-slash and wildcard handling | ✓ |

---

## CI/Deploy Workflow Shape

### Q1: Workflow file shape for docs CI/deploy?

| Option | Description | Selected |
|--------|-------------|----------|
| One combined workflow | Mirror marketing's `ci.yml`: single `docs-ci.yml` runs astro check + build + deploy in sequence | ✓ |
| Split check vs deploy | `deploy-docs.yml` only on push to main; separate check job on all PRs | |
| Reuse existing ci.yml with matrix | Add a docs job to existing `ci.yml` using matrix strategy | |

**User's choice:** One combined workflow (Recommended)

### Q2: Path-filter strategy for both workflows?

| Option | Description | Selected |
|--------|-------------|----------|
| Symmetric allowlist + ignore | `docs-ci.yml`: `paths: ['docs/**', '.github/workflows/docs-ci.yml']`. Marketing `ci.yml`: `paths-ignore: ['docs/**']` | ✓ |
| Docs allowlist only, marketing untouched | Add paths filter only to new docs workflow; leave marketing as-is | |
| Aggressive: also ignore root config files | Marketing `ci.yml` also ignores root-level package.json/tsconfig.json changes | |

**User's choice:** Symmetric allowlist on docs, ignore on marketing (Recommended)

### Q3: CF Pages project name for docs?

| Option | Description | Selected |
|--------|-------------|----------|
| `getgeolens-docs` | Matches existing pattern (marketing is `getgeolens-com`) | ✓ |
| `geolens-docs` | Research summary's suggestion | |

**User's choice:** getgeolens-docs (Recommended)

### Q4: wrangler.toml strategy for docs/?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate `docs/wrangler.toml` | Mirror marketing root pattern inside `docs/`; CF Pages picks up via rootDirectory | ✓ |
| Dashboard-only configuration | No `docs/wrangler.toml`; configure entirely via CF dashboard | |

**User's choice:** Separate docs/wrangler.toml (Recommended)

**Notes:** All four recommended defaults accepted — pattern mirrors marketing site's existing CI/deploy structure for consistency and minimum surprise.

---

## Custom Domain Timing & Visibility

### Q1: When does docs.getgeolens.com get mapped?

| Option | Description | Selected |
|--------|-------------|----------|
| Map in Phase 223 | DEPLOY-03 explicitly puts it in 223; TLS provisioning takes time | ✓ |
| Defer to Phase 224 | Stay on `*.pages.dev` until brand work passes visual review | |
| Map in 223 but only as preview alias | Add domain but keep production on `*.pages.dev` (degenerates to option 1) | |

**User's choice:** Map in Phase 223 (Recommended)

### Q2: Robots/indexing posture during bootstrap?

| Option | Description | Selected |
|--------|-------------|----------|
| Block robots.txt + noindex meta | `Disallow: /` + sitewide noindex meta until SEO-03 in Phase 228 | ✓ |
| robots.txt block only | `Disallow: /` only; rely on it solely | |
| Allow from day 1 | robots.txt allows crawl immediately | |

**User's choice:** Block in robots.txt + noindex meta until content (Recommended)

### Q3: How is TLS auto-provisioning verified?

| Option | Description | Selected |
|--------|-------------|----------|
| Manual curl + screenshot | One-time bootstrap event; `curl -I` + screenshot in phase summary | ✓ |
| Automated probe in docs-ci.yml | CI step asserting cert validity post-deploy | |

**User's choice:** Manual curl check + screenshot (Recommended)

**Notes:** noindex posture is intentional belt-and-suspenders — robots.txt blocks well-behaved crawlers, meta tag catches Bingbot edge cases that occasionally index disallowed URLs.

---

## Skeleton Content & Brand Depth

### Q1: How much custom.css ships in Phase 223?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal placeholder accent | `--sl-color-accent` / -low / -high mapped to GeoLens blue (~hue 250) only | ✓ |
| Empty placeholder file | File registered in astro.config but empty body | |
| Full OKLCH 50–950 mapping | Ship BRAND-01 in 223 (overlaps Phase 224 scope) | |

**User's choice:** Minimal placeholder accent (Recommended)

### Q2: Homepage content for skeleton deploy?

| Option | Description | Selected |
|--------|-------------|----------|
| Stub with planned-URL TOC | Short "Documentation in progress" + bullet TOC referencing planned `/guides/*` URLs | ✓ |
| Default Starlight splash component | Use Starlight `<Hero>` with placeholder copy | |
| Single-line under-construction page | Bare "GeoLens docs — launching soon" line | |

**User's choice:** Stub with planned-URL TOC (Recommended)

### Q3: Sidebar groups declared in Phase 223?

| Option | Description | Selected |
|--------|-------------|----------|
| Declare empty `/guides/` groups upfront | astro.config sidebar declares Quickstart, User Guide, Admin Guide, API Reference with `/guides/` paths | ✓ |
| Leave sidebar empty / auto-generate | No sidebar config; Starlight auto-generates from content | |

**User's choice:** Declare empty /guides/ groups upfront (Recommended)

### Q4: Inter font load in Phase 223?

| Option | Description | Selected |
|--------|-------------|----------|
| Defer to Phase 224 | BRAND-02 owns `@fontsource-variable/inter` setup; clean phase boundary | ✓ |
| Pre-load Inter in 223 | Install fontsource pkg now and add to customCss | |

**User's choice:** Defer to Phase 224 (Recommended)

**Notes:** Strategy keeps Phase 224's BRAND-01 / BRAND-02 / SHELL-01 boundaries crisp. The bootstrap deploy will not be Starlight-purple (minimal accent placeholder) but won't preempt full token mapping work either. Sidebar group declaration anchors BOOT-03 (`/guides/` prefix) from day 1 so 224 cannot accidentally regress to flat URLs.

---

## _redirects Stub + Legacy URL Inventory

### Pre-discussion scout finding
Marketing site (`getgeolens.com`) **already owns `/quickstart`** as a real page (`HeroSection.astro:23`, `Nav.astro:79`, `QuickstartTeaser.astro:21`). Docs `_redirects` must not claim `/quickstart`. Backend monorepo has no current external links to flat docs URLs (`backend/docs/` markdown files are accessed via GitHub UI only).

### Q1: What populates _redirects at Phase 223?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal MIG-02 set | `/install`, `/admin`, `/api` → `/guides/*` | ✓ |
| Empty stub with header comment | File exists, no rules; add only on actual rename | |
| Broader pre-population | All four prefixes including `/quickstart` + splats (conflicts with marketing) | |

**User's choice:** Minimal MIG-02 set (Recommended)

### Q2: Trailing-slash and wildcard handling?

| Option | Description | Selected |
|--------|-------------|----------|
| Match `/foo`, `/foo/`, and `/foo/*` splats | Three rules per legacy path; covers every variant | ✓ |
| Exact match only | Just `/foo` → `/guides/foo`; rely on CF auto-handling for slashes | |

**User's choice:** Match /foo, /foo/, and /foo/* splats (Recommended)

### Q3: How does _redirects stay maintained as docs evolve?

| Option | Description | Selected |
|--------|-------------|----------|
| Comment header + docs-team convention | `_redirects` opens with comment block; Phase 227 MIG-03 documents in CONTRIBUTING.md | ✓ |
| CI check that fails on rename without _redirects entry | Custom script comparing prior commit's content tree to current | |

**User's choice:** Comment header in _redirects + docs-team convention (Recommended)

**Notes:** Excluding `/quickstart` from docs `_redirects` was the most consequential finding — it's a marketing route, not a docs path. Captured as anti-pattern in CONTEXT.md `<code_context>`.

---

## Claude's Discretion

- Exact contents of `docs/wrangler.toml` (mirror marketing pattern)
- Exact noindex meta injection mechanism (Starlight `head` config array vs custom `<head>` component)
- `.nvmrc` strategy (reuse repo-root vs add `docs/.nvmrc`)
- Whether to commit a placeholder `docs/src/content/openapi/.gitkeep` for Phase 225 readiness
- Exact stub homepage copy

## Deferred Ideas

- CI rename-detection check for `_redirects` — premature complexity for unproven need
- Cross-site redirect from marketing `/quickstart` → docs once Phase 226 ships — surface during Phase 226 planning
- Automated TLS / cert-renewal monitoring — production reliability concern, not launch concern
- `oasdiff` CI integration — explicitly deferred per REQUIREMENTS.md (OASDIFF-01)
- Versioned docs (`starlight-versions`) — explicitly deferred per REQUIREMENTS.md (VERSION-01)
