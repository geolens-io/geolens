import { describe, expect, it } from 'vitest';

/**
 * --warning-foreground is a DARK value in BOTH themes (tuned as text over a
 * solid bg-warning fill). Used as text on card or soft-tint surfaces it
 * composites to ~1.05:1 in dark mode — a WCAG 1.4.3 failure. The on-tint /
 * on-card warning text color is `text-warning`, which is tuned to clear AA
 * on card AND /10 tints in both themes (see the #305 comment in index.css).
 *
 * No component currently renders a solid bg-warning fill, so there is no
 * legitimate use of text-warning-foreground in components today. If one is
 * introduced, pair it with a solid bg-warning AND retune the light-mode
 * value first (it measured 2.42:1 on solid warning at time of writing).
 */
const sources = import.meta.glob(['/src/**/*.tsx', '/src/**/*.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

describe('warning-foreground usage', () => {
  it('is not used as a text color in components', () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.includes('__tests__') && !path.endsWith('.test.ts') && !path.endsWith('.test.tsx'))
      .filter(([, source]) => source.includes('text-warning-foreground'))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
