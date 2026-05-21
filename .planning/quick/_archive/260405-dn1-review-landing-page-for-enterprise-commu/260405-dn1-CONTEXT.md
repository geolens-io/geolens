# Quick Task 260405-dn1: Review landing page for enterprise/community value — consider extracting to getgeolens.com - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Task Boundary

Review the current GeoLens landing page, determine if it's appropriate for enterprise and community deployments, and remove marketing content that belongs on the getgeolens.com marketing site instead.

</domain>

<decisions>
## Implementation Decisions

### What replaces the landing page
- **Straight to search**: Non-authenticated users hitting `/` see the catalog search page directly. No hero, no marketing copy — the catalog IS the product. Login available in navbar.
- Remove the `LandingPage.tsx` component and its route entirely
- The index route `/` should render the search page (same as `/search`)

### Enterprise vs community behavior
- **Remove the `show_landing_page` branding toggle entirely**: `/` always shows search for all deployment types
- No distinction between enterprise/community/cloud — all deployments get the same experience
- Admins customize via instance name and logo branding settings instead
- Delete the `SHOW_LANDING_PAGE` persistent config setting and related backend/frontend code

### Product preview asset fate
- **Move to getgeolens.com only**: Delete product preview mockup components from the app codebase
- The getgeolens.com marketing site (separate Astro repo) is the correct home for product screenshots and mockups
- Phase 214 assets should be migrated to the marketing site repo (out of scope for this task — just delete from app)

</decisions>

<specifics>
## Specific Ideas

- The search page already handles empty state gracefully — no special "welcome" needed
- i18n keys in `search.json` under `landing.*` namespace should be cleaned up
- Branding settings admin UI should remove the `show_landing_page` toggle

</specifics>

<canonical_refs>
## Canonical References

- `frontend/src/pages/LandingPage.tsx` — current landing page component (to be removed)
- `frontend/src/App.tsx:54` — index route pointing to LandingPage
- `backend/app/persistent_config.py` — `SHOW_LANDING_PAGE` setting
- `backend/app/settings/router.py` — branding endpoint serving the toggle
- `frontend/src/i18n/locales/en/search.json` — landing page copy

</canonical_refs>
