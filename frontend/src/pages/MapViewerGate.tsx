import { lazy, Suspense, useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { AppErrorBoundary } from '@/components/error';
import { ApiError } from '@/api/client';
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
 * fix(#430 V-15): editors had no way to preview the read-only viewer UI short of
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
  const { t } = useTranslation('common');
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const hasToken = useAuthStore((s) => !!s.token);
  const user = useAuthStore((s) => s.user);
  const editorFallback = useAuthStore((s) => s.isEditor());
  const shouldCheckAccess = !!id && hasToken && !!user;
  const accessQuery = useMapAccess(id, { enabled: shouldCheckAccess });

  // Own the title only for the gate's own loading/error UI below. A branch
  // sets its own once it renders; asserting one here too can stomp it if
  // both happen to mount in the same commit.
  const isOwnLoadingOrError =
    (hasToken && !user) ||
    (shouldCheckAccess && accessQuery.isLoading) ||
    (shouldCheckAccess && accessQuery.isError);
  useDocumentTitle(isOwnLoadingOrError ? t('pageTitle.map') : null);

  // fix(#1778): React.lazy() only fires its import() at first render of
  // <MapBuilderPage/>, so the chunk download used to serialize BEHIND the
  // /map-access round trip on this route's likely-editor path — the same
  // "vendor download serializes behind the page chunk" shape App.tsx already
  // works around for MapViewerGate itself (#448). Kick the download off in
  // parallel with the access check when the optimistic branch (editor) is
  // likely; a wrong guess (e.g. a downgraded editor) still renders the
  // correct branch once accessQuery resolves, just without the head start.
  // Viewers (editorFallback false) never trigger this, preserving the "public
  // viewers never download editor code" property in the file's doc comment.
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

  // A failed check offers a retry rather than guessing, so an editor is never
  // silently downgraded to the viewer. A 404 is how the API denies a map it
  // won't show, so it goes to the viewer, whose own request shows not-found.
  const isAccessCheckNotFound =
    accessQuery.error instanceof ApiError && accessQuery.error.status === 404;
  if (shouldCheckAccess && accessQuery.isError && !isAccessCheckNotFound) {
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
