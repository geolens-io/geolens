import { lazy, Suspense, useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { AppErrorBoundary } from '@/components/error';
import { ApiError } from '@/api/client';
import { MapUnavailableState } from '@/components/map/MapUnavailableState';
import { useMapAccess } from '@/hooks/use-maps';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useTranslation } from 'react-i18next';

const MapBuilderPage = lazy(() =>
  import('./MapBuilderPage').then((m) => ({ default: m.MapBuilderPage })),
);
const PublicMapViewerPage = lazy(() =>
  import('./PublicMapViewerPage').then((m) => ({ default: m.PublicMapViewerPage })),
);

/**
 * The Suspense fallback below, not the gate itself: only this is mounted
 * while a branch's chunk is still loading, so only it can own the title for
 * that window without racing the branch's own effect once it mounts. A
 * chunk that fails to load leaves this as the last title set, since
 * AppErrorBoundary's fallback doesn't touch it.
 */
function MapLoadingFallback({ title }: { title: string }) {
  useDocumentTitle(title);
  return <LoadingState />;
}

/**
 * Route-level gate for /maps/:id.
 * Editor/admin users see the full MapBuilderPage (server enforces RBAC).
 * Anonymous and signed-in viewer users see a read-only PublicMapViewerPage.
 * Each branch is lazy-loaded so public viewers never download editor code.
 *
 * `?preview=viewer` lets a user WITH edit rights render PublicMapViewerPage
 * (MapTitleBar's "View as viewer" item sets it). It is a no-op for viewers,
 * who already see that page.
 *
 * NOT an anonymous-data preview: API calls still carry the editor's session,
 * so private-dataset layers they can access still load. Audience data
 * visibility is surfaced by the stack badge / Share warning; a byte-exact
 * anonymous view needs an incognito window.
 */
export function MapViewerGate() {
  const { t } = useTranslation('common');
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const hasToken = useAuthStore((s) => !!s.token);
  const user = useAuthStore((s) => s.user);
  const editorFallback = useAuthStore((s) => s.isEditor());
  const shouldCheckAccess = !!id && hasToken && !!user;
  const accessQuery = useMapAccess(id, { enabled: shouldCheckAccess });

  // Owns the title only for the gate's own loading/error UI; asserting one
  // here too can stomp a branch's own if both mount in the same commit.
  const isOwnLoadingOrError =
    (hasToken && !user) ||
    (shouldCheckAccess && accessQuery.isLoading) ||
    (shouldCheckAccess && accessQuery.isError);
  useDocumentTitle(isOwnLoadingOrError ? t('pageTitle.map') : null);

  // React.lazy() fires its import() only at first render of <MapBuilderPage/>,
  // so on the likely-editor path the chunk download would serialize BEHIND the
  // /map-access round trip (the shape App.tsx works around for this gate).
  // Start it in parallel when the editor branch is likely; a wrong guess still
  // renders the right branch once accessQuery resolves, minus the head start.
  // Viewers (editorFallback false) never trigger it, so public viewers never
  // download editor code.
  useEffect(() => {
    if (hasToken && editorFallback) {
      void import('./MapBuilderPage');
    }
  }, [hasToken, editorFallback]);

  if (hasToken && !user) {
    return <LoadingState />;
  }

  if (shouldCheckAccess && accessQuery.isLoading) {
    return <LoadingState />;
  }

  // A failed check offers a retry so an editor is never silently downgraded.
  // A 404 is final for a missing or hidden map, and it has to win over the
  // last good access data React Query keeps across a failed refetch.
  const isAccessCheckNotFound =
    accessQuery.error instanceof ApiError && accessQuery.error.status === 404;
  if (shouldCheckAccess && accessQuery.isError && isAccessCheckNotFound) {
    return <MapUnavailableState error={accessQuery.error} mapId={id} />;
  }

  if (shouldCheckAccess && accessQuery.isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState
          message={t('mapViewerGate.accessCheckFailed')}
          onRetry={() => accessQuery.refetch()}
        />
      </div>
    );
  }

  const canEdit = shouldCheckAccess
    ? accessQuery.data?.can_edit === true
    : editorFallback;
  const previewAsViewer = canEdit && searchParams.get('preview') === 'viewer';

  return (
    <AppErrorBoundary>
      <Suspense fallback={<MapLoadingFallback title={t('pageTitle.map')} />}>
        {canEdit && !previewAsViewer ? <MapBuilderPage /> : <PublicMapViewerPage />}
      </Suspense>
    </AppErrorBoundary>
  );
}
