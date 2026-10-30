import { apiFetch } from '@/api/client';
import { getDatasetRows, reuploadCommit, reuploadDataset, setTargetStatus } from '@/api/datasets';
import type {
  ReuploadCommitResponse,
  ReuploadResponse,
  StatusUpdateResponse,
} from '@/types/api';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
  authenticatedRawFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(apiFetch);

// The app talks only to the target-status endpoint.
describe('dataset publication-status API contract', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the generated status response contract', () => {
    expectTypeOf(setTargetStatus)
      .returns.resolves.toEqualTypeOf<StatusUpdateResponse>();
  });

  it('setTargetStatus sends the expected PATCH request', async () => {
    const response = {
      id: 'dataset-1',
      record_status: 'ready',
    } satisfies StatusUpdateResponse;
    mockApiFetch.mockResolvedValueOnce(response);

    await expect(setTargetStatus('dataset-1', 'ready')).resolves.toEqual(response);

    expect(mockApiFetch).toHaveBeenCalledWith('/datasets/dataset-1/target-status/', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'ready' }),
    });
  });
});

// The reuploadDataset FormData body can hold up to
// upload_max_size_mb (500 MB) — it must not fall back to apiFetch's 30s
// default timeout, or a large transfer aborts client-side before it finishes.
describe('reuploadDataset timeout', () => {
  beforeEach(() => vi.clearAllMocks());

  it('passes an extended timeoutMs, not the apiFetch default', async () => {
    const response = {
      job_id: 'job-1',
      status: 'pending',
      message: 'Upload received',
    } satisfies ReuploadResponse;
    mockApiFetch.mockResolvedValueOnce(response);

    const file = new File(['data'], 'dataset.gpkg');
    await reuploadDataset('dataset-1', file);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    const [, options] = mockApiFetch.mock.calls[0];
    expect(options?.timeoutMs).toBeGreaterThan(30_000);
  });
});

// The commit body's expected-origin condition. `expected_origin_kind`
// is optional server-side, and an ABSENT key means no origin check — so the
// caller must omit it rather than send null when it has no captured origin.
describe('reuploadCommit expected-origin condition', () => {
  beforeEach(() => vi.clearAllMocks());

  it('sends the captured origin kind when one is given', async () => {
    mockApiFetch.mockResolvedValueOnce({
      job_id: 'job-1',
      status: 'pending',
      message: 'Re-upload queued',
    } satisfies ReuploadCommitResponse);

    await reuploadCommit('dataset-1', 'job-1', null, undefined, undefined, 'service');

    const [, options] = mockApiFetch.mock.calls[0];
    expect(JSON.parse(String(options?.body))).toMatchObject({
      expected_origin_kind: 'service',
    });
  });

  it.each([[undefined], [null]])(
    'omits the key entirely when the origin is %s',
    async (origin) => {
      mockApiFetch.mockResolvedValueOnce({
        job_id: 'job-1',
        status: 'pending',
        message: 'Re-upload queued',
      } satisfies ReuploadCommitResponse);

      await reuploadCommit('dataset-1', 'job-1', null, undefined, undefined, origin);

      const [, options] = mockApiFetch.mock.calls[0];
      expect(JSON.parse(String(options?.body))).not.toHaveProperty(
        'expected_origin_kind',
      );
    },
  );
});

describe('reuploadCommit review fingerprint', () => {
  beforeEach(() => vi.clearAllMocks());

  it('carries the preview fingerprint in the commit body', async () => {
    mockApiFetch.mockResolvedValueOnce({
      job_id: 'job-1',
      status: 'pending',
      message: 'Re-upload queued',
    } satisfies ReuploadCommitResponse);

    await reuploadCommit('dataset-1', 'job-1', null, undefined, undefined, null, 'c'.repeat(64));

    const [, options] = mockApiFetch.mock.calls[0];
    expect(JSON.parse(String(options?.body))).toMatchObject({
      review_fingerprint: 'c'.repeat(64),
    });
  });

  it('omits the key when there is nothing to acknowledge', async () => {
    mockApiFetch.mockResolvedValueOnce({
      job_id: 'job-1',
      status: 'pending',
      message: 'Re-upload queued',
    } satisfies ReuploadCommitResponse);

    await reuploadCommit('dataset-1', 'job-1', null, undefined, undefined, null, null);

    const [, options] = mockApiFetch.mock.calls[0];
    expect(JSON.parse(String(options?.body))).not.toHaveProperty('review_fingerprint');
  });
});

describe('dataset rows request', () => {
  beforeEach(() => vi.clearAllMocks());

  it('sends gid beside the other filters, and nothing when it is unset', async () => {
    mockApiFetch.mockResolvedValue({});

    await getDatasetRows('ds', { limit: 50, gid: 382, filters: { name: 'x' } });
    const url = new URL(String(mockApiFetch.mock.calls[0][0]), 'http://x');
    expect(url.searchParams.get('gid')).toBe('382');
    expect(url.searchParams.get('filter[name]')).toBe('x');

    await getDatasetRows('ds', { limit: 50 });
    expect(String(mockApiFetch.mock.calls[1][0])).not.toContain('gid');
  });
});
