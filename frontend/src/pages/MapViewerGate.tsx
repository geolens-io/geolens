import { lazy, Suspense } from 'react';
import { useParams } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { LoadingState } from '@/components/layout/LoadingState';
import { AppErrorBoundary } from '@/components/error';
import { useMapAccess } from '@/hooks/use-maps';

const MapBuilderPage = lazy(() =>
  import('./MapBuilderPage').then((m) => ({ default: m.MapBuilderPage })),
);
const PublicMapViewerPage = lazy(() =>
  import('./PublicMapViewerPage').then((m) => ({ default: m.PublicMapViewerPage })),
);

/**
 * Route-level gate for /maps/:id.
 * Editor/admin users see the full MapBuilderPage (server enforces RBAC).
 * Anonymous and signed-in viewer users see a read-only PublicMapViewerPage.
 * Each branch is lazy-loaded so public viewers never download editor code.
 */
export function MapViewerGate() {
  const { id } = useParams<{ id: string }>();
  const hasToken = useAuthStore((s) => !!s.token);
  const user = useAuthStore((s) => s.user);
  const editorFallback = useAuthStore((s) => s.isEditor());
  const shouldCheckAccess = !!id && hasToken && !!user;
  const accessQuery = useMapAccess(id, { enabled: shouldCheckAccess });

  if (hasToken && !user) {
    return <LoadingState />;
  }

  if (shouldCheckAccess && accessQuery.isLoading) {
    return <LoadingState />;
  }

  const canEdit = shouldCheckAccess
    ? accessQuery.data?.can_edit === true
    : editorFallback;

  return (
    <AppErrorBoundary>
      <Suspense fallback={<LoadingState />}>
        {canEdit ? <MapBuilderPage /> : <PublicMapViewerPage />}
      </Suspense>
    </AppErrorBoundary>
  );
}
