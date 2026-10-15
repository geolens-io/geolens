import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@/test/test-utils';
import { ContactsEditor } from '../ContactsEditor';
import { SourceQualityTab, type SourceQualityDraftValues } from '../tabs/SourceQualityTab';
import { buildDatasetEditCapabilities } from '../hooks/use-dataset-edit-capabilities';
import { listContacts } from '@/api/records';

vi.mock('@/api/records', () => ({
  listContacts: vi.fn(),
  createContact: vi.fn(),
  deleteContact: vi.fn(),
}));
vi.mock('@/hooks/use-ai-availability', () => ({
  useAIAvailability: () => ({ isAIAvailable: false }),
}));
vi.mock('@/hooks/use-ai-metadata', () => ({
  useLineageDraft: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useQualityStatementDraft: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useUpdateDataset: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('@/components/dataset/SpatialExtentCard', () => ({ SpatialExtentCard: () => null }));
vi.mock('@/components/dataset/TemporalExtentCard', () => ({ TemporalExtentCard: () => null }));
vi.mock('@/components/dataset/QualityScoreCard', () => ({ QualityScoreCard: () => null }));

const draftValues: SourceQualityDraftValues = {
  lineage_summary: '',
  source_url: '',
  source_organization: '',
  update_frequency: 'monthly',
  usage_constraints: '',
  access_constraints: '',
  sensitivity_classification: 'internal',
  quality_statement: '',
  attribution: '',
};

describe('metadata select accessible names', () => {
  it('names the contact role select after its visible label', async () => {
    vi.mocked(listContacts).mockResolvedValue({ contacts: [] } as never);
    render(<ContactsEditor recordId="rec-1" canEdit />);

    await userEvent.click(await screen.findByRole('button', { name: 'Add Contact' }));

    expect(await screen.findByRole('combobox', { name: 'Role' })).toBeInTheDocument();
  });

  it('names the update frequency and sensitivity selects after their visible labels', async () => {
    render(
      <SourceQualityTab
        dataset={{ id: 'dataset-1' } as never}
        canEdit
        datasetId="dataset-1"
        capabilities={buildDatasetEditCapabilities({ isEditor: true })}
        draftValues={draftValues}
        onDraftSave={vi.fn()}
        onDraftDirtyChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'Update Frequency' })).toBeInTheDocument();
    });
    expect(screen.getByRole('combobox', { name: 'Sensitivity Classification' })).toBeInTheDocument();
  });
});
