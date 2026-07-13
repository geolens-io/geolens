import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Card } from '../card';

describe('Card density variants', () => {
  it('uses the standard spacing contract by default', () => {
    render(<Card data-testid="card">Content</Card>);
    const card = screen.getByTestId('card');

    expect(card).toHaveAttribute('data-density', 'default');
    expect(card).toHaveClass('gap-6', 'py-6');
  });

  it('offers named compact and flush contracts instead of spacing overrides', () => {
    const { rerender } = render(<Card data-testid="card" density="compact">Content</Card>);
    expect(screen.getByTestId('card')).toHaveClass('gap-2', 'py-4');

    rerender(<Card data-testid="card" density="flush">Content</Card>);
    expect(screen.getByTestId('card')).toHaveClass('gap-0', 'py-0');
  });
});
