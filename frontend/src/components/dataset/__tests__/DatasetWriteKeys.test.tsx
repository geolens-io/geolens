import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils';
import { createDatasetApiKey, listDatasetApiKeys } from '@/api/datasets';
import { revokeMyApiKey } from '@/api/auth';
import { DatasetWriteKeys } from '../DatasetWriteKeys';
import type { ApiKeyCreateResponse, MyApiKeyResponse } from '@/types/api';

vi.mock('@/api/datasets', () => ({
  listDatasetApiKeys: vi.fn(),
  createDatasetApiKey: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  revokeMyApiKey: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const mockList = vi.mocked(listDatasetApiKeys);
const mockCreate = vi.mocked(createDatasetApiKey);
const mockRevoke = vi.mocked(revokeMyApiKey);

const DAY_MS = 24 * 60 * 60 * 1000;

function makeKey(overrides: Partial<MyApiKeyResponse> = {}): MyApiKeyResponse {
  return {
    id: 'key-1',
    name: 'Survey webhook',
    fingerprint: 'abcdefgh…wxyz',
    is_active: true,
    expires_at: new Date(Date.now() + 30 * DAY_MS).toISOString(),
    scope: 'dataset_write',
    dataset_id: 'ds-1',
    created_at: '2026-10-01T00:00:00Z',
    last_used_at: null,
    ...overrides,
  };
}

describe('DatasetWriteKeys', () => {
  beforeEach(() => {
    mockList.mockReset();
    mockCreate.mockReset();
    mockRevoke.mockReset();
  });

  it('lists this dataset’s keys and marks an expired one', async () => {
    mockList.mockResolvedValue([
      makeKey(),
      makeKey({
        id: 'key-2',
        name: 'Old import',
        expires_at: new Date(Date.now() - DAY_MS).toISOString(),
      }),
    ]);
    render(<DatasetWriteKeys datasetId="ds-1" />);

    expect(await screen.findByText('Survey webhook')).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledWith('ds-1');
    const old = screen.getByText('Old import').closest('li') as HTMLElement;
    expect(within(old).getByText('Expired')).toBeInTheDocument();
    const current = screen.getByText('Survey webhook').closest('li') as HTMLElement;
    expect(within(current).queryByText('Expired')).not.toBeInTheDocument();
    expect(within(current).getByText(/^Expires /)).toBeInTheDocument();
  });

  it('says so when the dataset has no keys', async () => {
    mockList.mockResolvedValue([]);
    render(<DatasetWriteKeys datasetId="ds-1" />);
    expect(await screen.findByText('No write keys for this dataset.')).toBeInTheDocument();
  });

  it('mints a key with the chosen expiry and shows the secret once', async () => {
    mockList.mockResolvedValue([]);
    const created: ApiKeyCreateResponse = {
      ...makeKey(),
      key: 'raw-secret-value',
      fingerprint: 'raw-secr…alue',
    };
    mockCreate.mockResolvedValue(created);
    render(<DatasetWriteKeys datasetId="ds-1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Create write key' }));
    fireEvent.change(screen.getByLabelText('Key name'), { target: { value: '  Survey webhook ' } });
    const before = Date.now();
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    const [datasetId, body] = mockCreate.mock.calls[0];
    expect(datasetId).toBe('ds-1');
    expect(body.name).toBe('Survey webhook');
    // The default is 90 days, and never past the server's 365-day cap.
    const expiresIn = new Date(body.expires_at).getTime() - before;
    expect(expiresIn).toBeGreaterThan(89 * DAY_MS);
    expect(expiresIn).toBeLessThanOrEqual(90 * DAY_MS);
    expect(await screen.findByText('raw-secret-value')).toBeInTheDocument();
  });

  it('revokes a key after confirmation', async () => {
    mockList.mockResolvedValue([makeKey()]);
    mockRevoke.mockResolvedValue(undefined);
    render(<DatasetWriteKeys datasetId="ds-1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Revoke Survey webhook' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }));
    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith('key-1'));
  });
});
