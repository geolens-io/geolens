import { fireEvent, render, screen } from '@/test/test-utils';
import { ImportPage } from '../ImportPage';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => {
      if (options?.defaultValue) return options.defaultValue;
      const labels: Record<string, string> = {
        'tabs.label': 'Import sources',
        'tabs.upload': 'Upload',
        'tabs.register': 'Register table',
        'tabs.service': 'Service URL',
        'tabs.stac': 'STAC',
      };
      return labels[key] ?? key;
    },
  }),
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock('@/components/import/UploadForm', () => ({
  UploadForm: () => <div>Upload workflow</div>,
}));

vi.mock('@/components/import/RegisterForm', () => ({
  RegisterForm: () => <div>Register workflow</div>,
}));

vi.mock('@/components/import/ServiceUrlForm', () => ({
  ServiceUrlForm: () => <div>Service workflow</div>,
}));

vi.mock('@/components/import/StacImportForm', () => ({
  StacImportForm: () => <div>STAC workflow</div>,
}));

vi.mock('@/components/import/WorkflowRail', () => ({
  WorkflowRail: ({ mode }: { mode: string }) => <aside data-mode={mode}>Workflow rail</aside>,
}));

describe('ImportPage layout', () => {
  it('uses the standard page header without disrupting source switching', () => {
    const { container } = render(<ImportPage />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Bring data into the atlas' }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(
      screen.getByText(/Upload files, register tables from your Postgres/),
    ).toBeInTheDocument();
    expect(container.querySelector('.tick-rule')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Import sources' })).toHaveClass(
      'max-w-full',
      'overflow-x-auto',
    );
    expect(screen.getByText('Upload workflow')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Service URL' }));

    expect(screen.getByText('Service workflow')).toBeInTheDocument();
    expect(screen.getByRole('complementary')).toHaveAttribute('data-mode', 'service');
  });
});
