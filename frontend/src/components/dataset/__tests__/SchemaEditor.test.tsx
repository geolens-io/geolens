/**
 * fix(#458 E-38/E-49/E-50): SchemaEditor accessibility + destructive-confirm
 * guards. First direct suite for this component (StructureTab.test mocks it
 * away), covering:
 * - E-38: name-validation errors are announced (role="alert") and associated
 *   with the input (aria-invalid/aria-describedby).
 * - E-49: the name input and type select carry accessible names.
 * - E-50: the drop-column Confirm stays disabled until the map-references
 *   query resolves, so a fast confirm can't outrun the E-06 warning.
 */
import { render, screen, fireEvent, act } from '@testing-library/react';
import { vi } from 'vitest';
import { toast } from 'sonner';
import { SchemaEditor } from '@/components/dataset/SchemaEditor';
import { useAddColumn, useColumnReferences, useDropColumn } from '@/hooks/use-features';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
  }),
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('@/hooks/use-features', () => ({
  useAddColumn: vi.fn(),
  useDropColumn: vi.fn(),
  useColumnReferences: vi.fn(),
}));

Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
});

const COLUMNS = [
  { name: 'name', type: 'character varying' },
  { name: 'value', type: 'integer' },
];

function renderEditor(datasetId = 'test-ds') {
  return render(
    <SchemaEditor
      datasetId={datasetId}
      columns={COLUMNS}
      open
      onOpenChange={vi.fn()}
    />,
  );
}

