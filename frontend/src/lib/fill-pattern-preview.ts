import { FILL_PATTERN_IDS } from '@/components/builder/layer-adapters/fill-pattern-images';

/**
 * CSS-only previews for the built-in fill patterns, shared by every surface that
 * has to show "this polygon is patterned": the builder's FillPatternPicker, the
 * legend chip (builder + viewer), and the layer-list swatch.
 *
 * It lives here rather than in FillPatternPicker so the legend and layer icons
 * can reach it without importing a builder panel component.
 *
 * Gradients use `currentColor`: a consumer sets `color` and the pattern follows.
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
 * The paint value, when it names a built-in pattern we can preview. An imported
 * or API-authored layer may carry any sprite id in `fill-pattern`;
 * patternPreviewStyle returns no CSS for those, and a consumer taking the
 * patterned branch anyway would draw an empty outlined chip instead of the solid colour.
 */
export function fillPatternFromPaint(paint: Record<string, unknown> | undefined): string | undefined {
  const value = paint?.['fill-pattern'];
  return typeof value === 'string' && (FILL_PATTERN_IDS as readonly string[]).includes(value)
    ? value
    : undefined;
}

/**
 * The colour a built-in fill pattern draws in: the layer's own fill colour,
 * wherever it lives.
 *
 * A pattern deletes `fill-color` from paint, so for a layer patterned through the
 * picker the colour is in the `fillColorSaved` stash. `paint` still wins when it
 * holds a string (maps saved by older clients carry both keys). Returns undefined
 * when there is nothing to tint with, and consumers fall back to the fixed grey.
 *
 * The map adapter and the preview surfaces all resolve the tint through this one
 * function so they cannot disagree with the map.
 */
export function fillPatternTint(
  paint: Record<string, unknown> | undefined,
  builder: { fillColorSaved?: string } | undefined,
): string | undefined {
  const painted = paint?.['fill-color'];
  if (typeof painted === 'string') return painted;
  // The stash is typed string but comes from an open `style_config`, so an
  // API-authored or imported layer can hold a number or object; the pattern
  // lookup throws on non-strings while the layer is described.
  return typeof builder?.fillColorSaved === 'string' ? builder.fillColorSaved : undefined;
}
