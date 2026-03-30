import { useAuthStore } from '@/stores/auth-store';
import { MapBuilderPage } from './MapBuilderPage';
import { PublicMapViewerPage } from './PublicMapViewerPage';

/**
 * Route-level gate for /maps/:id.
 * Authenticated editors see the full MapBuilderPage.
 * Anonymous users see a read-only PublicMapViewerPage.
 */
export function MapViewerGate() {
  const isEditor = useAuthStore((s) => s.isEditor());
  return isEditor ? <MapBuilderPage /> : <PublicMapViewerPage />;
}
