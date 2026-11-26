import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Button } from './button';

const EDGE = [
  'forced-colors:outline-1',
  'forced-colors:outline-[ButtonText]',
  'forced-colors:disabled:outline-[GrayText]',
];

describe('Button forced colors', () => {
  it.each(['default', 'destructive', 'secondary'] as const)(
    'keeps a visible edge on the %s variant',
    (variant) => {
      render(<Button variant={variant}>Go</Button>);
      expect(screen.getByRole('button')).toHaveClass(...EDGE);
    },
  );

  it.each(['outline', 'ghost', 'link'] as const)(
    'leaves the %s variant without the filled edge',
    (variant) => {
      render(<Button variant={variant}>Go</Button>);
      expect(screen.getByRole('button').className).not.toContain('forced-colors:outline');
    },
  );
});
