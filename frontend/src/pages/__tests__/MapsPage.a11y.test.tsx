/**
 * GLUX-002 (Phase 1248): accessible-name regression gate for the MapsPage
 * search input.
 *
 * Asserts that the search input is queryable by its accessible name rather
 * than by its placeholder. If anyone removes the FieldLabel + id binding, this
 * test fails — placeholder alone does not produce an accessible name.
 */
import { render, screen } from '@/test/test-utils';
import { vi } from 'vitest';
import { MapsPage } from '@/pages/MapsPage';
import { useMaps, useDeleteMap } from '@/hooks/use-maps';
import { useAuthStore } from '@/stores/auth-store';
import { act } from 'react';

vi.mock('@/hooks/use-maps', () => ({
  useMaps: vi.fn(),
  useDeleteMap: vi.fn(),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

const initialAuthState = useAuthStore.getState();

describe('GLUX-002: MapsPage search input accessible name', () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState(initialAuthState, true);
    });

    vi.mocked(useMaps).mockReturnValue({
      data: { maps: [], total: 0 },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMaps>);

    vi.mocked(useDeleteMap).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteMap>);
  });

  it('search input is queryable by its accessible name (not only by placeholder)', () => {
    render(<MapsPage />);
    // The search input exposes an accessible name via FieldLabel (sr-only label
    // bound via htmlFor). getByLabelText resolves through the label association.
    // Removing the FieldLabel + id from MapsPage will make this test fail.
    const searchInput = screen.getByLabelText(/search maps/i);
    expect(searchInput).toBeInTheDocument();
    expect(searchInput.tagName.toLowerCase()).toBe('input');
  });
});
