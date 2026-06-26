import { render, screen } from '@/test/test-utils';
import { FieldLabel } from '../field-label';

describe('FieldLabel', () => {
  it('renders a label that gives its associated input an accessible name', () => {
    render(
      <>
        <FieldLabel htmlFor="test-input">Search maps</FieldLabel>
        <input id="test-input" type="text" />
      </>,
    );
    // getByLabelText resolves via the htmlFor → id association
    expect(screen.getByLabelText('Search maps')).toBeInTheDocument();
  });

  it('applies sr-only class by default so the label is visually hidden', () => {
    render(
      <FieldLabel htmlFor="hidden-label-input">Hidden label</FieldLabel>,
    );
    const label = screen.getByText('Hidden label');
    expect(label).toHaveClass('sr-only');
  });

  it('allows callers to pass additional className to override visibility', () => {
    render(
      <FieldLabel htmlFor="visible-label-input" className="visible-label">
        Visible label
      </FieldLabel>,
    );
    const label = screen.getByText('Visible label');
    // Caller-provided class is applied (sr-only is merged via cn so it may be
    // overridden when callers supply contradictory Tailwind utilities)
    expect(label).toHaveClass('visible-label');
  });

  it('renders children as the label text content', () => {
    render(
      <FieldLabel htmlFor="children-test">My label text</FieldLabel>,
    );
    expect(screen.getByText('My label text')).toBeInTheDocument();
  });
});
