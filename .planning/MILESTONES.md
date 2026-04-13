# Milestones

## v14.0 getgeolens.com Marketing Site (Shipped: 2026-04-13)

**Phases completed:** 14 of 15 phases, 33 plans, 45 tasks
**Timeline:** 2026-04-05 → 2026-04-13 (9 days)
**Files:** 507 changed, +42,515 / -10,508 lines

**Key accomplishments:**

- Astro 6 static site repo with Tailwind 4 OKLCH tokens, Cloudflare Pages deploy, GitHub Actions CI
- Satori + resvg-js OG image pipeline generating branded 1200x630 PNGs at build time
- Three stylized product preview components (search, map builder, dataset detail) in CSS browser frames
- Homepage with hero, trust signals, feature highlights, and quickstart teaser
- SEO infrastructure: unique meta/OG per page, sitemap.xml, JSON-LD structured data
- WCAG 2.1 AA accessibility audit — keyboard nav, semantic HTML, Axe scan pass
- Demo themed collections: 3 themes, 9 maps, multi-stage seeder Docker pipeline
- Backend quality: CommitRequest discriminated union, sample_values sparse-column fix, PersistentConfig TypeAdapter validation
- 3D support: terrain toggle, fill-extrusion layers, PostGIS 3D detection, GeoJSON-Z delivery
- Shared vector staging pipeline: extracted _ingest_vector_into_staging from ingest/reupload

### Known Gaps

- **Phase 216** (Features & Quickstart Pages) deferred — FEAT-01/02/03, QUICK-01/02/03 not started. Candidate for next milestone.

---
