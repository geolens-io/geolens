# Quick Task 260530-ezw — Low-Priority Follow-ups

Captured for next cycle from quick task `260530-ezw` (download/tile/vector verify + basemap-labels, thumbnail-blob, import-style fixes). The three substantive findings were promoted to GitHub issues; the items below are coverage gaps and nits not worth a same-session fix.

**Promoted to GitHub issues (not in this backlog):**
- #120 — Builder: raster/imagery basemap occludes data when `basemap_position='top'`
- #121 — Public datasets not anonymously exportable (file export 401s for anon)
- #122 — Duplicate `ReactDOMClient.createRoot()` console error on `/maps`

---

## P2 — Defer / polish

| ID | Source | Summary | Target Follow-up | Rationale |
|----|--------|---------|------------------|-----------|
| QZ-LP-01 | thumbnail fix coverage | The blob-URL revoke-on-eviction fix (commit cc321149) was live-MCP verified on the **maps list** (`/maps`) but not on the **search page** quicklooks. Both consume the same hook pattern + `lib/blob-url-cache.ts`, so the fix applies. | Live-MCP smoke the search page (`/`) result-card quicklooks: scroll/re-query, confirm no `ERR_FILE_NOT_FOUND`. | Shared code path; low risk, just unexercised end-to-end. |
| QZ-LP-02 | export gating coverage | Anonymous/unpublished **vector** export gating was confirmed only via the RBAC code path + a private-published proxy — there were **no draft/ready vector datasets** in the local DB to exercise a true unpublished export. | When a draft vector dataset exists (or seed one), verify unpublished vector export returns 401/404 for anon and non-owner. Pairs with #121. | Coverage gap, not a known defect. |
| QZ-LP-03 | route-shape inconsistency | `GET /api/collections/{id}/items/` (trailing slash) → 404, while the no-slash form works. Frontend uses no-slash so it's unaffected. | Add the dual-shape alias (stacked decorator) per the Phase 1092 ROUTE-01 pattern, or document the exception. | Inconsistent with the `redirect_slashes=False` dual-shape effort; harmless today. |
| QZ-LP-04 | code nit (own work) | `registerBlobUrlRevocation(queryClient)` is invoked during hook render in `use-map-thumbnail.ts` / `use-quicklook.ts` (idempotent via a module-level `WeakSet`, so safe and cheap) rather than inside an effect. | If lint conventions object to side-effect-in-render, move the call into a `useEffect`/`useMemo`. | Stylistic; behavior is correct and idempotent. |
