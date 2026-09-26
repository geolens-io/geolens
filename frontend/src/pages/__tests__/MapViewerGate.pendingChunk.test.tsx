/**
 * MapViewerGate.test.tsx's PublicMapViewerPage mock resolves (on the next
 * microtask), so it can't show what the tab title looks like while a real
 * chunk is still downloading. This file's own module registry keeps that
 * lazy import pending for the one test below.
 */
import { render, waitFor } from '@/test/test-utils';
import { Route, Routes } from 'react-router';
import { MapViewerGate } from '../MapViewerGate';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('../PublicMapViewerPage', () => new Promise(() => {}));

it("shows the gate's fallback title while the viewer chunk is still loading", async () => {
  document.title = 'Some Other Page - GeoLens';
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });

  render(
    <Routes>
      <Route path="/maps/:id" element={<MapViewerGate />} />
    </Routes>,
    { route: '/maps/map-1' },
  );

  await waitFor(() => expect(document.title).toBe('Map - GeoLens'));
});
