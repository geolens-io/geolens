import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEdit } from '@/components/dataset/InlineEdit';
import { PendingEditsBar } from '@/components/dataset/PendingEditsBar';
import { useDraftEditing } from '@/components/dataset/hooks/use-draft-editing';
import type { DatasetResponse } from '@/types/api';

const mutateAsync = vi.fn();
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useUpdateDataset: () => ({ mutateAsync }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), message: vi.fn() },
}));

function DraftEditor() {
  const drafts = useDraftEditing({
    datasetId: 'dataset-a',
    dataset: { summary: 'original' } as DatasetResponse,
    isGeometryEditDirty: false,
  });
  return <>
    <InlineEdit
      value={drafts.resolveDraftValue('summary')}
      onSave={(value) => drafts.stagePendingDraft('summary', value)}
      onDirtyChange={(dirty) => drafts.handleDraftDirtyChange('summary', dirty)}
      multiline
      saveOnBlur
      allowClear
    />
    <PendingEditsBar
      pendingCount={drafts.pendingCount}
      onSaveAll={async () => { await drafts.savePendingDrafts(); }}
      onCancelAll={drafts.discardPendingDrafts}
      isSaving={drafts.isSaving}
    />
  </>;
}

describe('multiline draft handoff', () => {
  beforeEach(() => mutateAsync.mockReset().mockResolvedValue({}));

  it.each([false, true])('page Save stages active input, with editor button focus: %s', async (tabToButton) => {
    const user = userEvent.setup();
    render(<DraftEditor />);
    await user.click(screen.getByRole('button', { name: 'original' }));
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus());
    await user.clear(screen.getByRole('textbox'));
    await user.type(screen.getByRole('textbox'), 'new summary');
    if (tabToButton) await user.tab();
    await user.click(screen.getByTestId('pending-edits-save'));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith({
      datasetId: 'dataset-a', data: { summary: 'new summary' },
    }));
    await waitFor(() => expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument());
  });

  it('page Discard removes the active multiline draft', async () => {
    const user = userEvent.setup();
    render(<DraftEditor />);
    await user.click(screen.getByRole('button', { name: 'original' }));
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus());
    await user.type(screen.getByRole('textbox'), ' changed');
    await user.click(screen.getByTestId('pending-edits-cancel'));
    await waitFor(() => expect(screen.queryByTestId('pending-edits-bar')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'original' })).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
