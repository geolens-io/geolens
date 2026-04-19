import { lazy, Suspense } from 'react';
import { useAuthStore } from '@/stores/auth-store';
import { LoadingState } from '@/components/layout/LoadingState';
import { AppErrorBoundary } from '@/components/error';

const MapBuilderPage = lazy(() =>
  import('./MapBuilderPage').then((m) => ({ default: m.MapBuilderPage })),
);
const PublicMapViewerPage = lazy(() =>
  import('./PublicMapViewerPage').then((m) => ({ default: m.PublicMapViewerPage })),
);

/**
 * Route-level gate for /maps/:id.
 * Authenticated editors see the full MapBuilderPage.
 * Anonymous users see a read-only PublicMapViewerPage.
 * Each branch is lazy-loaded so anonymous users never download editor code.
 */
export function MapViewerGate() {
  const isEditor = useAuthStore((s) => s.isEditor());
  return (
    <AppErrorBoundary>
      <Suspense fallback={<LoadingState />}>
        {isEditor ? <MapBuilderPage /> : <PublicMapViewerPage />}
      </Suspense>
    </AppErrorBoundary>
  );
}
