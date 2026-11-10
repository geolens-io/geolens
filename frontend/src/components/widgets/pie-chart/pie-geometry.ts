/** One slice: its angles in radians, clockwise from twelve o'clock, and its share of the whole. */
export interface PieArc {
  start: number;
  end: number;
  share: number;
}

const FULL = Math.PI * 2;

/** The slices for `amounts`; a value that isn't a positive number takes no room. */
export function pieArcs(amounts: readonly number[]): PieArc[] {
  const positive = amounts.map((amount) => (Number.isFinite(amount) && amount > 0 ? amount : 0));
  // Scaled by the largest first, so a sum of huge values can't overflow to Infinity.
  const largest = Math.max(0, ...positive);
  const sizes = positive.map((size) => (largest > 0 ? size / largest : 0));
  const total = sizes.reduce((sum, size) => sum + size, 0);
  let angle = 0;
  return sizes.map((size) => {
    const share = total > 0 ? size / total : 0;
    const start = angle;
    angle += share * FULL;
    return { start, end: angle, share };
  });
}

const point = (cx: number, cy: number, radius: number, angle: number) =>
  `${(cx + radius * Math.sin(angle)).toFixed(3)},${(cy - radius * Math.cos(angle)).toFixed(3)}`;

/** The SVG path of a slice, or an empty one for a slice with no room. */
export function arcPath(cx: number, cy: number, radius: number, arc: PieArc): string {
  if (arc.share <= 0) return '';
  // A lone slice is a whole disc, which one arc can't draw.
  if (arc.share >= 1 - 1e-9) {
    return `M${point(cx, cy, radius, 0)}A${radius},${radius} 0 1 1 ${point(cx, cy, radius, Math.PI)}A${radius},${radius} 0 1 1 ${point(cx, cy, radius, 0)}Z`;
  }
  const large = arc.end - arc.start > Math.PI ? 1 : 0;
  return `M${cx},${cy}L${point(cx, cy, radius, arc.start)}A${radius},${radius} 0 ${large} 1 ${point(cx, cy, radius, arc.end)}Z`;
}

/** Where a slice's mark sits: on its middle angle, at `fraction` of the radius. */
export function arcCentre(cx: number, cy: number, radius: number, arc: PieArc, fraction = 0.62): { x: number; y: number } {
  const angle = (arc.start + arc.end) / 2;
  return { x: cx + radius * fraction * Math.sin(angle), y: cy - radius * fraction * Math.cos(angle) };
}
