import { render, screen } from '@/test/test-utils';
import { MetadataTab } from '../tabs/MetadataTab';
import { useValidation } from '@/components/dataset/hooks/use-dataset';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useValidation: vi.fn(),
}));

vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (selector: (state: { token: null }) => unknown) => selector({ token: null }),
}));

vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: true }),
}));

vi.mock('@/hooks/use-ai-metadata', () => ({
  useKeywordSuggestions: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/components/dataset/hooks/use-records', () => ({
  useCreateKeyword: () => ({ mutateAsync: vi.fn() }),
  useKeywords: () => ({ data: { keywords: [] } }),
}));

vi.mock('@/components/dataset/ContactsEditor', () => ({
  ContactsEditor: () => <div>Contacts editor</div>,
}));
vi.mock('@/components/dataset/KeywordsEditor', () => ({
  KeywordsEditor: () => <div>Keywords editor</div>,
}));
vi.mock('@/components/dataset/AiAssistButton', () => ({
  AiAssistButton: ({ onClick }: { onClick: () => void }) => (
    <button type="button" onClick={onClick}>AI assist</button>
  ),
  AiKeywordSuggestions: () => null,
}));
vi.mock('@/components/dataset/ValidationStatus', () => ({
  ValidationStatus: () => <div>Validation status</div>,
}));
vi.mock('@/components/dataset/VersionHistory', () => ({ VersionHistory: () => null }));
vi.mock('@/components/dataset/ChangeHistory', () => ({ ChangeHistory: () => null }));
vi.mock('@/components/dataset/tabs/SourceQualityTab', () => ({ SourceQualityTab: () => null }));

describe('MetadataTab card header patterns', () => {
  beforeEach(() => {
    vi.mocked(useValidation).mockReturnValue({ data: null } as unknown as ReturnType<typeof useValidation>);
  });

  it('uses level-two section titles and the shared action slot for AI assistance', () => {
    render(
      <MetadataTab
        dataset={{ id: 'dataset-1', record_id: 'record-1' } as never}
        canEdit
        capabilities={{} as never}
        draftValues={{} as never}
        onDraftSave={vi.fn()}
        onDraftDirtyChange={vi.fn()}
      />,
    );

    for (const name of ['Contacts', 'Keywords', 'Validation Status', 'History']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument();
    }
    expect(
      screen.getByRole('button', { name: 'AI assist' }).closest('[data-slot="card-action"]'),
    ).toBeInTheDocument();
  });

  it('explains validation progress and gives a reader a maintainer action', () => {
    vi.mocked(useValidation).mockReturnValue({
      data: {
        errors: [{ field: 'lineage_summary', message: 'Required', severity: 'error' }],
        warnings: [],
      },
    } as unknown as ReturnType<typeof useValidation>);
    render(
      <MetadataTab
        dataset={{ id: 'dataset-1', record_id: 'record-1' } as never}
        canEdit={false}
        capabilities={{} as never}
        draftValues={{} as never}
        onDraftSave={vi.fn()}
        onDraftDirtyChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Validation checks clear: 92%')).toBeInTheDocument();
    expect(screen.getByText(/12 baseline checks minus reported errors and warnings/)).toBeInTheDocument();
    expect(screen.getByText(/Ask the dataset owner.*Lineage/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Next: fill in/ })).not.toBeInTheDocument();
  });
});
