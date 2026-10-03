import { QueryClient } from '@tanstack/react-query';
import * as serviceSession from '@/api/service-url-session';
import { queryKeys } from '@/lib/query-keys';
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
  const failedJob = { status: 'failed' };

  function setup(jobStatus?: { status: string }) {
    const qc = new QueryClient();
    if (jobStatus) qc.setQueryData(queryKeys.ingest.jobStatus('job-1'), jobStatus);
    return qc;
  }

  function startSession(jobId: string | null, status: 'pending' | 'fulfilled' | 'rejected') {
    const promise = new Promise<never>(() => {});
    vi.spyOn(serviceSession, 'peekServiceImport').mockReturnValue({
      status,
      jobId,
      promise,
    } as never);
    return vi.spyOn(serviceSession, 'clearServiceImport').mockImplementation(() => {});
  }

  afterEach(() => vi.restoreAllMocks());

  it('releases a service session whose committed job failed', () => {
    const clear = startSession('job-1', 'fulfilled');

    expect(releaseTerminalImportSession('service', setup(failedJob))).toBe(true);
    expect(clear).toHaveBeenCalled();
  });

  it('releases a service session whose preview was rejected', () => {
    const clear = startSession(null, 'rejected');

    expect(releaseTerminalImportSession('service', setup())).toBe(true);
    expect(clear).toHaveBeenCalled();
  });

  it('keeps a session whose job is still running or awaiting review', () => {
    const clear = startSession('job-1', 'fulfilled');

    expect(releaseTerminalImportSession('service', setup({ status: 'running' }))).toBe(false);
    expect(releaseTerminalImportSession('service', setup())).toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });
});
