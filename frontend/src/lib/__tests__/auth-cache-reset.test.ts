import { QueryClient } from '@tanstack/react-query';
import { wireAuthCacheReset } from '../auth-cache-reset';
import { useAuthStore } from '@/stores/auth-store';
import { getReportEntries, pushReportEntry } from '@/lib/report';
import { useDrawingStore } from '@/stores/drawing-store';
import { useSearchStore } from '@/stores/search-store';
import type { UserResponse } from '@/types/api';

// fix(#430 codex r6): identity changes evict the whole query cache; token
// refresh (same user id) does not.
describe('wireAuthCacheReset', () => {
  const initialAuthState = useAuthStore.getState();
  const initialDrawingState = useDrawingStore.getState();
  const initialSearchState = useSearchStore.getState();

  afterEach(() => {
    useAuthStore.setState(initialAuthState, true);
    useDrawingStore.setState(initialDrawingState, true);
    useSearchStore.setState(initialSearchState, true);
  });

  function seed(qc: QueryClient) {
    qc.setQueryData(['search', 'maps', 'matterhorn'], { maps: [{ id: 'm1' }] });
  }

  it('clears cached queries on login and logout, but not on token refresh', () => {
    useAuthStore.setState({ token: null, user: null });
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      // Login (anonymous -> user-1): clear.
      seed(qc);
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeUndefined();

      // Token refresh (same identity): keep.
      seed(qc);
      useAuthStore.setState({ token: 't2' });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeDefined();

      // Different user signs in: clear.
      useAuthStore.setState({ token: 't3', user: { id: 'user-2' } as UserResponse });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeUndefined();

      // Logout: clear.
      seed(qc);
      useAuthStore.setState({ token: null, user: null });
      expect(qc.getQueryData(['search', 'maps', 'matterhorn'])).toBeUndefined();
    } finally {
      unsubscribe();
    }
  });

  it('clears the problem-report capture buffer when identity changes, not on refresh', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      pushReportEntry({ severity: 'error', source: 'console', message: 'user-1 residue' });
      expect(getReportEntries()).toHaveLength(1);

      // Token refresh (same identity): buffer kept.
      useAuthStore.setState({ token: 't2' });
      expect(getReportEntries()).toHaveLength(1);

      // Logout: buffer cleared — an anonymous tab must not inherit the
      // previous user's captured entries (fix(#1663 review P1)).
      useAuthStore.setState({ token: null, user: null });
      expect(getReportEntries()).toHaveLength(0);
    } finally {
      unsubscribe();
    }
  });

  // fix(#1713): drawing-store's target dataset, selected feature (a real
  // row's property bag) and edit-dirty flag are identity-scoped residue of
  // the same kind — an in-place identity change must not leave them for the
  // next signed-in user.
  it('clears the drawing store when identity changes, not on token refresh', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      useDrawingStore
        .getState()
        .setSelectedFeature(
          { gid: 1, tdId: 'td-1', properties: { name: 'user-1 row' } },
          useDrawingStore.getState().sessionEpoch,
        );
      useDrawingStore.getState().setEditDirty(true);
      expect(useDrawingStore.getState().selectedFeature).not.toBeNull();

      // Token refresh (same identity): kept, including the dirty flag —
      // DatasetPage's unsaved-changes prompt must not lose a real edit.
      useAuthStore.setState({ token: 't2' });
      expect(useDrawingStore.getState().selectedFeature).not.toBeNull();
      expect(useDrawingStore.getState().isEditDirty).toBe(true);

      // A second identity signs in WITHOUT a page reload: cleared.
      useAuthStore.setState({ token: 't3', user: { id: 'user-2' } as UserResponse });
      const state = useDrawingStore.getState();
      expect(state.selectedFeature).toBeNull();
      expect(state.targetDatasetId).toBeNull();
      expect(state.isEditDirty).toBe(false);
    } finally {
      unsubscribe();
    }
  });

  it('clears the drawing store on logout', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      expect(useDrawingStore.getState().targetDatasetId).not.toBeNull();

      useAuthStore.setState({ token: null, user: null });
      expect(useDrawingStore.getState().targetDatasetId).toBeNull();
    } finally {
      unsubscribe();
    }
  });

  // fix(#1761 review P1): the race the ownerId-only check missed —
  // handleEditAttributeSubmit reads `selectedFeature` before an update
  // mutation and calls setSelectedFeature again once it resolves. These pin
  // that resolution being refused when it lands AFTER an identity change,
  // through the real choke point (not bumpSessionEpoch() called directly,
  // which is what drawing-store.test.ts's unit tests use).
  it('refuses a write that arrives after logout, for a target adopted before it', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      // Captured BEFORE the logout, the way handleEditAttributeSubmit
      // captures it before its own await.
      const epoch = useDrawingStore.getState().sessionEpoch;

      // Logout: the choke point bumps the session epoch and clears.
      useAuthStore.setState({ token: null, user: null });

      // The late write: captured before the logout, landing after it, with
      // the dataset route still mounted for anonymous viewing.
      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: { name: 'user-1 row' } }, epoch);

      expect(useDrawingStore.getState().selectedFeature).toBeNull();
    } finally {
      unsubscribe();
    }
  });

  it('refuses a write that arrives after a second identity signs in, for a target adopted by the first', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const epoch = useDrawingStore.getState().sessionEpoch;

      // User B signs in without a page reload.
      useAuthStore.setState({ token: 't2', user: { id: 'user-2' } as UserResponse });

      // User A's late write arrives while B is signed in.
      useDrawingStore
        .getState()
        .setSelectedFeature({ gid: 1, tdId: 'td-1', properties: { name: 'user-1 row' } }, epoch);

      expect(useDrawingStore.getState().selectedFeature).toBeNull();
    } finally {
      unsubscribe();
    }
  });

  it('does not bump the drawing session epoch on same-user token rotation', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useDrawingStore.getState().setDrawing('ds-1', 'my_table', 'Polygon');
      const epochBefore = useDrawingStore.getState().sessionEpoch;

      useAuthStore.setState({ token: 't2' });

      expect(useDrawingStore.getState().sessionEpoch).toBe(epochBefore);

      // The target adopted before the rotation is still valid: a write for
      // it succeeds rather than being refused.
      const feature = { gid: 1, tdId: 'td-1', properties: {} };
      useDrawingStore.getState().setSelectedFeature(feature, useDrawingStore.getState().sessionEpoch);
      expect(useDrawingStore.getState().selectedFeature).toEqual(feature);
    } finally {
      unsubscribe();
    }
  });

  // fix(#1713): milder than drawing-store — search intent, not row data —
  // but the same class and the same choke point.
  it('clears identity-scoped search fields when identity changes, not on token refresh', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useSearchStore.setState({
        q: 'parks',
        bbox: '1,2,3,4',
        collection_id: 'c1',
        keywords: ['water'],
        geometry: '{"type":"Point","coordinates":[0,0]}',
      });

      // Token refresh (same identity): kept.
      useAuthStore.setState({ token: 't2' });
      expect(useSearchStore.getState().q).toBe('parks');

      // A second identity signs in WITHOUT a page reload: cleared.
      useAuthStore.setState({ token: 't3', user: { id: 'user-2' } as UserResponse });
      const state = useSearchStore.getState();
      expect(state.q).toBe('');
      expect(state.bbox).toBe('');
      expect(state.collection_id).toBe('');
      expect(state.keywords).toEqual([]);
      expect(state.geometry).toBe('');
    } finally {
      unsubscribe();
    }
  });

  // fix(#1850): the AI chat transcript is sessionStorage keyed on the map,
  // not on identity, and previously outlived logout — a second user signing
  // in in the same tab would render the first user's prompts and query
  // metadata.
  it('clears geolens-chat-* sessionStorage keys when identity changes, not on token refresh', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      sessionStorage.setItem('geolens-chat-map-1', '[{"role":"user","content":"user-1 prompt"}]');
      sessionStorage.setItem('geolens-chat-result', '{"prompt":"user-1 query"}');
      sessionStorage.setItem('unrelated-key', 'kept');

      // Token refresh (same identity): kept.
      useAuthStore.setState({ token: 't2' });
      expect(sessionStorage.getItem('geolens-chat-map-1')).not.toBeNull();

      // A second identity signs in WITHOUT a page reload: cleared.
      useAuthStore.setState({ token: 't3', user: { id: 'user-2' } as UserResponse });
      expect(sessionStorage.getItem('geolens-chat-map-1')).toBeNull();
      expect(sessionStorage.getItem('geolens-chat-result')).toBeNull();
      expect(sessionStorage.getItem('unrelated-key')).toBe('kept');
    } finally {
      unsubscribe();
      sessionStorage.clear();
    }
  });

  it('clears geolens-chat-* sessionStorage keys on logout', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      sessionStorage.setItem('geolens-chat-map-1', '[]');

      useAuthStore.setState({ token: null, user: null });
      expect(sessionStorage.getItem('geolens-chat-map-1')).toBeNull();
    } finally {
      unsubscribe();
      sessionStorage.clear();
    }
  });

  it('clears identity-scoped search fields on logout', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      useSearchStore.setState({ q: 'parks' });
      expect(useSearchStore.getState().q).toBe('parks');

      useAuthStore.setState({ token: null, user: null });
      expect(useSearchStore.getState().q).toBe('');
    } finally {
      unsubscribe();
    }
  });

  // fix(#1761 review P2): SearchBar keys its local input/debounce state on
  // this counter (see SearchBar.identity.test.tsx) precisely because `q`
  // can stay '' across the identity change and not signal anything on its
  // own — this pins that the counter itself always moves, even then.
  it('bumps the search-store reset epoch on logout, even when q was already empty', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      const before = useSearchStore.getState().resetEpoch;

      useAuthStore.setState({ token: null, user: null });

      expect(useSearchStore.getState().resetEpoch).toBe(before + 1);
    } finally {
      unsubscribe();
    }
  });

  it('does not bump the search-store reset epoch on token refresh', () => {
    const qc = new QueryClient();
    const unsubscribe = wireAuthCacheReset(qc);
    try {
      useAuthStore.setState({ token: 't1', user: { id: 'user-1' } as UserResponse });
      const before = useSearchStore.getState().resetEpoch;

      useAuthStore.setState({ token: 't2' });

      expect(useSearchStore.getState().resetEpoch).toBe(before);
    } finally {
      unsubscribe();
    }
  });
});
