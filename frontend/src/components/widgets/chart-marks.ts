import { useState, type KeyboardEvent } from 'react';

const NEXT = new Set(['ArrowDown', 'ArrowRight']);
const PREVIOUS = new Set(['ArrowUp', 'ArrowLeft']);

/**
 * Keyboard and pointer handling for a chart of `count` marks drawn as one tab
 * stop: arrow keys, Home and End move the active mark, focus starts at the
 * first, and with `onPick` a click on a mark, or Enter or Space on the active
 * one, picks it. Spread `chartProps` on the SVG and `markProps(i)` on each mark.
 */
export function useChartMarks(count: number, onPick?: (index: number) => void) {
  const [active, setActive] = useState<number | null>(null);
  const current = active === null || count === 0 ? null : Math.min(active, count - 1);

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (onPick && current !== null && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      onPick(current);
      return;
    }
    const from = current ?? -1;
    const last = count - 1;
    const next = NEXT.has(event.key)
      ? Math.min(from + 1, last)
      : PREVIOUS.has(event.key)
        ? Math.max(from - 1, 0)
        : event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? last
            : null;
    if (next === null) return;
    event.preventDefault();
    setActive(next);
  };

  return {
    current,
    chartProps: {
      tabIndex: 0,
      onKeyDown,
      onFocus: () => setActive((value) => value ?? 0),
      className:
        'h-auto w-full rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
    },
    markProps: (index: number) =>
      onPick
        ? {
            className: 'cursor-pointer',
            onClick: () => {
              setActive(index);
              onPick(index);
            },
          }
        : {},
  };
}
