# Phase 225: API Reference - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-25
**Phase:** 225-api-reference
**Areas discussed:** Snapshot fetch script, URL layout, OGC page granularity, Pagefind exclusion scope

---

## Snapshot Fetch Script

| Option | Description | Selected |
|--------|-------------|----------|
| TS in docs, HTTP fetch (Recommended) | `docs/scripts/fetch-openapi.ts` curls http://localhost:8000/api/openapi.json on the operator's machine. Matches REQUIREMENTS API-01 verbatim. Operator must run `docker compose up api` first. Output: docs/src/content/openapi/geolens.json. Self-contained in docs subtree. | ✓ |
| Python in geolens, no server | `backend/scripts/export_openapi.py` imports the FastAPI app, calls `app.openapi()`, writes JSON. No DB or container needed. Operator manually copies JSON cross-repo OR script writes via relative path `../../getgeolens.com/docs/...`. | |
| Both — Python writes to backend/, TS in docs copies | Python script writes `backend/openapi-snapshot.json` (committed in geolens repo too — single source of truth). TS in docs reads from sibling repo path or downloads from a published artifact. Most rigorous but two scripts to maintain. | |

**User's choice:** TS in docs, HTTP fetch
**Notes:** Recommended path was selected. Aligns with REQUIREMENTS API-01 wording and avoids cross-repo path coupling. Operator workflow requires a running API container (DB connection needed) — that tradeoff is accepted and documented in the README (D-03).

---

## URL Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Flat siblings (Recommended) | Auto-generated tag pages live at `/guides/api/{tag}/` directly. Hand-authored `/guides/api/auth` and `/guides/api/ogc` are siblings. `/guides/api/index.mdx` is a curated landing page. Minimum URL depth, matches the requirement literal. | ✓ |
| Nested reference subdir | Auto-generated pages live under `/guides/api/reference/{tag}/`. Hand-authored auth/OGC at `/guides/api/auth` and `/guides/api/ogc`. Clear separation; deeper URLs but no naming collisions. | |

**User's choice:** Flat siblings
**Notes:** Surfaces a known collision — the FastAPI `Auth` tag would auto-generate to `/guides/api/auth/`, conflicting with the hand-authored auth page. Resolution captured in D-07: prefer plugin slug-override; fall back to renaming the FastAPI tag and re-snapshotting. Researcher to confirm which path the plugin supports.

---

## OGC Page Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Single landing page (Recommended) | One `/guides/api/ogc` page with sections: Common, Records, Features, STAC, Tiles. Each section has the QGIS/GDAL connection example inline. Matches REQUIREMENTS API-04 literal ("landing page summarizing"). | ✓ |
| Split per-standard subpages | Hub at `/guides/api/ogc` linking to `/guides/api/ogc/features`, `/records`, `/stac`, `/tiles`. Better long-term browseability; deeper sidebar; deviates from API-04 literal. | |

**User's choice:** Single landing page
**Notes:** Recommended option. Matches REQUIREMENTS API-04 literal. Per-standard split is captured in deferred ideas if reader feedback warrants later.

---

## Pagefind Exclusion Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Exclude only auto-generated tag pages (Recommended) | Auto-rendered `/guides/api/{tag}/` pages get `pagefind: false`. Hand-authored `/guides/api/`, `/guides/api/auth`, `/guides/api/ogc` STAY indexed. Satisfies SC#4 interpreted as the auto-generated reference subtree; auth + OGC examples remain searchable. | ✓ |
| Exclude all of /guides/api/ | Strictest reading of SC#4. Anyone searching for 'JWT', 'CQL2', 'WFS' won't surface API pages. Discoverability cost is real; cleanest implementation. | |
| Rely on D-28 weight=0.1 alone | Auto-generated pages have a lot of code blocks; weight=0.1 should already push them down. Risk: SC#4 wording is "does not appear" — weight=0.1 makes them appear lower-ranked, not absent. Likely fails verification. | |

**User's choice:** Exclude only auto-generated tag pages
**Notes:** Adds a verification assertion (D-24) — Pagefind index entries for tag slugs must be 0; entries for `/guides/api/auth` must be ≥ 1. Confirms exclusion scope is correct, not over-broad. Mechanism path-of-discovery captured in D-22 with three fallback options for the planner/researcher.

---

## Claude's Discretion

User did not directly delegate any specific gray areas to "you decide." Discretion items captured in CONTEXT.md `<decisions>` Claude's Discretion subsection are implementation details (CSS, runner choice, package selection, callout wording, curl style) that downstream agents should resolve from existing patterns or research without re-prompting the user.

## Deferred Ideas

- Interactive API console (TRY-IT-01) — out of scope for v15.0
- `oasdiff` drift CI (OASDIFF-01) — wait until docs site stabilized
- Versioned API references (VERSION-01) — single "latest" only; URL prefix enables retrofit
- CQL2 deep-dive page — single example in OGC page is enough
- OAuth client-credentials / PKCE machine flow — geolens does not currently support this
- Sequence/PKCE flow diagrams in auth page — possible polish phase
- Marketing-site cross-link to /guides/api/ — Phase 228 marketing /features page
- Per-standard OGC subpages — possible if reader feedback warrants
