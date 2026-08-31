/**
 * fix(#1712): switching Import tabs must not unmount a form that is working.
 *
 * The panels used to render as `activeTab === x && <Form />`, so a tab switch
 * mid-import unmounted the running form. The request carried on, because the
 * server does not stop when a client goes away, and the response landed in
 * dead component state: an unreachable job plus its staged bytes.
 *
 * These pin the two halves of the fix that can regress independently. A panel
 * stays mounted once visited (so in-flight work keeps a live component to
 * report into), and a panel nobody has opened is not mounted at all (so the
 * forms that do real work on mount, RegisterForm lists unregistered tables,
 * still only do it when asked).
 */
import { fireEvent, render, screen } from '@/test/test-utils';
import { useEffect, useState } from 'react';
import { ImportPage } from '../ImportPage';

const mounts: Record<string, number> = {};

function useTrackMount(name: string) {
  useEffect(() => {
    mounts[name] = (mounts[name] ?? 0) + 1;
  }, [name]);
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => {
      if (options?.defaultValue) return options.defaultValue;
      const labels: Record<string, string> = {
        'tabs.label': 'Import sources',
        'tabs.upload': 'Upload',
        'tabs.url': 'From URL',
        'tabs.register': 'Register table',
        'tabs.service': 'Service URL',
        'tabs.stac': 'STAC',
      };
      return labels[key] ?? key;
    },
  }),
}));

vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));

// Stands in for a form carrying in-flight work: the typed value is the state
// that an unmount would have destroyed.
vi.mock('@/components/import/UploadForm', () => ({
  UploadForm: () => {
    useTrackMount('upload');
    const [value, setValue] = useState('');
    return (
      <input
        aria-label="Upload workflow"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
}));

vi.mock('@/components/import/UrlImportForm', () => ({
  UrlImportForm: () => {
    useTrackMount('url');
    return <div>URL workflow</div>;
  },
}));

vi.mock('@/components/import/RegisterForm', () => ({
  RegisterForm: () => {
    useTrackMount('register');
    return <div>Register workflow</div>;
  },
}));

vi.mock('@/components/import/ServiceUrlForm', () => ({
  ServiceUrlForm: () => {
    useTrackMount('service');
    return <div>Service workflow</div>;
  },
}));

vi.mock('@/components/import/StacImportForm', () => ({
  StacImportForm: () => {
    useTrackMount('stac');
    return <div>STAC workflow</div>;
  },
}));

vi.mock('@/components/import/WorkflowRail', () => ({
  WorkflowRail: ({ mode }: { mode: string }) => <aside data-mode={mode}>Workflow rail</aside>,
}));

describe('ImportPage panel lifecycle', () => {
  beforeEach(() => {
    for (const key of Object.keys(mounts)) delete mounts[key];
  });

  it('keeps a visited panel mounted, with its state, across a tab switch', () => {
    render(<ImportPage />);

    const upload = screen.getByLabelText('Upload workflow');
    fireEvent.change(upload, { target: { value: 'import in progress' } });
    expect(mounts.upload).toBe(1);

    fireEvent.click(screen.getByRole('button', { name: 'Service URL' }));
    expect(screen.getByText('Service workflow')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    // One mount, not two: the panel was hidden, never torn down. If it had
    // remounted the value would be back to '' and the counter would read 2.
    expect(mounts.upload).toBe(1);
    expect(screen.getByLabelText('Upload workflow')).toHaveValue('import in progress');
  });

  it('does not mount a panel the user has never opened', () => {
    render(<ImportPage />);

    expect(mounts.upload).toBe(1);
    expect(mounts.register).toBeUndefined();
    expect(mounts.stac).toBeUndefined();

    fireEvent.click(screen.getByRole('button', { name: 'Register table' }));

    expect(mounts.register).toBe(1);
    expect(mounts.stac).toBeUndefined();
  });

  it('hides the inactive panel from the accessibility tree', () => {
    render(<ImportPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Service URL' }));

    // Still in the DOM, which is the entire point, but `hidden` keeps it out
    // of the a11y tree and out of the tab order.
    expect(screen.getByLabelText('Upload workflow')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Upload workflow' })).not.toBeInTheDocument();
  });
});
