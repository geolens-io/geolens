import { renderHook, waitFor } from '@/test/test-utils';
import { vi } from 'vitest';

vi.mock('@/api/ingest', () => ({
  uploadFile: vi.fn(),
  registerTable: vi.fn(),
  getJobStatus: vi.fn(),
  previewFile: vi.fn(),
  commitImport: vi.fn(),
  retryJob: vi.fn(),
  probeService: vi.fn(),
  previewServiceLayer: vi.fn(),
  discoverTables: vi.fn(),
  bulkRegisterTables: vi.fn(),
  getUploadConfig: vi.fn(),
  createVrt: vi.fn(),
}));

import { uploadFile, getJobStatus, discoverTables, getUploadConfig } from '@/api/ingest';
import { useUploadFile, useJobStatus, useDiscoverTables, useUploadConfig } from '@/hooks/use-ingest';

const mockUploadFile = vi.mocked(uploadFile);
const mockGetJobStatus = vi.mocked(getJobStatus);
const mockDiscoverTables = vi.mocked(discoverTables);
const mockGetUploadConfig = vi.mocked(getUploadConfig);

describe('useUploadFile', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls uploadFile on mutate', async () => {
    const response = { job_id: 'j-1', filename: 'test.geojson' };
    mockUploadFile.mockResolvedValueOnce(response as never);

    const { result } = renderHook(() => useUploadFile());

    const file = new File(['{}'], 'test.geojson', { type: 'application/json' });
    await result.current.mutateAsync(file);

    expect(mockUploadFile).toHaveBeenCalledWith(file, expect.anything());
  });

  it('returns error state on upload failure', async () => {
    mockUploadFile.mockRejectedValueOnce(new Error('Too large'));

    const { result } = renderHook(() => useUploadFile());

    const file = new File(['{}'], 'test.geojson');
    await expect(result.current.mutateAsync(file)).rejects.toThrow('Too large');
  });
});

describe('useJobStatus', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches job status when jobId is provided', async () => {
    const status = { job_id: 'j-1', status: 'complete', filename: 'test.geojson' };
    mockGetJobStatus.mockResolvedValueOnce(status as never);

    const { result } = renderHook(() => useJobStatus('j-1'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(status);
  });

  it('does not fetch when jobId is null', () => {
    const { result } = renderHook(() => useJobStatus(null));

    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetJobStatus).not.toHaveBeenCalled();
  });

  it('returns error state on failure', async () => {
    mockGetJobStatus.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useJobStatus('bad-id'));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useDiscoverTables', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches discovered tables', async () => {
    const data = { tables: [{ schema: 'public', table: 'my_table' }] };
    mockDiscoverTables.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useDiscoverTables());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });

  it('returns error state on failure', async () => {
    mockDiscoverTables.mockRejectedValueOnce(new Error('DB error'));

    const { result } = renderHook(() => useDiscoverTables());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useUploadConfig', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches upload config', async () => {
    const data = { max_file_size: 500_000_000, storage_backend: 'local' };
    mockGetUploadConfig.mockResolvedValueOnce(data as never);

    const { result } = renderHook(() => useUploadConfig());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(data);
  });
});
