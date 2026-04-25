# Stack Research

**Domain:** Documentation site — Astro Starlight on existing Astro 6 monorepo
**Researched:** 2026-04-25
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `@astrojs/starlight` | 0.38.4 | Documentation framework | Astro-native, ships Pagefind out of the box, active dev (45+ releases), v0.38.0 added Astro 6 support and dropped Astro 5 — exact match for existing stack |
| `astro` | 6.1.9 (existing) | Build framework | Already used by marketing site; no version change needed |
| `pagefind` | 1.5.2 (bundled via Starlight) | Static full-text search | Zero-config, zero external service, runs at build time, <300kB payload for 10K-page sites, new v1.5.0 adds Web Worker search and CJK segmentation |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `starlight-openapi` | 0.25.0 | Auto-generate API reference from OpenAPI/Swagger spec | Required for API docs section; supports Swagger 2.0, OpenAPI 3.0/3.1, both local and remote schemas; generates static pages (not an embedded widget) |
| `@astrojs/starlight-tailwind` | latest compatible with Starlight 0.38 | Bridge Starlight styles into Tailwind 4 layer system | Required only if docs site shares the marketing site's Tailwind config; provides the `@layer base, starlight, theme, components, utilities` cascade order and dark-mode variant wiring |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Cloudflare Pages (Build System V2) | Deploy docs as separate project from same repo | Create a second Pages project pointing at the `apps/docs/` (or `docs/`) subdirectory; configure Build Watch Paths so only docs changes trigger docs builds; max 5 Pages projects per repo |
| Wrangler / CF Pages dashboard | Configure monorepo build isolation | Set `Root directory` = docs app dir, `Build command` = `npm run build` (from that dir), enable Build Watch Paths to the docs subtree only |

## Installation

```bash
# From the getgeolens-com repo root, inside the docs app dir
npm create astro@latest -- --template starlight

# OR add Starlight manually to an existing Astro project
npx astro add starlight

# API reference plugin
npm install starlight-openapi

# Tailwind bridge (only if sharing Tailwind config with marketing site)
npm install @astrojs/starlight-tailwind
```

## Key Integration Points

### 1. Starlight + Astro 6 compatibility

Starlight `>=0.38.0` requires `astro >=6.0.0`. Earlier Starlight versions (0.36.x and below) require Astro 5. Do not install Starlight 0.37 or earlier — it will not work with the existing Astro 6 marketing site toolchain.

### 2. Shared design tokens

Starlight exposes all colors as CSS custom properties (`--sl-color-accent`, `--sl-color-accent-low`, `--sl-color-accent-high`, etc.) overridable via a `customCss` file. The marketing site's OKLCH tokens can be referenced directly:

```css
/* docs/src/styles/custom.css */
:root {
  /* Map GeoLens brand primary (blue, hue ~250) into Starlight accent slots */
  --sl-color-accent-low:  oklch(0.20 0.04 250);   /* dark tint */
  --sl-color-accent:      oklch(0.55 0.20 250);   /* primary */
  --sl-color-accent-high: oklch(0.90 0.08 250);   /* light tint */
  --sl-font: 'Inter Variable', system-ui, sans-serif;
}
:root[data-theme='dark'] {
  --sl-color-accent-low:  oklch(0.18 0.04 250);
  --sl-color-accent:      oklch(0.65 0.18 250);
  --sl-color-accent-high: oklch(0.28 0.08 250);
}
```

Register this file in `astro.config.mjs` via Starlight's `customCss: ['./src/styles/custom.css']`. No Tailwind dependency is required for token sharing — raw CSS variables are sufficient and preferred because they avoid coupling the docs build to the marketing site's Tailwind config.

The Inter Variable font is already self-hosted via `@fontsource-variable/inter` in the marketing site. Install the same package in the docs app (or reference a shared workspace package if the repo uses workspaces) and add `'@fontsource-variable/inter'` to `customCss`.

### 3. starlight-openapi — remote vs committed snapshot

`starlight-openapi` accepts either a local file path or a remote URL as the `schema` value:

```js
// astro.config.mjs
starlightOpenAPI([{
  base: 'api',
  schema: '../geolens-openapi.json',   // local committed snapshot
  // OR:
  schema: 'https://api.example.com/openapi.json',  // live fetch at build time
  sidebar: { label: 'API Reference' }
}])
```

**Recommended: commit a snapshot.** The FastAPI `/openapi.json` is only accessible when the backend is running. Cloudflare Pages build runners do not have access to the self-hosted backend, so a live fetch at build time requires a publicly reachable staging URL or an additional CI secret — adding operational complexity for zero functional gain. A committed `openapi.json` in the repo is version-controlled, diff-visible in PRs, and requires no network access at build time. Update the snapshot as part of the release process (a `scripts/update-openapi.sh` that hits the local dev server and copies the output into the docs repo).

### 4. Cloudflare Pages monorepo multi-project setup

