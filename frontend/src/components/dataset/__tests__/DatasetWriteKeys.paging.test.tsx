import { render, screen, within } from '@/test/test-utils';
import { apiFetch } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import { DatasetWriteKeys } from '../DatasetWriteKeys';
import type { DatasetApiKeyResponse, UserResponse } from '@/types/api';

// The real list fetch runs, so the card sees exactly what paging returns.
vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
  authenticatedRawFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(apiFetch);

function key(id: string, name: string, user = 'me'): DatasetApiKeyResponse {
  return {
    id,
    name,
    fingerprint: null,
    is_active: true,
    expires_at: null,
    scope: 'dataset_write',
    dataset_id: 'ds-1',
    created_at: '2026-10-01T00:00:00Z',
    last_used_at: null,
    user_id: user,
    username: user === 'me' ? 'owner' : 'admin',
  };
}

describe('DatasetWriteKeys paging', () => {
  beforeEach(() => {
    mockApiFetch.mockReset();
    useAuthStore.setState({ user: { id: 'me' } as UserResponse });
  });

  it('lists and offers to revoke the 201st key, made by someone else', async () => {
    const firstPage = Array.from({ length: 200 }, (_, i) => key(`key-${i}`, `Recent ${i}`));
    mockApiFetch
      .mockResolvedValueOnce({ items: firstPage, total: 201 })
      .mockResolvedValueOnce({ items: [key('key-old', 'Old admin key', 'admin-id')], total: 201 });

    render(<DatasetWriteKeys datasetId="ds-1" />);

    const row = (await screen.findByText('Old admin key')).closest('li') as HTMLElement;
    expect(within(row).getByText(/Created by admin/)).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Revoke Old admin key' })).toBeInTheDocument();
  });
});
