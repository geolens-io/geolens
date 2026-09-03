/**
 * fix(#1746 B2b review r24/r26): an unknown row-count delta is not zero.
 *
 * `row_count_delta` became nullable in r24, because coercing an unknown count
 * to 0 invented a delta the size of whichever side was known. r26 found the
 * other half of that in this component: `?? 0` turned the deliberately null
 * delta back into zero, so a re-upload whose row count nobody had established
 * reported "No schema changes detected" whenever the columns matched.
 *
 * The count is unknown on exactly the path this PR added: a protected OGC API
 * collection whose service publishes no `numberMatched`.
 */
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import { SchemaDiffView } from '@/components/dataset/SchemaDiffView';
import type { SchemaDiff } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string; count?: number }) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : (opts?.defaultValue ?? key),
  }),
}));

function diff(overrides: Partial<SchemaDiff> = {}): SchemaDiff {
  return {
    columns_added: [],
    columns_removed: [],
    type_changes: [],
    row_count_old: 1200,
    row_count_new: null,
    row_count_delta: null,
    ...overrides,
  };
}

describe('SchemaDiffView with an unknown row count', () => {
  it('does not claim there are no changes', () => {
    render(<SchemaDiffView schemaDiff={diff()} />);

    expect(screen.queryByText('schemaDiff.noChanges')).not.toBeInTheDocument();
  });

  it('says the row count could not be established', () => {
    render(<SchemaDiffView schemaDiff={diff()} />);

    expect(screen.getByText('schemaDiff.rowCountUnknown')).toBeInTheDocument();
  });

  it('shows the not-available label rather than a number for the delta', () => {
    render(<SchemaDiffView schemaDiff={diff()} />);

    // Twice: once for the unknown new-row count, once for the unknown delta.
    expect(screen.getAllByText('common:notAvailable')).toHaveLength(2);
  });

  it('still claims no changes when the delta is genuinely zero', () => {
    render(
      <SchemaDiffView
        schemaDiff={diff({ row_count_new: 1200, row_count_delta: 0 })}
      />,
    );

    expect(screen.getByText('schemaDiff.noChanges')).toBeInTheDocument();
    expect(
      screen.queryByText('schemaDiff.rowCountUnknown'),
    ).not.toBeInTheDocument();
  });

  it('still renders a known delta with its sign', () => {
    render(
      <SchemaDiffView
        schemaDiff={diff({ row_count_new: 1500, row_count_delta: 300 })}
      />,
    );

    expect(screen.getByText(/\+/)).toBeInTheDocument();
    expect(
      screen.queryByText('schemaDiff.rowCountUnknown'),
    ).not.toBeInTheDocument();
  });

  it('does not show the unknown line when there are real column changes', () => {
    render(
      <SchemaDiffView
        schemaDiff={diff({ columns_added: [{ name: 'x', type: 'String' }] })}
      />,
    );

    expect(
      screen.queryByText('schemaDiff.rowCountUnknown'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('schemaDiff.noChanges')).not.toBeInTheDocument();
  });
});
