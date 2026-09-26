/**
 * A lazy chunk that fails to load leaves AppErrorBoundary rendering its own
 * fallback, which never touches document.title. This file's own module
 * registry makes the viewer's chunk reject for the one test below, so the
 * gate's fallback title (set while the chunk was still pending) is left as
 * the last one written rather than a stale title from the previous route.
 */
import { render, screen, waitFor } from '@/test/test-utils';
import { Route, Routes } from 'react-router';
import { MapViewerGate } from '../MapViewerGate';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('../PublicMapViewerPage', () => Promise.reject(new Error('chunk load failed')));

it('keeps the fallback title once the viewer chunk fails to load', async () => {
  document.title = 'Some Other Page - GeoLens';
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });

  render(
    <Routes>
      <Route path="/maps/:id" element={<MapViewerGate />} />
    </Routes>,
    { route: '/maps/map-1' },
  );

  await waitFor(() => expect(document.title).toBe('Map - GeoLens'));
  await screen.findByRole('button', { name: 'Reload page' });
  expect(document.title).toBe('Map - GeoLens');
});
