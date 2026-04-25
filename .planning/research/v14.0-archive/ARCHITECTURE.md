# Architecture Research

**Domain:** Static marketing site alongside an existing product monorepo
**Researched:** 2026-04-03
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Public Internet                              │
├──────────────────────────┬──────────────────────────────────────┤
│   getgeolens.com          │   app.geolens-domain (product)       │
│   (marketing site)        │   (GeoLens app — existing)           │
│                           │                                      │
│  ┌────────────────────┐   │   ┌────────────────────────────────┐ │
│  │  Cloudflare Pages  │   │   │  Docker Compose / VPS          │ │
│  │  (static CDN)      │   │   │  nginx → Vite frontend         │ │
│  │                    │   │   │  nginx → FastAPI backend        │ │
│  │  Astro build       │   │   └────────────────────────────────┘ │
│  │  HTML/CSS/JS       │   │                                      │
│  └────────────────────┘   │                                      │
└──────────────────────────┴──────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Repo Relationship                              │
│                                                                  │
│  geolens/          (existing — FastAPI + React product)          │
│  getgeolens.com/   (new — Astro marketing site, separate repo)   │
│                                                                  │
│  No shared packages. Brand tokens copied once at project init    │
│  and maintained in sync by convention, not automation.           │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Astro pages | Static HTML generation, routing | `.astro` files in `src/pages/` |
| Layout components | Shell, nav, footer, dark/light mode | Astro components with CSS variables |
| Content sections | Hero, features, pricing/editions, CTA | Astro components, hardcoded copy |
| Design token layer | Brand colors, typography, spacing | CSS custom properties in `global.css` |
| OG image generator | Per-page social cards at build time | Satori + sharp Astro API route |
| Product preview assets | Stylized screenshots for hero/features | Static PNG/WebP in `public/assets/` |
| Contact/CTA form | Enterprise inquiry capture | Cloudflare Forms or Formspree (no backend) |
| CI/CD pipeline | Build, preview deploys, production push | GitHub Actions → Cloudflare Pages |

## Recommended Project Structure

```
getgeolens.com/
├── public/
│   ├── assets/
│   │   ├── screenshots/        # Product preview PNGs (hand-crafted or automated)
│   │   └── icons/              # Favicons, brand SVGs
│   ├── fonts/                  # Self-hosted Inter (woff2) — copied from product
│   └── robots.txt
├── src/
│   ├── components/
│   │   ├── layout/
│   │   │   ├── SiteLayout.astro    # Shell: nav + footer + dark mode
│   │   │   └── Nav.astro
│   │   ├── sections/
│   │   │   ├── Hero.astro
│   │   │   ├── FeatureGrid.astro
│   │   │   ├── EditionsTable.astro
│   │   │   ├── QuickstartSteps.astro
│   │   │   └── EnterpriseCTA.astro
│   │   └── ui/
│   │       ├── Button.astro
│   │       └── Badge.astro
│   ├── pages/
│   │   ├── index.astro         # Homepage
│   │   ├── features.astro      # Feature breakdown
│   │   ├── editions.astro      # Community vs Enterprise matrix
│   │   ├── quickstart.astro    # Docker Compose walkthrough
│   │   ├── enterprise.astro    # Enterprise contact / demo request
│   │   └── og/
│   │       └── [slug].png.ts   # Build-time OG image generation (Satori)
│   ├── styles/
│   │   └── global.css          # Design tokens + Tailwind @import
│   ├── content/                # Astro content collections (optional, see below)
│   │   └── changelog/          # If changelog is added later
│   └── lib/
│       ├── og.ts               # Satori OG image helper
│       └── links.ts            # External URLs (mirrors product external-links.ts)
├── astro.config.mjs
├── package.json
└── tsconfig.json
```

### Structure Rationale

