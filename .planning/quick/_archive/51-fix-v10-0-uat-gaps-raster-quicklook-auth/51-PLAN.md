---
phase: quick-51
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/dataset/tabs/AccessSharingTab.tsx
  - backend/app/datasets/router.py
autonomous: true
requirements: [UAT-GAP-6, UAT-GAP-11, UAT-GAP-8]

must_haves:
  truths:
    - "Raster tiles render on the map in the builder after the tile token is fetched"
    - "Raster dataset detail page does not show the vector Export section"
    - "Quicklook thumbnail appears on dataset catalog cards for published raster datasets"
  artifacts:
    - path: "frontend/src/components/builder/BuilderMap.tsx"
      provides: "Fixed syncLayersToMap raster branch — only enters raster path when token is confirmed kind=raster"
    - path: "frontend/src/components/dataset/tabs/AccessSharingTab.tsx"
      provides: "Export card hidden when dataset.record_type === 'raster_dataset'"
    - path: "backend/app/datasets/router.py"
      provides: "Quicklook endpoint uses get_optional_user, allows anonymous access for published+public datasets"
  key_links:
    - from: "BuilderMap.tsx syncLayersToMap"
      to: "map.addSource / map.addLayer"
      via: "token?.kind === 'raster' guard (outer only)"
      pattern: "token\\?\\."
    - from: "AccessSharingTab.tsx"
      to: "ExportButton render"
      via: "record_type check"
      pattern: "record_type.*raster"
    - from: "backend/app/datasets/router.py get_quicklook"
      to: "check_dataset_access"
      via: "get_optional_user dependency"
      pattern: "get_optional_user"
---

<objective>
Fix three v10.0 UAT gaps: raster tiles not rendering in map builder, export section incorrectly shown on raster dataset pages, and quicklook thumbnails failing in the catalog due to missing auth on browser img requests.

Purpose: These are the only 3 remaining failures blocking v10.0 UAT sign-off.
Output: Three targeted file edits — no new files, no new dependencies.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/milestones/v10.0-phases/v10-UAT.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix BuilderMap raster branch nested condition bug</name>
  <files>frontend/src/components/builder/BuilderMap.tsx</files>
  <action>
    In `syncLayersToMap` (lines 120-156), the outer `if` checks
    `token?.kind === 'raster' || layer.layer_type === 'raster_geolens'` which
    can pass via the `layer_type` fallback even when `token` is not yet in
    `tokenMap`. The inner `if (token?.kind === 'raster')` then fails, no source
    is added, but `desiredSources.add(sourceId)` and `continue` still execute —
    the layer is silently skipped every sync cycle.

    Fix: Collapse the outer condition to only enter the raster branch when the
    token is confirmed raster. Change lines 120-156:

    ```ts
    // --- Raster layer branch ---
    if (token?.kind === 'raster') {
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, {
          type: 'raster',
          tiles: [`${window.location.origin}${token.tile_url}`],
          tileSize: token.tile_size ?? 256,
          minzoom: token.minzoom ?? 0,
          maxzoom: token.maxzoom ?? 18,
        });
        map.addLayer({
          id: layerId,
          type: 'raster',
          source: sourceId,
          paint: { 'raster-opacity': layer.opacity ?? 1 },
        });
        if (!layer.visible) {
          map.setLayoutProperty(layerId, 'visibility', 'none');
        }
      } else {
        // Sync opacity and visibility
        if (map.getLayer(layerId)) {
          const currentOpacity = map.getPaintProperty(layerId, 'raster-opacity');
          if (currentOpacity !== (layer.opacity ?? 1)) {
            map.setPaintProperty(layerId, 'raster-opacity', layer.opacity ?? 1);
          }
          const vis = layer.visible ? 'visible' : 'none';
          if (map.getLayoutProperty(layerId, 'visibility') !== vis) {
            map.setLayoutProperty(layerId, 'visibility', vis);
          }
        }
      }
      desiredSources.add(sourceId);
      continue; // skip vector logic for this layer
    }
    ```

    The `layer.layer_type === 'raster_geolens'` fallback is removed from the outer
    condition. When the token is not yet fetched, the layer naturally falls through
    to the vector branch which will also fail to build a tile URL (no token) and
    not add a source — that is acceptable because `syncLayersToMap` is called
    repeatedly via the `useEffect` triggered by `tokenMap` changes, so once the
    token arrives the next sync cycle will add the source correctly.

    NOTE: After this edit, verify the `desiredSources` and cleanup logic below
    line 156 is still correct — `desiredSources` should only include `sourceId`
    when the source is actually added or expected to be present.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -20</automated>
  </verify>
  <done>
    TypeScript compiles without errors. In the map builder, adding a raster
    dataset as a layer results in raster tile network requests to /raster-tiles/
    and the imagery renders on the map.
  </done>
