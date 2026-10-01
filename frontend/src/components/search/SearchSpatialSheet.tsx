import { lazy, Suspense } from 'react';
import { useSearchStore } from '@/stores/search-store';

const LazySpatialFilterPanel = lazy(async () => {
  const module = await import('./SpatialFilterPanel');
  return { default: module.SpatialFilterPanel };
});

/** The search-area sheet is portaled and modal, so it is mounted once per page. */
export function SearchSpatialSheet() {
  const spatialPanelOpen = useSearchStore((s) => s.spatialPanelOpen);
  const setSpatialPanelOpen = useSearchStore((s) => s.setSpatialPanelOpen);
  const bbox = useSearchStore((s) => s.bbox);

  return (
    <Suspense fallback={null}>
      {spatialPanelOpen ? (
        <LazySpatialFilterPanel
          open={spatialPanelOpen}
          onClose={() => setSpatialPanelOpen(false)}
          onApply={(bboxValue, predicate, geometry) => {
            const store = useSearchStore.getState();
            store.setFilter('bbox', bboxValue);
            store.setFilter('spatial_predicate', predicate);
            store.setFilter('geometry', geometry ? JSON.stringify(geometry) : '');
            setSpatialPanelOpen(false);
          }}
          initialBbox={bbox}
          initialPredicate={useSearchStore.getState().spatial_predicate}
        />
      ) : null}
    </Suspense>
  );
}