- **`src/components/sections/`:** One file per page section. Keeps pages thin and sections independently testable. Matches the product's component-per-concern convention.
- **`src/pages/og/`:** OG images as Astro API routes using Satori. Generated at `astro build` time into `dist/og/*.png`. Zero server dependency after deploy.
- **`src/styles/global.css`:** Single CSS entry point. Design tokens live here as CSS custom properties, identical to the product's `index.css` token block. Tailwind `@import "tailwindcss"` follows. This is the only cross-repo shared artifact.
- **`public/fonts/`:** Self-hosting Inter avoids a Google Fonts dependency and matches what `@fontsource-variable/inter` provides in the product. Copy the woff2 files once.
- **`src/lib/links.ts`:** Mirrors `frontend/src/lib/external-links.ts`. Kept in sync manually — there are only ~5 constants and they change rarely.

## Architectural Patterns

### Pattern 1: Design Token Copy-Once Strategy

**What:** Extract the CSS custom property block (`:root` and `.dark` tokens) from the product's `index.css` verbatim into the marketing site's `global.css`. Do not automate sync.

**When to use:** When two repos share brand identity but have different tech stacks and different release cadences. Full automation (npm package, git submodule) adds overhead that is not justified for a handful of CSS variables that change a few times per year.

**Trade-offs:** Tokens can drift if one side updates without remembering to mirror. The mitigation is to keep the token block small (it already is: primary OKLCH values, radius, surface hierarchy) and document the sync obligation in the marketing repo's README. Acceptable for a team of one or two.

**Example:**

```css
/* src/styles/global.css — copied from product frontend/src/index.css */
@import "@fontsource-variable/inter/wght.css";  /* or self-host in public/fonts/ */
@import "tailwindcss";

:root {
  --radius: 0.625rem;
  --primary: oklch(0.55 0.18 250);
  --primary-foreground: oklch(0.985 0 0);
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  /* ... full token block from product index.css ... */
}
.dark {
  --primary: oklch(0.72 0.17 250);
  --background: oklch(0.145 0.008 250);
  /* ... */
}
```

### Pattern 2: Hardcoded Copy with Astro Components

**What:** All marketing page content (headlines, feature descriptions, quickstart steps, edition comparison table) lives as hardcoded strings directly in `.astro` component files. No CMS, no MDX for page content.

**When to use:** When the author and developer are the same person and iteration speed matters more than editor-friendly tooling. The marketing site has ~5 pages of stable copy that will rarely change. Adding a CMS (Keystatic, Storyblok) or even MDX adds indirection with no current benefit.

**Trade-offs:** Changing copy requires a git commit and redeploy. Acceptable — Cloudflare Pages deploys in under 60 seconds, and copy edits are infrequent. If a non-technical editor is added later, content collections with Markdown files are a low-friction migration from hardcoded Astro components.

**Exception:** The Quickstart page is a good candidate for a Markdown file (`src/content/quickstart/index.md`) so the docker compose command block stays in a plain text file rather than JSX.

### Pattern 3: Build-Time OG Image Generation (Satori)

**What:** Use Satori + sharp inside an Astro API route (`src/pages/og/[slug].png.ts`) to generate PNG social card images at `astro build` time. Each page references its OG image as a static URL.

**When to use:** Always, for a marketing site. Social sharing previews significantly impact click-through from GitHub, LinkedIn, and Twitter posts. Hand-crafting OG images per page is not maintainable.

**Trade-offs:** Satori requires a font file to be available at build time (load Inter woff2 from the public folder). Adds ~5s to the build. Zero runtime cost — images are static files on Cloudflare CDN.

**Example:**

```typescript
// src/pages/og/[slug].png.ts
import { getCollection } from 'astro:content';
import satori from 'satori';
import sharp from 'sharp';

export async function GET({ params }) {
  const svg = await satori(
    { type: 'div', props: { children: params.slug, style: { ... } } },
    { width: 1200, height: 630, fonts: [{ name: 'Inter', data: interFontBuffer }]
    }
  );
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return new Response(png, { headers: { 'Content-Type': 'image/png' } });
}
```

### Pattern 4: Separate Repo, No Shared Package Infrastructure

**What:** The marketing site lives in `github.com/geolens-io/getgeolens.com` — an entirely independent repo from `github.com/geolens-io/geolens`. No npm workspace, no Turborepo, no git submodule.