</task>

<task type="auto">
  <name>Task 2: Hide Export section for raster datasets in AccessSharingTab</name>
  <files>frontend/src/components/dataset/tabs/AccessSharingTab.tsx</files>
  <action>
    The Export Card (lines 43-51) renders unconditionally. Add a guard so it
    only renders for vector datasets.

    Add `isRaster` derived from `dataset.record_type`:

    ```tsx
    export function AccessSharingTab({ dataset, datasetId }: AccessSharingTabProps) {
      const { t } = useTranslation('dataset');
      const isRaster = dataset.record_type === 'raster_dataset';

      return (
        <>
          {/* Distributions */}
          <Card>
            ...
          </Card>

          {/* Export — vector datasets only */}
          {!isRaster && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('page.export')}</CardTitle>
              </CardHeader>
              <CardContent>
                <ExportButton datasetId={datasetId} datasetName={dataset.title} />
              </CardContent>
            </Card>
          )}

          {/* Visibility */}
          <Card>
            ...
          </Card>
        </>
      );
    }
    ```

    The `record_type` field is available on `DatasetResponse` (added in Phase
    168). No prop changes needed — `dataset` is already `DatasetResponse`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -20</automated>
  </verify>
  <done>
    TypeScript compiles without errors. Navigating to a raster dataset detail
    page and clicking the Access & Sharing tab shows Distributions and Visibility
    cards but no Export card. Vector dataset detail pages still show the Export
    card.
  </done>
</task>

<task type="auto">
  <name>Task 3: Fix quicklook endpoint to allow anonymous access for public published datasets</name>
  <files>backend/app/datasets/router.py</files>
  <action>
    The quicklook endpoint uses `get_current_active_user` which requires a valid
    JWT. Browser `<img src>` tags do not send Authorization headers, so the
    request always returns 401/403 for any user, even though they are logged in
    via the SPA.

    Change the quicklook endpoint to use `get_optional_user` (already imported
    in the router as it's used elsewhere for anonymous catalog access). Then
    apply an inline visibility check that permits anonymous access when the
    dataset is published and public:

    Replace the `get_quicklook` dependency and access check:

    ```python
    @router.get("/{dataset_id}/quicklook")
    async def get_quicklook(
        dataset_id: uuid.UUID,
        size: int = Query(256, description="Quicklook size: 256 or 512"),
        user: User | None = Depends(get_optional_user),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """Serve a quicklook PNG image for a raster dataset."""
        from app.raster.models import RasterAsset

        dataset = await get_dataset(db, dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        record = dataset.record
        if user is None:
            # Anonymous access: only published + public datasets
            if record.record_status != "published" or record.visibility != "public":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        else:
            await check_dataset_access(db, dataset, dataset_id, user)

        if getattr(record, "record_type", None) != "raster_dataset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quicklook is only available for raster datasets",
            )
        ... (rest of the endpoint unchanged)
    ```

    Verify that `get_optional_user` is already imported — check the imports at
    the top of `router.py`. If not imported, add it to the import from
    `app.auth.dependencies`.

    Note: The `Cache-Control: public, max-age=3600` header on the response is
    already correct for browser caching of public quicklooks.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -c "from app.datasets.router import router; print('import ok')"</automated>
  </verify>
  <done>
    Backend imports without errors. Accessing `/api/datasets/{raster_id}/quicklook?size=256`
    without Authorization header returns a PNG image (200) for a public published
    raster dataset. Quicklook thumbnails appear in the catalog card for raster
    datasets without requiring auth headers from the browser img element.
  </done>
</task>

</tasks>

<verification>
After all three tasks:
1. `cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit` — zero errors
2. `cd /Users/ishiland/Code/geolens/backend && python -c "from app.datasets.router import router"` — no import errors
3. In map builder: add a raster dataset, confirm /raster-tiles/ requests appear in DevTools Network tab
4. On raster dataset detail Access & Sharing tab: no Export card visible
5. In catalog: raster dataset cards show thumbnail images
</verification>

<success_criteria>
- BuilderMap.tsx raster branch enters only when `token?.kind === 'raster'` (no fallback to layer_type alone)
- AccessSharingTab.tsx wraps Export card in `{!isRaster && (...)}`
- Quicklook endpoint uses `get_optional_user`, allows anonymous for public+published, delegates to `check_dataset_access` for authenticated users
- All three UAT gaps (tests 6, 11, 8) resolved
</success_criteria>

<output>
After completion, create `.planning/quick/51-fix-v10-0-uat-gaps-raster-quicklook-auth/51-SUMMARY.md`
</output>
