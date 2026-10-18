/**
 * A JS-driven map camera animation (MapLibre easeTo/flyTo) ignores the CSS
 * `prefers-reduced-motion` media query. Callers pass the result to a
 * `duration` so the move is instant under reduced motion.
 */
function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** A camera `duration`: `full` normally, `0` under reduced-motion. */
export function motionDuration(full: number): number {
  return prefersReducedMotion() ? 0 : full;
}
