/**
 * feat(#1486): attribution for the images the builder renders.
 *
 * Every image this product produces — the PNG export, the 400x250 thumbnail,
 * the 1200x630 OG card — is distributed outside the application while showing
 * basemap tiles whose licence requires visible credit, and (since #1477)
 * dataset tiles whose source terms may require it too. None of them carried a
 * credit line before this module existed.
 *
 * The trap this module exists to avoid: all three capture paths composite from
 * `map.getCanvas()`, a flat WebGL fill. MapLibre's own attribution control is a
 * DOM overlay, so it is invisible to every one of them by construction. A
 * credit only reaches an exported image if it is DRAWN INTO the canvas, which
 * is what the two draw helpers here do.
 *
 * Where the text comes from: MapLibre's rendered control, read as text.
 *
 * The obvious alternative — composing `BasemapEntry.attribution` with
 * `collectLayerAttributions` — is wrong for the builder in three ways:
 *
 *  1. `toMaplibreStyle` (lib/basemap-utils.ts) only threads `attribution` onto
 *     the source for XYZ tile URLs. A `/styles/` or `.json` basemap URL is
 *     returned unchanged and MapLibre reads the remote style's own per-source
 *     attribution, so the stored field is never what the screen shows. Most
 *     shipped presets are style URLs. Composing from the field would put a
 *     string in the PNG that differs from the one on screen.
 *  2. `collectLayerAttributions` returns HTML-ESCAPED strings (they are bound
 *     for `innerHTML`; see lib/attribution-safety.ts). Canvas `fillText` draws
 *     literally, so "Rand & McNally" would export as "Rand &amp; McNally".
 *  3. It is keyed on the viewer's `visibleLayers` set, which the builder
 *     deliberately does not maintain — `map-sync.ts` feeds dataset credits
 *     through MapLibre's native source-level `attribution` and lets MapLibre
 *     gate them on the live `used` flag.
 *
 * Reading the control gets the same merge, the same dedupe and the same live
 * gating as the screen by construction rather than by convention, and
 * `textContent` is post-parse so entities and anchors are already resolved.
 */
import { MAP_COLORS } from '@/lib/map-colors';

/** The separator MapLibre's AttributionControl joins entries with. */
const SEPARATOR = ' | ';
const ELLIPSIS = '…';
const FONT_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

/** Only the two methods this module needs, so tests can pass a plain object
 *  and so a partial map mock (the shape the builder suites already use) is a
 *  valid argument rather than a cast. */
export interface AttributionMapLike {
  getContainer?: () => HTMLElement | null | undefined;
  getStyle?: () => unknown;
}

function attributionFont(fontPx: number): string {
  return `400 ${fontPx}px ${FONT_STACK}`;
}

/** Decode HTML entities in an editor-supplied credit without ever parsing it
 *  as live markup. DOMParser documents are inert — no script runs, no image or
 *  iframe is fetched — which `el.innerHTML = s` cannot promise. */
function decodeHtmlText(raw: string): string {
  try {
    return (
      new DOMParser().parseFromString(raw, 'text/html').body.textContent ?? ''
    ).trim();
  } catch {
    return raw.trim();
  }
}

function dedupe(entries: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of entries) {
    const trimmed = entry.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed);
  }
  return out;
}

/**
 * The credit entries currently shown for `map`, as plain text.
 *
 * Tiered, because coupling to a library CSS class is a real risk:
 *
 *  1. `.maplibregl-ctrl-attrib-inner` textContent, split on MapLibre's own
 *     separator. Exact agreement with the screen.
 *  2. The union of `getStyle().sources[*].attribution`, entity-decoded. A
 *     degraded mode rather than a cliff: it loses only the `used` gating, so
 *     it may credit a source whose layers are all hidden. Over-crediting is
 *     the safe direction.
 *  3. Nothing, with a DEV warning.
 */
export function readRenderedAttribution(map: AttributionMapLike): string[] {
  const inner = map.getContainer?.()?.querySelector?.(
    '.maplibregl-ctrl-attrib-inner',
  );
  const rendered = inner?.textContent?.trim();
  if (rendered) return dedupe(rendered.split(SEPARATOR));

  const style = map.getStyle?.() as
    | { sources?: Record<string, { attribution?: string | null } | null> }
    | null
    | undefined;
  const sources = style?.sources;
  if (sources) {
    const fromSources: string[] = [];
    for (const spec of Object.values(sources)) {
      const raw = spec?.attribution;
      if (typeof raw !== 'string' || !raw.trim()) continue;
      const decoded = decodeHtmlText(raw);
      if (decoded) fromSources.push(decoded);
    }
    const deduped = dedupe(fromSources);
    if (deduped.length > 0) return deduped;
  }

  if (import.meta.env.DEV) {
    console.warn(
      '[attribution] no credit line available for this render; the exported image will carry none',
    );
  }
  return [];
}

/** Descending integer font sizes, `from` down to `to`. Bounded by
 *  construction: the fitter must never drive a shrink loop off `measureText`,
 *  or a font that fails to load hangs the export. */
