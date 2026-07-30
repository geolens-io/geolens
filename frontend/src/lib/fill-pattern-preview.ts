import { FILL_PATTERN_IDS } from '@/components/builder/layer-adapters/fill-pattern-images';

/**
 * CSS-only previews for the built-in fill patterns, shared by every surface that
 * has to show "this polygon is patterned": the builder's FillPatternPicker, the
 * legend chip (builder + viewer), and the layer-list swatch.
 *
 * fix(#951): this lived inside FillPatternPicker, so the legend and the layer
 * icons had no way to reach it without importing a builder panel component.
 *
 * Gradients use `currentColor`, so a consumer sets `color` to whatever the chip
 * should draw in and the pattern follows.
 */
export function patternPreviewStyle(id: string): React.CSSProperties {
  switch (id) {
    case 'geolens-fill-hatch':
      return {
        backgroundImage: 'repeating-linear-gradient(0deg, currentColor 0px, currentColor 1px, transparent 1px, transparent 4px)',
        backgroundSize: '4px 4px',
      };
    case 'geolens-fill-crosshatch':
      return {
        backgroundImage: `
          repeating-linear-gradient(45deg, currentColor 0px, currentColor 1px, transparent 1px, transparent 4px),
          repeating-linear-gradient(-45deg, currentColor 0px, currentColor 1px, transparent 1px, transparent 4px)
        `,
        backgroundSize: '5.66px 5.66px',
      };
    case 'geolens-fill-diagonal':
      return {
        backgroundImage: 'repeating-linear-gradient(45deg, currentColor 0px, currentColor 1px, transparent 1px, transparent 4px)',
        backgroundSize: '5.66px 5.66px',
      };
    case 'geolens-fill-dots':
      return {
        backgroundImage: 'radial-gradient(circle, currentColor 1px, transparent 1px)',
        backgroundSize: '4px 4px',
      };
    case 'geolens-fill-grid':
      return {
        backgroundImage: `
          repeating-linear-gradient(0deg, currentColor 0px, currentColor 1px, transparent 1px, transparent 4px),
          repeating-linear-gradient(90deg, currentColor 0px, currentColor 1px, transparent 1px, transparent 4px)
        `,
        backgroundSize: '4px 4px',
      };
    default:
      return {};
  }
}

/**
 * The paint value, when it names a BUILT-IN pattern we can actually preview.
 *
 * An imported or API-authored layer may carry any sprite id in `fill-pattern`;
 * patternPreviewStyle returns no CSS for those, and a consumer that took the
 * patterned branch anyway would draw an empty outlined chip instead of falling
 * back to the solid colour.
 */
export function fillPatternFromPaint(paint: Record<string, unknown> | undefined): string | undefined {
  const value = paint?.['fill-pattern'];
  return typeof value === 'string' && (FILL_PATTERN_IDS as readonly string[]).includes(value)
    ? value
    : undefined;
}
