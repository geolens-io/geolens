import { render, screen } from '@/test/test-utils';
import * as serviceSession from '@/api/service-url-session';
import { ImportPage } from '../ImportPage';

const mockGetJobStatus = vi.hoisted(() => vi.fn());
vi.mock('@/api/ingest', () => ({ getJobStatus: mockGetJobStatus }));
vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));
vi.mock('@/components/import/UploadForm', () => ({ UploadForm: () => <div>Upload workflow</div> }));
vi.mock('@/components/import/RegisterForm', () => ({ RegisterForm: () => <div /> }));
vi.mock('@/components/import/StacImportForm', () => ({ StacImportForm: () => <div /> }));
vi.mock('@/components/import/WorkflowRail', () => ({ WorkflowRail: () => <aside /> }));
vi.mock('@/components/import/UrlImportForm', () => ({
  UrlImportForm: ({ initialUrl }: { initialUrl?: string }) => (
    <div>File URL workflow [{initialUrl}]</div>
  ),
}));
vi.mock('@/components/import/ServiceUrlForm', () => ({
  ServiceUrlForm: ({ initialUrl }: { initialUrl?: string }) => (
    <div>Service workflow [{initialUrl}]</div>
  ),
}));

describe('ImportPage prefill', () => {
  it('opens the service tab with the URL from the link', async () => {
    render(<ImportPage />, {
      route: '/import?tab=service&url=https%3A%2F%2Fmaps.example.com%2Fwfs',
    });

    expect(await screen.findByText('Service workflow [https://maps.example.com/wfs]')).toBeInTheDocument();
  });

  it('opens the file URL tab without handing the URL to the other form', async () => {
    render(<ImportPage />, { route: '/import?tab=url' });

    expect(await screen.findByText('File URL workflow []')).toBeInTheDocument();
  });

  it('ignores an unknown tab', () => {
    render(<ImportPage />, { route: '/import?tab=stac&url=https%3A%2F%2Fx.test' });

    expect(screen.getByText('Upload workflow')).toBeInTheDocument();
  });

  describe('with a retained service session', () => {
    const route = '/import?tab=service&url=https%3A%2F%2Fmaps.example.com%2Fwfs';
    const retain = (status: 'fulfilled' | 'rejected', jobId: string | null) => {
      vi.spyOn(serviceSession, 'peekServiceImport').mockReturnValue({ status, jobId } as never);
      return vi.spyOn(serviceSession, 'clearServiceImport').mockImplementation(() => {});
    };
    afterEach(() => vi.restoreAllMocks());

    it('releases a job that failed since it was last seen, so the prefilled URL wins', async () => {
      const clear = retain('fulfilled', 'job-1');
      mockGetJobStatus.mockResolvedValue({ status: 'failed' });

      render(<ImportPage />, { route });

      expect(
        await screen.findByText('Service workflow [https://maps.example.com/wfs]'),
      ).toBeInTheDocument();
      expect(clear).toHaveBeenCalled();
    });

    it('keeps an active session and ignores the link URL', async () => {
      const clear = retain('fulfilled', 'job-1');
      mockGetJobStatus.mockResolvedValue({ status: 'running' });

      render(<ImportPage />, { route });

      expect(await screen.findByText('Service workflow []')).toBeInTheDocument();
      expect(clear).not.toHaveBeenCalled();
    });

    it('keeps the session when the status lookup fails', async () => {
      const clear = retain('fulfilled', 'job-1');
      mockGetJobStatus.mockRejectedValue(new Error('network'));

      render(<ImportPage />, { route });

      expect(await screen.findByText('Service workflow []')).toBeInTheDocument();
      expect(clear).not.toHaveBeenCalled();
    });
  });
});