function fontLadder(from: number, to: number): number[] {
  const top = Math.max(1, Math.round(from));
  const bottom = Math.max(1, Math.min(Math.round(to), top));
  const sizes: number[] = [];
  for (let px = top; px >= bottom; px--) sizes.push(px);
  return sizes;
}

/** Greedy wrap on entry boundaries. Returns null when any single entry is
 *  wider than `maxWidth` — the caller decides whether to shrink or elide. */
function wrapEntries(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  maxWidth: number,
): string[] | null {
  const lines: string[] = [];
  let current = '';
  for (const entry of entries) {
    if (ctx.measureText(entry).width > maxWidth) return null;
    if (!current) {
      current = entry;
      continue;
    }
    const candidate = current + SEPARATOR + entry;
    if (ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
    } else {
      lines.push(current);
      current = entry;
    }
  }
  if (current) lines.push(current);
  return lines;
}

/** Character-level truncation, reserved for a single entry too long for the
 *  smallest size. Binary search, so the number of `measureText` calls is
 *  logarithmic in the string length and always terminates. */
function truncateToWidth(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (ctx.measureText(text.slice(0, mid) + ELLIPSIS).width <= maxWidth) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return lo > 0 ? text.slice(0, lo) + ELLIPSIS : ELLIPSIS;
}

export interface FitAttributionOptions {
  maxWidth: number;
  fontPx: number;
  minFontPx: number;
  maxLines: number;
}

export interface FittedAttribution {
  lines: string[];
  fontPx: number;
  elided: boolean;
}

/**
 * Fit `entries` into at most `maxLines` lines of at most `maxWidth`.
 *
 * Overflow is resolved at ENTRY boundaries, never mid-name: "© OpenFreeMap |
 * …" credits everything it names correctly, while "© OpenFreeMap, ©
 * OpenMapTil…" mangles a provider's name, which is worse than showing fewer.
 *
 * Leaves `ctx.font` set to the size it chose.
 */
export function fitAttributionText(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  opts: FitAttributionOptions,
): FittedAttribution {
  const clean = dedupe(entries);
  if (clean.length === 0 || opts.maxWidth <= 0) {
    return { lines: [], fontPx: opts.fontPx, elided: false };
  }
  const maxLines = Math.max(1, opts.maxLines);

  for (const fontPx of fontLadder(opts.fontPx, opts.minFontPx)) {
    ctx.font = attributionFont(fontPx);
    const lines = wrapEntries(ctx, clean, opts.maxWidth);
    if (lines && lines.length <= maxLines) {
      return { lines, fontPx, elided: false };
    }
  }

  // Nothing fits whole. Drop whole entries from the end at the smallest size,
  // marking the loss with a trailing ellipsis entry.
  const fontPx = Math.max(1, Math.min(Math.round(opts.minFontPx), Math.round(opts.fontPx)));
  ctx.font = attributionFont(fontPx);
  for (let keep = clean.length - 1; keep >= 1; keep--) {
    const lines = wrapEntries(ctx, [...clean.slice(0, keep), ELLIPSIS], opts.maxWidth);
    if (lines && lines.length <= maxLines) {
      return { lines, fontPx, elided: true };
    }
  }

  return {
    lines: [truncateToWidth(ctx, clean[0], opts.maxWidth)],
    fontPx,
    elided: true,
  };
}

/* ── Overlay: the two fixed-size crops ─────────────────────────────────── */

export interface AttributionOverlaySpec {
  fontPx: number;
  minFontPx: number;
  /** Distance from the canvas edge to the scrim. */
  inset: number;
  paddingX: number;
  paddingY: number;
  radius: number;
}

/** 400x250. 10px over a scrim reads fine at 1:1; the gallery renders it into
 *  176x112 with object-cover, which is a display-size decision and not an
 *  argument about what the file should contain. It has to carry the credit
 *  because `get_share_card_image_url` falls back to the thumbnail as the
 *  og:image for every map captured before SHARE-08 — that surface has no
 *  adjacent text at all. */
export const THUMBNAIL_ATTRIBUTION: AttributionOverlaySpec = {
  fontPx: 10,
  minFontPx: 9,
  inset: 6,
  paddingX: 5,
  paddingY: 3,
  radius: 3,
};

/** 1200x630. An overlay rather than a band: the whole frame is the map, and
 *  adding a band would change the 1.91:1 ratio social platforms crop against. */
export const OG_ATTRIBUTION: AttributionOverlaySpec = {
  fontPx: 16,
  minFontPx: 13,
  inset: 12,
  paddingX: 8,
  paddingY: 5,
  radius: 4,
};

/** Rounded scrim, falling back to a square fill where `roundRect` is absent
 *  (older engines, and the 2D-context stubs the hook tests use). */
function fillScrim(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  radius: number,
): void {
  const roundRect = (
    ctx as CanvasRenderingContext2D & {
      roundRect?: (x: number, y: number, w: number, h: number, r: number) => void;
    }
  ).roundRect;
  if (
    typeof roundRect === 'function' &&
    typeof ctx.beginPath === 'function' &&
    typeof ctx.fill === 'function'
  ) {
    ctx.beginPath();
    roundRect.call(ctx, x, y, w, h, radius);
    ctx.fill();
    return;
  }
  ctx.fillRect(x, y, w, h);
}

