import { render, screen } from '@/test/test-utils';
import { ServiceUrlForm } from '../ServiceUrlForm';
import { UrlImportForm } from '../UrlImportForm';

vi.mock('@/api/ingest', () => ({
  probeService: vi.fn(),
  previewServiceLayer: vi.fn(),
  commitImport: vi.fn(),
  arcgisSignin: vi.fn(),
  previewFile: vi.fn(),
  getJobStatus: vi.fn(),
  cancelJob: vi.fn(),
}));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useJobStatus: () => ({ data: undefined }),
  useUploadConfig: () => ({ data: undefined }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
  }),
}));

describe('import forms with an initial URL', () => {
  it('fills the service URL field', () => {
    render(<ServiceUrlForm initialUrl="https://maps.example.com/wfs" />);

    expect(screen.getByPlaceholderText('serviceUrl.placeholder')).toHaveValue(
      'https://maps.example.com/wfs',
    );
  });

  it('starts the service URL field empty without one', () => {
    render(<ServiceUrlForm />);

    expect(screen.getByPlaceholderText('serviceUrl.placeholder')).toHaveValue('');
  });

  it('fills the file URL field', () => {
    render(<UrlImportForm initialUrl="https://files.example.com/roads.geojson" />);

    expect(screen.getByDisplayValue('https://files.example.com/roads.geojson')).toBeInTheDocument();
  });
});
