/**
 * Integration tests for the empty-state → modal pre-fill → add → flyout flow.
 *
 * These tests mount EmptyStackState inside a stub parent that mirrors
 * MapBuilderPage's handleAddDataClick + onAddDataset wiring, verifying the
 * end-to-end contract between components:
 *   - inline search → onOpenAddData(query)
 *   - suggest-card body → onOpenAddData(name)
 *   - suggest-card ＋ button → onAddDataset(id) → onSuccess(newLayerId)
 *   - Browse all → onOpenAddData() with no pre-fill
 *   - stopPropagation: ＋ does NOT also trigger card-body
 *
 * Requirement: BSR-17 (inline search → modal pre-fill) and BSR-18
 * (suggest-card ＋ → direct add → flyout open).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@/test/test-utils';
import { EmptyStackState } from '@/components/builder/EmptyStackState';
import { getDataset } from '@/api/datasets';
import { SUGGESTED_DATASETS } from '@/components/builder/suggested-datasets';

// ---- module mocks ----

vi.mock('@/api/datasets', () => ({
  getDataset: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string } & Record<string, unknown>) =>
      opts?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

// ---- helpers ----

const mockGetDataset = vi.mocked(getDataset);

beforeEach(() => {
  vi.clearAllMocks();
  // Resolve all dataset queries so all suggest-cards render
  mockGetDataset.mockResolvedValue({
    id: 'mock-id',
    display_name: 'Mock Dataset',
  } as unknown as Awaited<ReturnType<typeof getDataset>>);
});

// ---- tests ----

describe('EmptyStackState integration — BSR-17 / BSR-18', () => {
  it('Test 1: typing "roads" + Enter calls onOpenAddData("roads")', () => {
    const onOpenAddData = vi.fn();
    const onAddDataset = vi.fn();

    render(
      <EmptyStackState
        onOpenAddData={onOpenAddData}
        onAddDataset={onAddDataset}
      />,
    );

    const input = screen.getByRole('searchbox');
    fireEvent.change(input, { target: { value: 'roads' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onOpenAddData).toHaveBeenCalledOnce();
    expect(onOpenAddData).toHaveBeenCalledWith('roads');
    // Direct-add must NOT have fired
    expect(onAddDataset).not.toHaveBeenCalled();
  });

  it('Test 2: clicking suggest-card body calls onOpenAddData(suggestion.name)', () => {
    const onOpenAddData = vi.fn();
    const onAddDataset = vi.fn();

    render(
      <EmptyStackState
        onOpenAddData={onOpenAddData}
        onAddDataset={onAddDataset}
      />,
    );

    const suggestion = SUGGESTED_DATASETS[0];
    const cardBody = screen.getByRole('button', {
      name: `Open ${suggestion.name} in Add Data modal`,
    });
    fireEvent.click(cardBody);

    expect(onOpenAddData).toHaveBeenCalledOnce();
    expect(onOpenAddData).toHaveBeenCalledWith(suggestion.name);
    // Direct-add must NOT have fired
    expect(onAddDataset).not.toHaveBeenCalled();
  });

  it('Test 3: clicking ＋ button calls onAddDataset(id) and parent can invoke success callback', () => {
    // Simulate MapBuilderPage's onAddDataset wrapper:
    //   (id) => layers.handleAddDataset(id, (newLayerId) => handleSelectLayer(newLayerId))
    // In this test the "handleSelectLayer" role is played by onSuccessSpy.
    const onSuccessSpy = vi.fn();
    const onOpenAddData = vi.fn();

    // Stub parent wiring: onAddDataset invokes the success handler synchronously
    const onAddDataset = vi.fn((id: string) => {
      // The parent would call handleAddDataset(id, cb) and the mutation
      // onSuccess fires cb(newLayerId). We simulate that here:
      onSuccessSpy(`fake-layer-id-for-${id}`);
    });

    render(
      <EmptyStackState
        onOpenAddData={onOpenAddData}
        onAddDataset={onAddDataset}
      />,
    );

    const suggestion = SUGGESTED_DATASETS[0];
    const addBtn = screen.getByRole('button', { name: `Add ${suggestion.name} to map` });
    fireEvent.click(addBtn);

    // onAddDataset is called with the dataset ID
    expect(onAddDataset).toHaveBeenCalledOnce();
    expect(onAddDataset).toHaveBeenCalledWith(suggestion.id);

    // The parent's success handler fires (simulates flyout auto-open)
    expect(onSuccessSpy).toHaveBeenCalledOnce();
    expect(onSuccessSpy).toHaveBeenCalledWith(`fake-layer-id-for-${suggestion.id}`);

    // Modal-open must NOT have fired
    expect(onOpenAddData).not.toHaveBeenCalled();
  });

  it('Test 4: clicking "Browse all datasets →" calls onOpenAddData with no pre-fill', () => {
    const onOpenAddData = vi.fn();
    const onAddDataset = vi.fn();

    render(
      <EmptyStackState
        onOpenAddData={onOpenAddData}
        onAddDataset={onAddDataset}
      />,
    );

    const browseBtn = screen.getByRole('button', {
      name: 'Browse all datasets in the Add Data modal',
    });
    fireEvent.click(browseBtn);

    expect(onOpenAddData).toHaveBeenCalledOnce();
    // Called with no args (or undefined) — NOT with a query string
    const callArgs = onOpenAddData.mock.calls[0];
    expect(callArgs.length === 0 || callArgs[0] === undefined).toBe(true);

    expect(onAddDataset).not.toHaveBeenCalled();
  });

  it('Test 5 (regression): ＋ button stopPropagation — does NOT trigger card-body click', () => {
    const onOpenAddData = vi.fn();
    const onAddDataset = vi.fn();

    render(
      <EmptyStackState
        onOpenAddData={onOpenAddData}
        onAddDataset={onAddDataset}
      />,
    );

    const suggestion = SUGGESTED_DATASETS[0];
    const addBtn = screen.getByRole('button', { name: `Add ${suggestion.name} to map` });
    fireEvent.click(addBtn);

    // Direct-add fires once
    expect(onAddDataset).toHaveBeenCalledOnce();
    expect(onAddDataset).toHaveBeenCalledWith(suggestion.id);

    // Modal-open must NOT have fired (stopPropagation is intact)
    expect(onOpenAddData).not.toHaveBeenCalled();
  });
});
