import userEvent from '@testing-library/user-event';
import { render, screen } from '@/test/test-utils';
import { SourceQualityTab, type SourceQualityDraftValues } from '../tabs/SourceQualityTab';
import { buildDatasetEditCapabilities } from '../hooks/use-dataset-edit-capabilities';

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

const emptyDraft: SourceQualityDraftValues = {
  lineage_summary: '',
  source_url: '',
  source_organization: '',
  update_frequency: '',
  usage_constraints: '',
  access_constraints: '',
  sensitivity_classification: '',
  quality_statement: '',
  attribution: '',
};

function renderTab(canEdit: boolean, themeCategory: string[] = []) {
  return render(
    <SourceQualityTab
      dataset={{ id: 'dataset-1', theme_category: themeCategory } as never}
      canEdit={canEdit}
      datasetId="dataset-1"
      capabilities={buildDatasetEditCapabilities({ isEditor: canEdit })}
      draftValues={emptyDraft}
      onDraftSave={vi.fn()}
      onDraftDirtyChange={vi.fn()}
    />,
  );
}

describe('SourceQualityTab always-editable controls', () => {
  it('shows "Not set" in empty selects and no redundant pencil beside them', () => {
    renderTab(true);

    for (const name of ['Update Frequency', 'Sensitivity Classification']) {
      expect(screen.getByRole('combobox', { name })).toHaveTextContent('Not set');
    }
    for (const id of ['editable-field-shell-update-frequency', 'editable-field-shell-sensitivity']) {
      expect(screen.getByTestId(id).querySelector('[data-testid="editable-field-shell-icon"]')).toBeNull();
    }
  });

  it('summarizes theme categories and reveals the checklist only on request', async () => {
    const user = userEvent.setup();
    renderTab(true, ['boundaries']);

    expect(screen.getByTestId('theme-category-summary')).toHaveTextContent('Boundaries');
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);

    const toggle = screen.getByRole('button', { name: 'Edit categories' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1);
    expect(screen.getByRole('checkbox', { name: 'Boundaries' })).toBeChecked();
  });

  it('shows "Not set" and no checklist to a reader when no category is chosen', () => {
    renderTab(false);

    expect(screen.getByTestId('theme-category-summary')).toHaveTextContent('Not set');
    expect(screen.queryByRole('button', { name: 'Edit categories' })).not.toBeInTheDocument();
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });
});
