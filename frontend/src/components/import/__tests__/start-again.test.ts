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

  it('keeps the session when the lookup fails', async () => {
    const clear = retainSession('job-1', 'fulfilled');
    mockGetJobStatus.mockRejectedValue(new Error('network'));

    await expect(releaseTerminalImportSession('service')).resolves.toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });
});
