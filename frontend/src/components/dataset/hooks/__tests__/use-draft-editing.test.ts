import { renderHook, act, waitFor } from '@testing-library/react';
import { useDraftEditing } from '@/components/dataset/hooks/use-draft-editing';
import type { DatasetResponse } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockMutateAsync = vi.fn().mockResolvedValue({});
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useUpdateDataset: () => ({ mutateAsync: mockMutateAsync }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn(), info: vi.fn() },
}));

function makeDataset(overrides: Partial<DatasetResponse> = {}): DatasetResponse {
  return {
    id: 'ds-1',
    title: 'Test Dataset',
    summary: 'existing summary',
    lineage_summary: null,
    source_url: null,
    source_organization: null,
    update_frequency: null,
    usage_constraints: null,
    access_constraints: null,
    sensitivity_classification: null,
    quality_statement: null,
    ...overrides,
  } as DatasetResponse;
}

describe('useDraftEditing', () => {
  beforeEach(() => {
    mockMutateAsync.mockClear();
  });

  it('starts with zero pending count', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset(),
        isGeometryEditDirty: false,
      }),
    );
    expect(result.current.pendingCount).toBe(0);
    expect(result.current.isSaving).toBe(false);
  });

  it('resolveDraftValue returns dataset value when no draft staged', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'hello world' }),
        isGeometryEditDirty: false,
      }),
    );
    expect(result.current.resolveDraftValue('summary')).toBe('hello world');
  });

  it('stagePendingDraft stages a new value and increments pending count', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'old' }),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'new value');
    });

    expect(result.current.pendingCount).toBe(1);
    expect(result.current.resolveDraftValue('summary')).toBe('new value');
  });

  it('staging a value identical to dataset value is a no-op', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'same' }),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'same');
    });

    expect(result.current.pendingCount).toBe(0);
  });

  it('staging whitespace-only value normalizes to null', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: null }),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.stagePendingDraft('summary', '   ');
    });

    // whitespace normalizes to null, dataset value is also null — no-op
    expect(result.current.pendingCount).toBe(0);
  });

  it('discardPendingDrafts clears all staged values', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'old' }),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'new');
      result.current.stagePendingDraft('lineage_summary', 'lineage');
    });
    expect(result.current.pendingCount).toBe(2);

    act(() => {
      result.current.discardPendingDrafts();
    });
    expect(result.current.pendingCount).toBe(0);
    expect(result.current.resolveDraftValue('summary')).toBe('old');
  });

  it('savePendingDrafts calls mutateAsync with staged values', async () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'old' }),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'updated');
    });

    let success: boolean | undefined;
    await act(async () => {
      success = await result.current.savePendingDrafts();
    });

    expect(success).toBe(true);
    expect(mockMutateAsync).toHaveBeenCalledWith({
      datasetId: 'ds-1',
      data: { summary: 'updated' },
    });

    await waitFor(() => {
      expect(result.current.pendingCount).toBe(0);
    });
  });

  it('savePendingDrafts returns true with no staged drafts', async () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset(),
        isGeometryEditDirty: false,
      }),
    );

    let success: boolean | undefined;
    await act(async () => {
      success = await result.current.savePendingDrafts();
    });

    expect(success).toBe(true);
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  it('savePendingDrafts returns false on error', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('save failed'));

    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'old' }),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'new');
    });

    let success: boolean | undefined;
    await act(async () => {
      success = await result.current.savePendingDrafts();
    });

    expect(success).toBe(false);
  });

  it('handleDraftDirtyChange tracks dirty fields in pending count', () => {
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset(),
        isGeometryEditDirty: false,
      }),
    );

    act(() => {
      result.current.handleDraftDirtyChange('lineage_summary', true);
    });
    expect(result.current.pendingCount).toBe(1);

    act(() => {
      result.current.handleDraftDirtyChange('lineage_summary', false);
    });
    expect(result.current.pendingCount).toBe(0);
  });
});
