import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ToggleGroup, ToggleGroupItem } from './toggle-group';

describe('ToggleGroupItem touch sizing', () => {
  it.each(['default', 'sm', 'lg', 'icon'] as const)(
    'grows the %s size to 44 px tall on a coarse pointer',
    (size) => {
      render(
        <ToggleGroup type="single">
          <ToggleGroupItem value="a" size={size} aria-label="a" />
        </ToggleGroup>,
      );
      expect(screen.getByRole('radio', { name: 'a' })).toHaveClass('pointer-coarse:min-h-11');
    },
  );

  it('gives an icon-only item a 44 px minimum width on a coarse pointer', () => {
    render(
      <ToggleGroup type="single">
        <ToggleGroupItem value="a" size="icon" aria-label="a" />
      </ToggleGroup>,
    );
    expect(screen.getByRole('radio', { name: 'a' })).toHaveClass('pointer-coarse:min-w-11');
  });
});
