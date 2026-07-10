/**
 * fix(#438): A11Y-08 — a JS-driven map camera animation (MapLibre easeTo/flyTo)
 * cannot be stopped by the CSS `prefers-reduced-motion` media query the app
 * already respects for CSS transitions. Callers pass the result of this to a
 * `duration` so the move is instant when the user has asked for reduced motion.
 */
export function prefersReducedMotion(): boolean {
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
