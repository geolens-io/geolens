import { renderHook, act, waitFor } from '@testing-library/react';
import { useDraftEditing } from '@/components/dataset/hooks/use-draft-editing';
import type { DatasetResponse, UserResponse } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';

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

  it('savePendingDrafts includes a draft staged after the callback was captured (E-17)', async () => {
    // fix(#458 E-17): savePendingDrafts blurs the focused input, which stages its
    // edit mid-call. The old code read `pendingDrafts` from the callback closure
    // and dropped that field; the ref-based read captures it. Capturing `save`
    // BEFORE staging reproduces the stale-closure condition.
    const { result } = renderHook(() =>
      useDraftEditing({
        datasetId: 'ds-1',
        dataset: makeDataset({ summary: 'old' }),
        isGeometryEditDirty: false,
      }),
    );

    const save = result.current.savePendingDrafts;
    act(() => {
      result.current.stagePendingDraft('summary', 'late value');
    });

    await act(async () => {
      await save();
    });

    expect(mockMutateAsync).toHaveBeenCalledWith({
      datasetId: 'ds-1',
      data: { summary: 'late value' },
    });
  });

  it('save after discard sends nothing (ref is reset)', async () => {
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
    act(() => {
      result.current.discardPendingDrafts();
    });

    await act(async () => {
      await result.current.savePendingDrafts();
    });

    expect(mockMutateAsync).not.toHaveBeenCalled();
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

  // fix(#1851): DatasetPage stays mounted across a route change from one
  // dataset to another, so without a reset keyed on datasetId a staged draft
  // for dataset A survived into dataset B's render.
  it('resets staged drafts when datasetId changes', () => {
    const { result, rerender } = renderHook(
      ({ datasetId, dataset }) =>
        useDraftEditing({ datasetId, dataset, isGeometryEditDirty: false }),
      {
        initialProps: {
          datasetId: 'ds-1',
          dataset: makeDataset({ id: 'ds-1', summary: 'A summary' }),
        },
      },
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'A edited summary');
    });
    expect(result.current.pendingCount).toBe(1);

    rerender({
      datasetId: 'ds-2',
      dataset: makeDataset({ id: 'ds-2', summary: 'B summary' }),
    });

    expect(result.current.pendingCount).toBe(0);
    expect(result.current.resolveDraftValue('summary')).toBe('B summary');
  });

  it('a save after navigating to a different dataset does not send the previous draft', async () => {
    const { result, rerender } = renderHook(
      ({ datasetId, dataset }) =>
        useDraftEditing({ datasetId, dataset, isGeometryEditDirty: false }),
      {
        initialProps: {
          datasetId: 'ds-1',
          dataset: makeDataset({ id: 'ds-1', summary: 'A summary' }),
        },
      },
    );

    act(() => {
      result.current.stagePendingDraft('summary', 'A edited summary');
    });

    rerender({
      datasetId: 'ds-2',
      dataset: makeDataset({ id: 'ds-2', summary: 'B summary' }),
    });

    await act(async () => {
      await result.current.savePendingDrafts();
    });

    expect(mockMutateAsync).not.toHaveBeenCalled();
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

function deferredSave() {
  let resolve!: (value: unknown) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<unknown>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderDraft() {
  return renderHook(
    ({ id }) =>
      useDraftEditing({
        datasetId: id,
        dataset: makeDataset({ id, summary: `${id} original` }),
        isGeometryEditDirty: false,
      }),
    { initialProps: { id: 'A' } },
  );
}

function draftUser(id: string): UserResponse {
  return {
    id,
    username: id,
    email: `${id}@example.com`,
    is_active: true,
    status: 'approved',
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    roles: ['editor'],
  };
}

describe('draft save races', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset().mockResolvedValue({});
    useAuthStore.setState({ user: draftUser('user-A'), sessionEpoch: 0 });
  });

  it('clears staged and dirty metadata after a user switch without an epoch change', async () => {
    const { result } = renderDraft();
    act(() => {
      result.current.stagePendingDraft('summary', 'user A draft');
      result.current.handleDraftDirtyChange('lineage_summary', true);
    });
    const staleSave = result.current.savePendingDrafts;
    let saving!: Promise<boolean>;
    act(() => {
      useAuthStore.setState({ user: draftUser('user-B') });
      saving = staleSave();
    });
    await act(async () => expect(await saving).toBe(false));
    expect(useAuthStore.getState().sessionEpoch).toBe(0);
    expect(result.current.pendingCount).toBe(0);
    expect(result.current.resolveDraftValue('summary')).toBe('A original');
    await act(async () => {
      await result.current.savePendingDrafts();
    });
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  it.each(['success', 'failure'])(
    'preserves the new user draft after the old user save %s without an epoch change',
    async (outcome) => {
      const request = deferredSave();
      mockMutateAsync.mockReturnValueOnce(request.promise);
      const { result } = renderDraft();
      act(() => result.current.stagePendingDraft('summary', 'user A submitted'));
      let saving!: Promise<boolean>;
      act(() => {
        saving = result.current.savePendingDrafts();
      });
      await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
      act(() => useAuthStore.setState({ user: draftUser('user-B') }));
      expect(result.current.isSaving).toBe(false);
      act(() => result.current.stagePendingDraft('summary', 'user B draft'));
      await act(async () => {
        if (outcome === 'success') request.resolve({});
        else request.reject(new Error('failed'));
        expect(await saving).toBe(false);
      });
      expect(result.current.resolveDraftValue('summary')).toBe('user B draft');
      expect(result.current.pendingCount).toBe(1);
      await act(async () => expect(await result.current.savePendingDrafts()).toBe(true));
      expect(mockMutateAsync).toHaveBeenLastCalledWith({
        datasetId: 'A',
        data: { summary: 'user B draft' },
      });
    },
  );

  it.each(['success', 'failure'])(
    'preserves another dataset draft after old save %s',
    async (outcome) => {
      const request = deferredSave();
      mockMutateAsync.mockReturnValueOnce(request.promise);
      const { result, rerender } = renderDraft();
      act(() => result.current.stagePendingDraft('summary', 'A submitted'));
      let saving!: Promise<boolean>;
      act(() => {
        saving = result.current.savePendingDrafts();
      });
      await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
      rerender({ id: 'B' });
      act(() => result.current.stagePendingDraft('summary', 'B draft'));
      await act(async () => {
        if (outcome === 'success') request.resolve({});
        else request.reject(new Error('failed'));
        expect(await saving).toBe(false);
      });
      expect(result.current.resolveDraftValue('summary')).toBe('B draft');
      expect(result.current.pendingCount).toBe(1);
      expect(result.current.isSaving).toBe(false);
    },
  );

  it.each(['new edit', 'A original'])(
    'preserves input staged during a save: %s',
    async (laterValue) => {
      const request = deferredSave();
      mockMutateAsync.mockReturnValueOnce(request.promise);
      const { result } = renderDraft();
      act(() => result.current.stagePendingDraft('summary', 'submitted'));
      let saving!: Promise<boolean>;
      act(() => {
        saving = result.current.savePendingDrafts();
      });
      await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
      act(() => result.current.stagePendingDraft('summary', laterValue));
      await act(async () => {
        request.resolve({});
        await saving;
      });
      expect(result.current.pendingCount).toBe(1);
      expect(result.current.resolveDraftValue('summary')).toBe(laterValue);
      await act(async () => {
        await result.current.savePendingDrafts();
      });
      expect(mockMutateAsync).toHaveBeenLastCalledWith({
        datasetId: 'A',
        data: { summary: laterValue },
      });
    },
  );

  it('keeps the submitted value retryable when a reverted in-flight edit fails', async () => {
    const request = deferredSave();
    mockMutateAsync.mockReturnValueOnce(request.promise);
    const { result } = renderDraft();
    act(() => result.current.stagePendingDraft('summary', 'submitted'));
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.savePendingDrafts();
    });
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    act(() => result.current.stagePendingDraft('summary', 'second edit'));
    act(() => result.current.stagePendingDraft('summary', 'submitted'));
    expect(result.current.resolveDraftValue('summary')).toBe('submitted');
    await act(async () => {
      request.reject(new Error('failed'));
      expect(await saving).toBe(false);
    });
    expect(result.current.pendingCount).toBe(1);
    expect(result.current.resolveDraftValue('summary')).toBe('submitted');
    await act(async () => {
      await result.current.savePendingDrafts();
    });
    expect(mockMutateAsync).toHaveBeenLastCalledWith({
      datasetId: 'A',
      data: { summary: 'submitted' },
    });
  });

  it('keeps a newer dataset save active when the old request finishes', async () => {
    const first = deferredSave();
    const second = deferredSave();
    mockMutateAsync.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderDraft();
    act(() => result.current.stagePendingDraft('summary', 'A draft'));
    let firstSave!: Promise<boolean>;
    act(() => {
      firstSave = result.current.savePendingDrafts();
    });
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    rerender({ id: 'B' });
    act(() => result.current.stagePendingDraft('summary', 'B draft'));
    let secondSave!: Promise<boolean>;
    act(() => {
      secondSave = result.current.savePendingDrafts();
    });
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(2));
    await act(async () => {
      first.resolve({});
      await firstSave;
    });
    expect(result.current.isSaving).toBe(true);
    expect(result.current.pendingCount).toBe(1);
    await act(async () => {
      second.resolve({});
      await secondSave;
    });
    expect(result.current.pendingCount).toBe(0);
  });

  it('preserves unblurred changes after a save', async () => {
    const request = deferredSave();
    mockMutateAsync.mockReturnValueOnce(request.promise);
    const { result } = renderDraft();
    act(() => result.current.stagePendingDraft('summary', 'submitted'));
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.savePendingDrafts();
    });
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    act(() => result.current.handleDraftDirtyChange('summary', true));
    await act(async () => {
      request.resolve({});
      await saving;
    });
    expect(result.current.pendingCount).toBe(1);
    act(() => {
      result.current.stagePendingDraft('summary', 'latest input');
      result.current.handleDraftDirtyChange('summary', false);
    });
    await act(async () => {
      await result.current.savePendingDrafts();
    });
    expect(mockMutateAsync).toHaveBeenLastCalledWith({
      datasetId: 'A',
      data: { summary: 'latest input' },
    });
  });

  it('does not clear drafts after the authentication identity changes', async () => {
    const request = deferredSave();
    mockMutateAsync.mockReturnValueOnce(request.promise);
    const { result } = renderDraft();
    act(() => result.current.stagePendingDraft('summary', 'old session'));
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.savePendingDrafts();
    });
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    act(() =>
      useAuthStore.setState({
        sessionEpoch: useAuthStore.getState().sessionEpoch + 1,
      }),
    );
    act(() => result.current.stagePendingDraft('summary', 'new session'));
    await act(async () => {
      request.resolve({});
      expect(await saving).toBe(false);
    });
    expect(result.current.resolveDraftValue('summary')).toBe('new session');
    expect(result.current.pendingCount).toBe(1);
  });

  it('rejects a save callback captured before navigation', async () => {
    const { result, rerender } = renderDraft();
    const staleSave = result.current.savePendingDrafts;
    rerender({ id: 'B' });
    act(() => result.current.stagePendingDraft('summary', 'B draft'));
    await act(async () => {
      expect(await staleSave()).toBe(false);
    });
    expect(mockMutateAsync).not.toHaveBeenCalled();
    expect(result.current.pendingCount).toBe(1);
  });

  it('prevents duplicate saves before blur settles', async () => {
    const request = deferredSave();
    mockMutateAsync.mockReturnValueOnce(request.promise);
    const { result } = renderDraft();
    act(() => result.current.stagePendingDraft('summary', 'submitted'));
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.savePendingDrafts();
    });
    await act(async () => {
      expect(await result.current.savePendingDrafts()).toBe(false);
    });
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    await act(async () => {
      request.resolve({});
      await saving;
    });
  });
});