Create a **second** Cloudflare Pages project (separate from the marketing site project) connected to the same `getgeolens-com` GitHub repository:

- **Root directory**: set to the docs app subdirectory (e.g., `apps/docs` or `docs`)
- **Build command**: `npm run build` (Starlight/Astro static build)
- **Build output directory**: `dist`
- **Custom domain**: `docs.getgeolens.com`
- **Build Watch Paths** (CF Pages V2 feature): include only `apps/docs/**` (or equivalent) so marketing-site-only commits do not trigger a docs rebuild, and vice versa

This is the standard CF Pages monorepo pattern, fully supported as of Build System V2. The two projects deploy independently and are served from different CF Pages subdomains/custom domains with no shared cache or routing.

### 5. Pagefind — no configuration needed

Starlight enables Pagefind by default. The index is built at the end of `astro build`. The `pagefind: false` frontmatter option can exclude auto-generated API reference pages from search if they produce noisy results — worth evaluating after the first build. No additional packages or service accounts required.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `starlight-openapi` (static pages) | Scalar / Stoplight Elements / RapiDoc (embedded widgets) | When you need a "Try it" interactive console in production. Scalar is the best-maintained widget option in 2026 (Stoplight dev slowed post-SmartBear acquisition). Not needed for v15.0 — static reference is sufficient and avoids a CSP/CORS setup |
| `starlight-openapi` (HiDeoo) | `starlight-openapi-rapidoc` (jeffdrumgod) | If you specifically need RapiDoc's interactive UI embedded inside Starlight pages. Lower star count, less active |
| Committed `openapi.json` snapshot | Live fetch from backend at build time | If the GeoLens backend has a permanent public staging URL that is stable during CF Pages builds |
| Raw `customCss` for token sharing | `@astrojs/starlight-tailwind` bridge | Use the Tailwind bridge only if the docs site needs Tailwind utility classes in custom components; for branding tokens alone, raw CSS variables are simpler |
| Astro Starlight | Mintlify, Docusaurus, VitePress | Mintlify is SaaS with per-editor pricing. Docusaurus/VitePress are React/Vue-native — mismatched to existing Astro stack, separate build systems, no Pagefind built in |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Mintlify | SaaS pricing model; docs content leaves your infrastructure; no self-hosted option | Starlight |
| Docusaurus | React-ecosystem, separate webpack/babel toolchain, duplicates build infra already solved by Astro | Starlight |
| VitePress | Vue-native, incompatible with existing React component library | Starlight |
| Algolia DocSearch | External service dependency; Pagefind is already bundled with Starlight at zero cost with no crawl quota | Pagefind (Starlight default) |
| `@astrojs/starlight` < 0.38.0 | Requires Astro 5; breaks on the existing Astro 6 toolchain | `@astrojs/starlight@^0.38.0` |
| `@astrojs/tailwind` integration | Deprecated for Tailwind 4; replaced by `@tailwindcss/vite` plugin | `@tailwindcss/vite` (already in marketing site) |
| Versioned docs machinery (starlight-versions) | Zero return for single-version v15.0 scope; adds per-release overhead | Defer until 2.0 API stability warrants it |

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `@astrojs/starlight@^0.38.4` | `astro@^6.0.0` | v0.38.0 adds Astro 6 support, drops Astro 5. Peer dep: `astro >=6.0.0` |
| `starlight-openapi@^0.25.0` | `@astrojs/starlight >=0.38.0`, `astro >=6.0.0` | Confirmed peer deps; released April 23 2026 — same week as Starlight 0.38.4 |
| `pagefind@^1.5.2` | bundled/called by Starlight build | Starlight invokes Pagefind automatically after `astro build`; no direct dependency management needed |
| `@astrojs/starlight-tailwind` | Tailwind 4 via `@tailwindcss/vite` | Requires specific `@layer` cascade order in global CSS; `@astrojs/tailwind` integration is deprecated |
| Cloudflare Pages Build System V2 | monorepo multi-project | Required for Build Watch Paths feature; V2 is the current default for new projects |

## Sources

- `/withastro/starlight` (Context7) — configuration, customCss, Pagefind integration, Tailwind layer order
- https://github.com/withastro/starlight/releases — confirmed latest version 0.38.4, Astro 6 peer dep
- https://github.com/HiDeoo/starlight-openapi — version 0.25.0, remote schema support, peer deps
- https://starlight-openapi.vercel.app/configuration/ — configuration options confirmed
- https://github.com/Pagefind/pagefind/releases — confirmed v1.5.2, April 12 2026
- https://github.com/withastro/astro/releases — confirmed astro@6.1.9 current
- https://developers.cloudflare.com/pages/configuration/monorepos/ — Build System V2 requirement, 5-project limit, Build Watch Paths
- https://starlight.astro.build/guides/css-and-tailwind/ — Tailwind 4 layer order, @astrojs/starlight-tailwind usage

---
*Stack research for: docs.getgeolens.com — Astro Starlight documentation site*
*Researched: 2026-04-25*