describe('SchemaEditor (E-38/E-49/E-50)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ sessionEpoch: 0, user: null });
    vi.mocked(useAddColumn).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useAddColumn>);
    vi.mocked(useDropColumn).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useDropColumn>);
    vi.mocked(useColumnReferences).mockReturnValue({
      data: { map_count: 0 },
      isLoading: false,
    } as unknown as ReturnType<typeof useColumnReferences>);
  });

  it('E-49: name input and type select carry accessible names', () => {
    renderEditor();
    expect(
      screen.getByRole('textbox', { name: 'schema.addColumn' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: 'schema.columnType' }),
    ).toBeInTheDocument();
  });

  it('E-38: a reserved name announces an associated validation error', () => {
    renderEditor();
    const input = screen.getByRole('textbox', { name: 'schema.addColumn' });
    fireEvent.change(input, { target: { value: 'gid' } });
    fireEvent.click(screen.getByRole('button', { name: /schema\.add$/ }));

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('schema.validation.reserved');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input.getAttribute('aria-describedby')).toBe(alert.id);
    // ...and typing clears it
    fireEvent.change(input, { target: { value: 'gid2' } });
    expect(screen.queryByRole('alert')).toBeNull();
    expect(input).not.toHaveAttribute('aria-invalid');
  });

  it('E-50: drop confirm is disabled while the map-references query loads', () => {
    vi.mocked(useColumnReferences).mockReturnValue({
      data: undefined,
      isLoading: true,
    } as unknown as ReturnType<typeof useColumnReferences>);
    renderEditor();

    fireEvent.click(screen.getAllByTitle('schema.removeColumn')[0]);
    expect(
      screen.getByRole('button', { name: 'common:confirm' }),
    ).toBeDisabled();
  });

  it('E-50: drop confirm enables once references resolve, showing the E-06 warning', () => {
    vi.mocked(useColumnReferences).mockReturnValue({
      data: { map_count: 2 },
      isLoading: false,
    } as unknown as ReturnType<typeof useColumnReferences>);
    renderEditor();

    fireEvent.click(screen.getAllByTitle('schema.removeColumn')[0]);
    expect(
      screen.getByRole('button', { name: 'common:confirm' }),
    ).toBeEnabled();
    expect(screen.getByText('schema.usedByMaps')).toBeInTheDocument();
  });

  it('preserves a new column name typed while the previous add is pending', () => {
    let onSuccess: (() => void) | undefined;
    const mutate = vi.fn((_variables, options) => {
      onSuccess = options?.onSuccess;
    });
    vi.mocked(useAddColumn).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useAddColumn>);
    renderEditor();

    const input = screen.getByRole('textbox', { name: 'schema.addColumn' });
    fireEvent.change(input, { target: { value: 'first_column' } });
    fireEvent.click(screen.getByRole('button', { name: /schema\.add$/ }));
    fireEvent.change(input, { target: { value: 'next_column' } });
    onSuccess?.();

    expect(input).toHaveValue('next_column');
  });

  it('preserves a changed type while the previous add is pending', async () => {
    let onSuccess: (() => void) | undefined;
    vi.mocked(useAddColumn).mockReturnValue({
      mutate: vi.fn((_variables, options) => {
        onSuccess = options?.onSuccess;
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useAddColumn>);
    renderEditor();

    fireEvent.change(screen.getByRole('textbox', { name: 'schema.addColumn' }), {
      target: { value: 'new_column' },
    });
    fireEvent.click(screen.getByRole('button', { name: /schema\.add$/ }));
    const typeSelect = screen.getByRole('combobox', { name: 'schema.columnType' });
    fireEvent.keyDown(typeSelect, { key: 'ArrowDown' });
    fireEvent.click(await screen.findByRole('option', { name: 'integer' }));
    onSuccess?.();

    expect(screen.getByRole('combobox', { name: 'schema.columnType' }))
      .toHaveTextContent('integer');
  });

  it('ignores an add completion after dataset A is left and reopened', () => {
    let onSuccess: (() => void) | undefined;
    vi.mocked(useAddColumn).mockReturnValue({
      mutate: vi.fn((_variables, options) => {
        onSuccess = options?.onSuccess;
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useAddColumn>);
    const { rerender } = renderEditor('dataset-a');
    const input = screen.getByRole('textbox', { name: 'schema.addColumn' });
    fireEvent.change(input, { target: { value: 'first_column' } });
    fireEvent.click(screen.getByRole('button', { name: /schema\.add$/ }));

    rerender(<SchemaEditor datasetId="dataset-b" columns={COLUMNS} open onOpenChange={vi.fn()} />);
    rerender(<SchemaEditor datasetId="dataset-a" columns={COLUMNS} open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'schema.addColumn' }), {
      target: { value: 'current_column' },
    });
    onSuccess?.();

    expect(screen.getByRole('textbox', { name: 'schema.addColumn' }))
      .toHaveValue('current_column');
  });

  it('ignores an add completion after the auth session changes', () => {
    let onSuccess: (() => void) | undefined;
    vi.mocked(useAddColumn).mockReturnValue({
      mutate: vi.fn((_variables, options) => {
        onSuccess = options?.onSuccess;
      }),
      isPending: false,
    } as unknown as ReturnType<typeof useAddColumn>);
    renderEditor();
    const input = screen.getByRole('textbox', { name: 'schema.addColumn' });
    fireEvent.change(input, { target: { value: 'new_column' } });
    fireEvent.click(screen.getByRole('button', { name: /schema\.add$/ }));

    useAuthStore.setState({ sessionEpoch: 1 });
    onSuccess?.();

    expect(input).toHaveValue('new_column');
  });

  it('ignores repeated Enter submissions while an add is pending', () => {
    const mutate = vi.fn();
    vi.mocked(useAddColumn).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useAddColumn>);
    renderEditor();

    const input = screen.getByRole('textbox', { name: 'schema.addColumn' });
    fireEvent.change(input, { target: { value: 'new_column' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(mutate).toHaveBeenCalledTimes(1);
  });
});


describe('schema response scope', () => {
  it.each(['success', 'failure'])('preserves a newer drop confirmation after old %s', (outcome) => {
    vi.clearAllMocks();
    let callbacks: { onSuccess: () => void; onError: (error: Error) => void };
    vi.mocked(useAddColumn).mockReturnValue({ mutate: vi.fn(), isPending: false } as unknown as ReturnType<typeof useAddColumn>);
    vi.mocked(useDropColumn).mockReturnValue({
      mutate: vi.fn((_variables, options) => { callbacks = options; }),
      isPending: false,
    } as unknown as ReturnType<typeof useDropColumn>);
    vi.mocked(useColumnReferences).mockReturnValue({ data: { map_count: 0 }, isLoading: false } as unknown as ReturnType<typeof useColumnReferences>);
    const { rerender } = renderEditor('dataset-a');
    fireEvent.click(screen.getAllByTitle('schema.removeColumn')[0]);
    fireEvent.click(screen.getByRole('button', { name: 'common:confirm' }));
    rerender(<SchemaEditor datasetId="dataset-b" columns={COLUMNS} open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getAllByTitle('schema.removeColumn')[1]);
    act(() => {
      if (outcome === 'success') callbacks.onSuccess();
      else callbacks.onError(new Error('Old failure'));
    });
    expect(screen.getByRole('button', { name: 'common:confirm' })).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
