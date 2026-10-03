import { render, screen } from '@/test/test-utils';
import { ImportPage } from '../ImportPage';

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
  it('opens the service tab with the URL from the link', () => {
    render(<ImportPage />, {
      route: '/import?tab=service&url=https%3A%2F%2Fmaps.example.com%2Fwfs',
    });

    expect(screen.getByText('Service workflow [https://maps.example.com/wfs]')).toBeInTheDocument();
  });

  it('opens the file URL tab without handing the URL to the other form', () => {
    render(<ImportPage />, { route: '/import?tab=url' });

    expect(screen.getByText('File URL workflow []')).toBeInTheDocument();
  });

  it('ignores an unknown tab', () => {
    render(<ImportPage />, { route: '/import?tab=stac&url=https%3A%2F%2Fx.test' });

    expect(screen.getByText('Upload workflow')).toBeInTheDocument();
  });
});
