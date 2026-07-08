import { lazy, Suspense } from 'react';
import { useParams, useSearchParams } from 'react-router';
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
 *
 * fix(V-15): editors had no way to preview the read-only viewer UI short of
 * opening an incognito window / share link. `?preview=viewer` lets a user
 * WITH edit rights render PublicMapViewerPage instead — the "View as viewer"
 * item in MapTitleBar's overflow menu sets this param. Only takes effect for
 * users who canEdit; it is a no-op for viewers (who already see
 * PublicMapViewerPage).
 *
 * NOT an anonymous-data preview: API calls still carry the editor's session,
 * so private-dataset layers they can access still load. Audience data
 * visibility is surfaced by the V-17 stack badge / Share warning; a byte-exact
 * anonymous view needs an incognito window.
 */
export function MapViewerGate() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
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
  const previewAsViewer = canEdit && searchParams.get('preview') === 'viewer';

  return (
    <AppErrorBoundary>
      <Suspense fallback={<LoadingState />}>
        {canEdit && !previewAsViewer ? <MapBuilderPage /> : <PublicMapViewerPage />}
      </Suspense>
    </AppErrorBoundary>
  );
}
