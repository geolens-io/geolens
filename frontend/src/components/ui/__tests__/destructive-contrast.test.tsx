import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from '../button';
import { Badge } from '../badge';

/**
 * Regression test for the destructive-variant dark-mode contrast bug:
 * `dark:bg-destructive/60` composited over --card, read with
 * `text-destructive-foreground` (a dark-on-dark token tuned for the SOLID
 * light fill), measures 2.61:1 -- below the 4.5:1 WCAG 1.4.3 floor.
 * `text-white` measures 6.24:1 against the same dark fill and >5.9:1
 * against the light-mode solid fill, so both variants use it instead.
 */
describe('destructive variant contrast', () => {
  it('button destructive variant does not pair text-destructive-foreground with the translucent dark fill', () => {
    render(<Button variant="destructive">Delete</Button>);
    const button = screen.getByRole('button', { name: 'Delete' });

    expect(button).toHaveClass('text-white');
    expect(button).toHaveClass('dark:bg-destructive/60');
    expect(button.className).not.toMatch(/\btext-destructive-foreground\b/);
  });

  it('badge destructive variant does not pair text-destructive-foreground with the translucent dark fill', () => {
    render(<Badge variant="destructive">Expired</Badge>);
    const badge = screen.getByText('Expired');

    expect(badge).toHaveClass('text-white');
    expect(badge).toHaveClass('dark:bg-destructive/60');
    expect(badge.className).not.toMatch(/\btext-destructive-foreground\b/);
  });
});