**When to use:** When the two products are built with different frameworks (React 19 + Vite vs. Astro), have different deployment targets, and different teams (or same team, different contexts). The coordination cost of a monorepo outweighs the benefit of shared packages when the only shared artifact is a CSS file.

**Trade-offs:** Token drift is the main risk. Managed by documentation and infrequency of brand changes.

## Data Flow

### Request Flow

```
User visits getgeolens.com
    |
Cloudflare CDN (edge cache)
    |
Pre-built static HTML (from Astro build)
    |
Page loads — zero API calls for content
    |
Interactive elements:
  Dark mode toggle  → localStorage read/write (FOUC-safe inline script)
  Enterprise form   → Cloudflare Web Analytics + Formspree POST (no backend)
  GitHub CTA        → External link to github.com/geolens-io/geolens
```

### State Management

```
Dark mode:
  localStorage "geolens-theme" key (matches product storage key)
  Inline script in <head> reads and applies .dark class before paint (no FOUC)
  Toggle button updates class + localStorage

No other client-side state needed.
```

### Key Data Flows

1. **OG image delivery:** `astro build` → Satori renders PNG for each slug → `dist/og/*.png` → Cloudflare Pages CDN. `<meta property="og:image">` points to absolute CDN URL.
2. **Enterprise form submission:** User fills form → Formspree endpoint POST → Formspree sends email to team → No GeoLens backend involved. Fallback is a mailto: link.
3. **Product preview screenshots:** Static WebP assets in `public/assets/screenshots/`. Created manually from actual product screenshots, processed with ImageMagick or Figma for consistent framing. No automation required at MVP.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-10k monthly visitors | Cloudflare Pages free tier handles this with no configuration changes |
| 10k-500k monthly visitors | Still Cloudflare Pages free tier (unlimited bandwidth for static). No changes. |
| 500k+ monthly visitors | Cloudflare Pages Pro for advanced analytics and branch deploy controls. Still static, no infra change. |

### Scaling Priorities

1. **First bottleneck:** Not traffic — it's content updates. If a marketing manager joins and needs to edit copy without git access, migrate to Astro content collections + Keystatic (git-backed CMS, free, self-contained). This is a 2-3 hour migration, not a rewrite.
2. **Second bottleneck:** If A/B testing or personalization is required, Cloudflare Workers can intercept edge requests and serve variants without changing the static build. Deferred until there is evidence of need.

## Anti-Patterns

### Anti-Pattern 1: Adding a CMS Before the First Launch

**What people do:** Set up Contentful, Storyblok, or Sanity to manage the 5 pages of marketing copy before any page exists.

**Why it's wrong:** Adds a paid external dependency, an API call per page render, and a content modeling phase — all before validating whether the site converts. The copy will change 10 times in the first two weeks as messaging is refined. Editing in a CMS while the page structure is still in flux is slower than editing the component directly.

**Do this instead:** Hardcode all copy. Move to content collections (local Markdown files) only when someone other than the developer needs to edit content.

### Anti-Pattern 2: Sharing Code via npm Package or Git Submodule

**What people do:** Create `@geolens/design-tokens` npm package containing the CSS variables, then install it in both the product and the marketing site.

**Why it's wrong:** For a handful of CSS custom properties that change once or twice a year, the overhead (package publish workflow, version pinning, changelog, possible private registry) is disproportionate to the problem. Git submodules are worse — they add merge friction and confuse CI.

**Do this instead:** Copy the token block. Put a comment at the top: `/* Design tokens — keep in sync with frontend/src/index.css in the geolens repo */`. The risk of drift is real but the blast radius is low (visual inconsistency, not a runtime error).

### Anti-Pattern 3: Using the React Frontend for the Marketing Site

**What people do:** Extend the existing Vite/React app with a `/marketing` route or extract it into a standalone React SPA served from the same container.

**Why it's wrong:** React SPAs require JavaScript to render content visible to search engines. Marketing sites live or die by organic search. Astro generates plain HTML — every page is immediately crawlable without a JS-capable renderer. Cloudflare Pages is free for static, while the product app requires a VPS with Docker. Coupling the marketing site to the product's deployment pipeline means a backend outage takes down the marketing site.

