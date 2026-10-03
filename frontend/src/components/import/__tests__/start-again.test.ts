import { ApiError } from '@/api/client';
import * as serviceSession from '@/api/service-url-session';
const mockGetJobStatus = vi.hoisted(() => vi.fn());
vi.mock('@/api/ingest', () => ({ getJobStatus: mockGetJobStatus }));

import { releaseTerminalImportSession, startAgainPath } from '../start-again';

describe('startAgainPath', () => {
  it('opens the service tab with the URL minus userinfo and redacted credentials', () => {
    const path = startAgainPath(
      'service',
      'https://redacted@maps.example.com/arcgis/rest/services/Roads/FeatureServer?f=json&token=%3Credacted%3E&layer=3',
    );
    const url = new URL(path, 'http://localhost');

    expect(url.pathname).toBe('/import');
    expect(url.searchParams.get('tab')).toBe('service');
    const prefill = new URL(url.searchParams.get('url') ?? '');
    expect(prefill.username).toBe('');
    expect(prefill.searchParams.has('token')).toBe(false);
    expect(prefill.searchParams.get('layer')).toBe('3');
    expect(path).not.toContain('redacted');
  });

  it('opens the file URL tab without a URL when the job kept none', () => {
    expect(startAgainPath('url', null)).toBe('/import?tab=url');
  });

  it('drops a source URL that is not http(s) or does not parse', () => {
    expect(startAgainPath('service', 'javascript:alert(1)')).toBe('/import?tab=service');
    expect(startAgainPath('service', 'not a url')).toBe('/import?tab=service');
  });
});

describe('releaseTerminalImportSession', () => {
  function retainSession(jobId: string | null, status: 'pending' | 'fulfilled' | 'rejected') {
    vi.spyOn(serviceSession, 'peekServiceImport').mockReturnValue({ status, jobId } as never);
    return vi.spyOn(serviceSession, 'clearServiceImport').mockImplementation(() => {});
  }

  afterEach(() => vi.restoreAllMocks());

  it('releases a session whose job the server now reports failed', async () => {
    const clear = retainSession('job-1', 'fulfilled');
    mockGetJobStatus.mockResolvedValue({ status: 'failed' });

    await expect(releaseTerminalImportSession('service')).resolves.toBe(true);
    expect(mockGetJobStatus).toHaveBeenCalledWith('job-1');
    expect(clear).toHaveBeenCalled();
  });

  it('releases a session whose preview was rejected without a lookup', async () => {
    const clear = retainSession(null, 'rejected');

    await expect(releaseTerminalImportSession('service')).resolves.toBe(true);
    expect(mockGetJobStatus).not.toHaveBeenCalled();
    expect(clear).toHaveBeenCalled();
  });

  it('keeps a session whose job is still running', async () => {
    const clear = retainSession('job-1', 'fulfilled');
    mockGetJobStatus.mockResolvedValue({ status: 'running' });

    await expect(releaseTerminalImportSession('service')).resolves.toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });

  it('leaves a newer session alone when the user starts another import mid-lookup', async () => {
    const first = { status: 'fulfilled', jobId: 'job-1' };
    const second = { status: 'fulfilled', jobId: 'job-2' };
    const peek = vi.spyOn(serviceSession, 'peekServiceImport').mockReturnValue(first as never);
    const clear = vi.spyOn(serviceSession, 'clearServiceImport').mockImplementation(() => {});
    let answer: (value: { status: string }) => void = () => {};
    mockGetJobStatus.mockReturnValue(new Promise((resolve) => (answer = resolve)));

    const released = releaseTerminalImportSession('service');
    peek.mockReturnValue(second as never);
    answer({ status: 'failed' });

    await expect(released).resolves.toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });

  it('releases for both of two concurrent lookups of the same ended session', async () => {
    const session = { status: 'fulfilled', jobId: 'job-1' };
    let current: typeof session | null = session;
    vi.spyOn(serviceSession, 'peekServiceImport').mockImplementation(() => current as never);
    vi.spyOn(serviceSession, 'clearServiceImport').mockImplementation(() => {
      current = null;
    });
    mockGetJobStatus.mockResolvedValue({ status: 'failed' });

    const results = await Promise.all([
      releaseTerminalImportSession('service'),
      releaseTerminalImportSession('service'),
    ]);

    expect(results).toEqual([true, true]);
  });

  it.each([404, 410])('releases a session whose job is gone (%i)', async (status) => {
    const clear = retainSession('job-1', 'fulfilled');
    mockGetJobStatus.mockRejectedValue(new ApiError('gone', status));

    await expect(releaseTerminalImportSession('service')).resolves.toBe(true);
    expect(clear).toHaveBeenCalled();
  });

  it('keeps the session on a server error', async () => {
    const clear = retainSession('job-1', 'fulfilled');
    mockGetJobStatus.mockRejectedValue(new ApiError('unavailable', 503));

    await expect(releaseTerminalImportSession('service')).resolves.toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });

  it('keeps the session when the lookup fails', async () => {
    const clear = retainSession('job-1', 'fulfilled');
    mockGetJobStatus.mockRejectedValue(new Error('network'));

    await expect(releaseTerminalImportSession('service')).resolves.toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });
});
