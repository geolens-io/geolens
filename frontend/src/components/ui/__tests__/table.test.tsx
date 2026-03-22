import { render } from '@testing-library/react';
import { Table, TableBody, TableRow, TableCell } from '../table';

function renderTable(props?: Record<string, unknown>) {
  return render(
    <Table {...props}>
      <TableBody>
        <TableRow>
          <TableCell>test</TableCell>
        </TableRow>
      </TableBody>
    </Table>,
  );
}

describe('Table A11Y-03: keyboard-accessible container', () => {
  it('has tabIndex=0 on the container', () => {
    renderTable();
    const container = document.querySelector('[data-slot="table-container"]')!;
    expect(container.getAttribute('tabindex')).toBe('0');
  });

  it('has role=region on the container', () => {
    renderTable();
    const container = document.querySelector('[data-slot="table-container"]')!;
    expect(container.getAttribute('role')).toBe('region');
  });

  it('has default aria-label "Scrollable table"', () => {
    renderTable();
    const container = document.querySelector('[data-slot="table-container"]')!;
    expect(container.getAttribute('aria-label')).toBe('Scrollable table');
  });

  it('accepts custom aria-label', () => {
    renderTable({ 'aria-label': 'Dataset attributes' });
    const container = document.querySelector('[data-slot="table-container"]')!;
    expect(container.getAttribute('aria-label')).toBe('Dataset attributes');
  });

  it('has focus-visible ring classes', () => {
    renderTable();
    const container = document.querySelector('[data-slot="table-container"]')!;
    expect(container.className).toContain('focus-visible:ring-2');
    expect(container.className).toContain('focus-visible:ring-ring');
  });
});
