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
 * Authenticated users see the full MapBuilderPage (server enforces RBAC).
 * Anonymous users see a read-only PublicMapViewerPage.
 * Each branch is lazy-loaded so anonymous users never download editor code.
 */
export function MapViewerGate() {
  const isAuthenticated = useAuthStore((s) => !!s.token);
  return (
    <AppErrorBoundary>
      <Suspense fallback={<LoadingState />}>
        {isAuthenticated ? <MapBuilderPage /> : <PublicMapViewerPage />}
      </Suspense>
    </AppErrorBoundary>
  );
}
