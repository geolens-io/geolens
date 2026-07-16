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
import { render, screen, fireEvent } from '@testing-library/react';
import { vi } from 'vitest';
import { SchemaEditor } from '@/components/dataset/SchemaEditor';
import { useAddColumn, useColumnReferences, useDropColumn } from '@/hooks/use-features';

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

const COLUMNS = [
  { name: 'name', type: 'character varying' },
  { name: 'value', type: 'integer' },
];

function renderEditor() {
  return render(
    <SchemaEditor
      datasetId="test-ds"
      columns={COLUMNS}
      open
      onOpenChange={vi.fn()}
    />,
  );
}

describe('SchemaEditor (E-38/E-49/E-50)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