**Do this instead:** Separate Astro repo. Independent deployment. The marketing site should survive even if the product's Docker host is down.

### Anti-Pattern 4: Building Interactive Product Demos with React Islands

**What people do:** Embed live interactive map or search demos in the marketing site using React islands.

**Why it's wrong:** At MVP, this is significant scope — you must either proxy to a live product instance (creates a production dependency from the marketing site) or build a fake/mock version (doubles the surface area). The existing `ProductPreview` component in the main app's `LandingPage.tsx` demonstrates that a CSS-only mock with hardcoded dataset names provides 90% of the value.

**Do this instead:** Use static stylized screenshots in the hero. Add a short video walkthrough (Loom embed or self-hosted MP4) for the Features page. Live demo can be a future milestone once the marketing site proves conversion.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Cloudflare Pages | Git push → auto build → CDN deploy | Connect `getgeolens.com` repo in Cloudflare dashboard. Build command: `npm run build`. Output: `dist/`. |
| Cloudflare Analytics (free) | One `<script>` tag in layout | Privacy-first, no cookie consent required. Replace with Plausible if preferred. |
| Formspree | Form `action` attribute POST | No backend needed. Free tier: 50 submissions/month. Captures enterprise inquiry emails. |
| GitHub (github.com/geolens-io/geolens) | External link only | Star count can be fetched at build time via GitHub API (no token needed for public repos) and embedded as a static number. |
| Satori + sharp | Build-time npm dependencies | Used only during `astro build`. Not a runtime dependency. |

### Internal Boundaries (Marketing Site ↔ Product)

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Design tokens | Copy-once CSS block | `:root` and `.dark` variable definitions. Manual sync obligation. |
| Inter font | Copy woff2 files or use `@fontsource-variable/inter` npm package | npm package preferred — avoids manual font file management. |
| External URLs | Duplicate `links.ts` constants | ~5 constants. Mirror manually. Both files rarely change. |
| Product screenshots | Static PNG/WebP in `public/assets/` | Generated from the running product manually, processed for consistent framing. No automation. |
| Brand identity | Convention, not tooling | Same color values, same radius, same font. Enforced by copying tokens, not by a shared library. |
| Deployment | Completely independent | Marketing site on Cloudflare Pages. Product on Docker VPS. No shared CI, no shared infrastructure. |

## Deployment Pipeline

```
Push to main branch
    |
GitHub Actions (optional: run astro check + lint)
    |
Cloudflare Pages build hook
    |
  npm ci
  npm run build     (astro build)
  └── generates dist/ with pre-rendered HTML + OG PNGs
    |
Cloudflare CDN deployment (< 60s typical)
    |
getgeolens.com live at edge

Pull request → preview deploy at pr-123.getgeolens-com.pages.dev
```

## Sources

- [Astro deploy to Cloudflare Pages — official docs](https://docs.astro.build/en/guides/deploy/cloudflare/)
- [Cloudflare Pages Astro guide](https://developers.cloudflare.com/pages/framework-guides/deploy-an-astro-site/)
- [Tailwind CSS v4 with Astro](https://tailwindcss.com/docs/installation/framework-guides/astro)
- [Astro Tailwind v4 quick guide](https://tailkits.com/blog/astro-tailwind-setup/)
- [Satori OG image generation with Astro](https://mahadk.com/posts/astro-og-with-satori)
- [Dynamic OG images with Satori and Astro](https://knaap.dev/posts/dynamic-og-images-with-any-static-site-generator/)
- [Next.js vs Astro for marketing sites — 2025](https://makersden.io/blog/nextjs-vs-astro-in-2025-which-framework-best-for-your-marketing-website)
- [Scaling Astro with monorepos — Astro Weekly #92](https://newsletter.astroweekly.dev/p/astro-weekly-92)
- [Monorepo vs Polyrepo — 2025](https://dev.to/md-afsar-mahmud/monorepo-vs-polyrepo-which-one-should-you-choose-in-2025-g77)
- [Best Astro hosting 2026](https://instapods.com/blog/astro-hosting/)

---
*Architecture research for: getgeolens.com marketing site*
*Researched: 2026-04-03*
