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

  it('keeps the keyboard focus outline and marks the selected item in forced colors', () => {
    render(
      <ToggleGroup type="single" defaultValue="a">
        <ToggleGroupItem value="a" aria-label="a" />
      </ToggleGroup>,
    );
    const item = screen.getByRole('radio', { name: 'a' });
    expect(item).toHaveClass(
      'forced-colors:focus-visible:outline-2',
      'forced-colors:focus-visible:outline-solid',
      'forced-colors:focus-visible:-outline-offset-2',
    );
    expect(item).toHaveClass(
      'forced-colors:data-[state=on]:bg-[Highlight]',
      'forced-colors:data-[state=on]:text-[HighlightText]',
      'forced-colors:data-[state=on]:forced-color-adjust-none',
      'forced-colors:data-[state=on]:**:text-[HighlightText]',
    );
  });
});
