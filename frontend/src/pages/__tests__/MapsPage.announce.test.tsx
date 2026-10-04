import { useEffect, useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { MapsPage } from '@/pages/MapsPage';
import { useMaps, useDeleteMap } from '@/hooks/use-maps';

vi.mock('@/hooks/use-maps', () => ({
  useMaps: vi.fn(),
  useDeleteMap: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

const EMPTY = { maps: [], total: 0 };
const MATCH = {
  maps: [{ id: 'm1', name: 'Alps', visibility: 'private', layer_count: 0, updated_at: '2026-01-01T00:00:00Z' }],
  total: 1,
};
let responses: Record<string, unknown> = {};

// Mirrors keepPreviousData: the old page stays as data while the new key loads.
function useFakeMaps(params: { search?: string }) {
  const key = params.search ?? '';
  const [state, setState] = useState({ key, data: EMPTY as unknown, loadedKey: key });
  useEffect(() => {
    if (state.loadedKey === key) return;
    const id = setTimeout(() => setState({ key, data: responses[key], loadedKey: key }), 400);
    return () => clearTimeout(id);
  }, [key, state.loadedKey]);
  return {
    data: state.data,
    isLoading: false,
    isFetching: state.loadedKey !== key,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useMaps>;
}

const statusTexts = () => screen.queryAllByRole('status').map((n) => n.textContent ?? '');
const matchAnnounced = () => statusTexts().some((text) => text.includes('No maps match'));

function search(value: string) {
  fireEvent.change(screen.getByLabelText(/search maps/i), { target: { value } });
}

describe('MapsPage empty-state announcement', () => {
  beforeEach(() => {
    vi.mocked(useMaps).mockImplementation(useFakeMaps as unknown as typeof useMaps);
    vi.mocked(useDeleteMap).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteMap>);
  });

  it('does not announce the stale empty page while a second search is pending, then announces if it is empty', async () => {
    responses = { a: EMPTY, b: EMPTY };
    render(<MapsPage />);
    search('a');
    await waitFor(() => expect(matchAnnounced()).toBe(true), { timeout: 3000 });

    search('b');
    await waitFor(() => expect(screen.getByText('No matching maps')).toBeInTheDocument());
    // Debounce (300 ms) has fired and the request is in flight.
    await new Promise((resolve) => setTimeout(resolve, 380));
    expect(matchAnnounced()).toBe(false);
    await waitFor(() => expect(matchAnnounced()).toBe(true), { timeout: 3000 });
  });

  it('never announces the empty message when the second search has matches', async () => {
    responses = { a: EMPTY, b: MATCH };
    render(<MapsPage />);
    search('a');
    await waitFor(() => expect(matchAnnounced()).toBe(true), { timeout: 3000 });

    search('b');
    await new Promise((resolve) => setTimeout(resolve, 380));
    expect(matchAnnounced()).toBe(false);
    await waitFor(() => expect(screen.getByText('Alps')).toBeInTheDocument(), { timeout: 3000 });
    expect(matchAnnounced()).toBe(false);
  });

  it('titles an unfiltered empty list "No maps yet" and a filtered one "No matching maps"', async () => {
    responses = { a: EMPTY };
    render(<MapsPage />);
    expect(screen.getByText('No maps yet')).toBeInTheDocument();
    search('a');
    await waitFor(() => expect(screen.getByText('No matching maps')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.queryByText('No maps yet')).not.toBeInTheDocument();
  });
});