/**
 * Draw the credit into the bottom-right of an already-composited crop.
 *
 * A light scrim with dark text, not a glyph halo: stroking at 9-10px roughly
 * doubles apparent weight, and the thumbnail is a JPEG — halo plus chroma
 * subsampling is exactly where small text turns to mush. One fixed pair works
 * over both light and dark tiles because the scrim establishes its own ground,
 * which also covers the globe case (#1479), where the bottom-right may be
 * space rather than tiles.
 *
 * Returns whether anything was drawn.
 */
export function drawAttributionOverlay(
  canvas: HTMLCanvasElement,
  entries: string[],
  spec: AttributionOverlaySpec,
): boolean {
  if (entries.length === 0) return false;
  const ctx = canvas.getContext('2d');
  if (!ctx) return false;

  const maxWidth = canvas.width - spec.inset * 2 - spec.paddingX * 2;
  const fitted = fitAttributionText(ctx, entries, {
    maxWidth,
    fontPx: spec.fontPx,
    minFontPx: spec.minFontPx,
    maxLines: 1,
  });
  const line = fitted.lines[0];
  if (!line) return false;

  ctx.font = attributionFont(fitted.fontPx);
  const textWidth = ctx.measureText(line).width;
  const boxW = textWidth + spec.paddingX * 2;
  const boxH = fitted.fontPx + spec.paddingY * 2;
  const boxX = Math.max(0, canvas.width - spec.inset - boxW);
  const boxY = Math.max(0, canvas.height - spec.inset - boxH);

  ctx.fillStyle = MAP_COLORS.exportImage.attributionScrim;
  fillScrim(ctx, boxX, boxY, boxW, boxH, spec.radius);

  ctx.fillStyle = MAP_COLORS.exportImage.text;
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  ctx.fillText(line, boxX + spec.paddingX, boxY + spec.paddingY);
  return true;
}

/* ── Band: the full-resolution PNG export ──────────────────────────────── */

/** Unscaled band metrics; every one is multiplied by `dpr` at use, because
 *  `handleExportPNG` works entirely in srcCanvas pixel space. */
const BAND_FONT_PX = 12;
const BAND_MIN_FONT_PX = 10;
const BAND_MAX_LINES = 2;
const BAND_LINE_HEIGHT = 16;
const BAND_GAP = 12;

export interface MeasuredAttributionBand {
  lines: string[];
  /** Already dpr-scaled: the caller draws with it directly. */
  fontPx: number;
  /** Already dpr-scaled: the caller adds it into the canvas height. */
  height: number;
}

/**
 * Measure the export's attribution band before the canvas is sized.
 *
 * Its own band rather than a share of the branding footer row: sharing would
 * need horizontal collision math against the measured branding width, and the
 * enterprise case (`showBranding === false`) would need a special case. A
 * separate band makes that path fall out for free — the attribution band
 * renders and the branding band does not. It also sits on white rather than on
 * imagery, so it needs no scrim, which matters most for the path most likely
 * to be printed or pasted into a report.
 *
 * Wraps to two lines rather than eliding: the full-resolution export has the
 * room, and it is the one output that should never drop a credit.
 */
export function measureAttributionBand(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  opts: { maxWidth: number; dpr: number },
): MeasuredAttributionBand {
  const dpr = opts.dpr || 1;
  const fallback = { lines: [], fontPx: BAND_FONT_PX * dpr, height: 0 };
  if (entries.length === 0 || opts.maxWidth <= 0) return fallback;

  const fitted = fitAttributionText(ctx, entries, {
    maxWidth: opts.maxWidth,
    fontPx: BAND_FONT_PX * dpr,
    minFontPx: BAND_MIN_FONT_PX * dpr,
    maxLines: BAND_MAX_LINES,
  });
  if (fitted.lines.length === 0) return fallback;

  return {
    lines: fitted.lines,
    fontPx: fitted.fontPx,
    height: Math.round(
      BAND_GAP * dpr + fitted.lines.length * BAND_LINE_HEIGHT * dpr + BAND_GAP * dpr,
    ),
  };
}

/**
 * Draw a measured band with its top-left at (`x`, `y`).
 *
 * `mutedText` (#666666, ~5.7:1 on white) rather than the #999999 the branding
 * footer uses (~2.8:1) — a legally required line is not somewhere to reuse a
 * decorative contrast.
 */
export function drawAttributionBand(
  ctx: CanvasRenderingContext2D,
  measured: MeasuredAttributionBand,
  opts: { x: number; y: number; dpr: number },
): void {
  if (measured.lines.length === 0) return;
  const dpr = opts.dpr || 1;
  ctx.fillStyle = MAP_COLORS.exportImage.mutedText;
  ctx.font = attributionFont(measured.fontPx);
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  let lineY = opts.y + BAND_GAP * dpr;
  for (const line of measured.lines) {
    ctx.fillText(line, opts.x, lineY);
    lineY += BAND_LINE_HEIGHT * dpr;
  }
}
