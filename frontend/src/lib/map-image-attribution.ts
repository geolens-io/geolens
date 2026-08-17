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
 * Where the text comes from: the style's own per-source `attribution` values,
 * as a LIST. See `readRenderedAttribution` for why a list rather than the
 * rendered control's joined string (fix(#1541 codex P2): ` | ` is legal content
 * inside a credit, so splitting the joined line cut credits in half and let the
 * dedupe delete them).
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
 * Reading the live style keeps the image and the screen agreeing on WHICH
 * credits exist, by construction rather than by convention, and the HTML in
 * those values is decoded through an inert DOMParser rather than a regex.
 */
import { MAP_COLORS } from '@/lib/map-colors';
// Canvas drawing happens outside React, so the overflow marker is translated
// through the i18n singleton. Same pattern as api/client.ts's error strings.
import i18n from '@/i18n/i18n';

/** The separator MapLibre's AttributionControl joins entries with. */
const SEPARATOR = ' | ';
const FONT_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

/** Only the two methods this module needs, so tests can pass a plain object
 *  and so a partial map mock (the shape the builder suites already use) is a
 *  valid argument rather than a cast. */
export interface AttributionMapLike {
  getContainer?: () => HTMLElement | null | undefined;
  getStyle?: () => unknown;
  /** Live source objects. Their `attribution` is the RESOLVED value; the
   *  serialized style's is not. See `readRenderedAttribution`. */
  getSource?: (id: string) => { attribution?: string | null } | null | undefined;
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
 * The credit entries currently shown for `map`, as plain text, AS A LIST.
 *
 * fix(#1541 codex P2): this used to read MapLibre's rendered control and split
 * the joined text on ` | `. That re-derived structure from a rendered string,
 * and the delimiter is legal content — the backend accepts it anywhere in a
 * 5,000-character credit. A credit reading `© Acme | © Acme` split into two
 * identical fragments, which the dedupe then collapsed into one, silently
 * deleting half a real credit; and the overflow marker counted fragments rather
 * than credits, so its "+N" could be wrong in either direction while a single
 * licensing statement was cut in half and its remainder counted as a separate
 * provider. No smarter delimiter fixes that. Any delimiter can appear in
 * content, so the round-trip itself had to go.
 *
 * Ordered by whether the source is STRUCTURED, not by how close it is to the
 * screen:
 *
 *  1. The live sources' own `attribution`, one entry per source, entity-decoded
 *     and never split on anything. This is the only place the individual
 *     credits exist as separate values, so it is the only honest input to a
 *     per-credit count. Read from `getSource(id)` rather than from
 *     `getStyle().sources[id]`: MEASURED on the shipped OpenFreeMap basemap,
 *     the serialized spec reports `attribution: null` while the live source
 *     carries the OpenMapTiles and OpenStreetMap credits, because a vector
 *     source loaded from a TileJSON `url` receives them in that response and
 *     `getStyle()` serializes the spec as authored. Reading the spec alone
 *     dropped every basemap credit whenever a dataset declared one.
 *  2. `.maplibregl-ctrl-attrib-inner` textContent as ONE opaque entry. This
 *     path genuinely only has the joined string, so it does not guess: the
 *     whole line is treated as a single credit rather than split back apart.
 *     It renders identically; only the marker's granularity is coarser, and
 *     only on a map whose sources declare nothing.
 *  3. Nothing, with a DEV warning.
 *
 * Two costs of preferring (1), both accepted:
 *
 *  - The `used` gating. MapLibre hides a source whose layers are all hidden and
 *    the source list does not, so the image may credit a source the screen does
 *    not. Over-crediting is the safe direction.
 *  - MapLibre's own "MapLibre" self-credit does not reach the image. It is a
 *    control default rather than a source, so no structured list contains it,
 *    and it was DECIDED on #1541 review that it should stay out rather than be
 *    hardcoded back in: MapLibre GL JS is BSD-3-Clause, which requires its
 *    notice in source and binary distributions, not in rendered output, so no
 *    licence obligation turns on its presence in an exported PNG. Putting it
 *    back would mean reintroducing the hardcoded vendor string this module
 *    exists to remove, to satisfy an obligation that does not exist. The
 *    interactive map still shows it — the control default is untouched.
 *
 * Both are the price of a credit list that cannot be mangled by its own
 * content, which is the property the whole marker count rests on.
 */
export function readRenderedAttribution(map: AttributionMapLike): string[] {
  const style = map.getStyle?.() as
    | { sources?: Record<string, { attribution?: string | null } | null> }
    | null
    | undefined;
  const sources = style?.sources;
  if (sources) {
    const fromSources: string[] = [];
    for (const id of Object.keys(sources)) {
      // The LIVE source first: a vector source loaded from a TileJSON `url`
      // receives its attribution in that response, and `getStyle()` serializes
      // the spec as authored, so the basemap's credit is null there and
      // present here. Measured on the shipped OpenFreeMap basemap, where the
      // spec says null and the live source carries the OpenMapTiles and
      // OpenStreetMap credits. The serialized value is the fallback for a
      // source the map has not instantiated.
      const live = map.getSource?.(id)?.attribution;
      const raw = typeof live === 'string' && live.trim() ? live : sources[id]?.attribution;
      if (typeof raw !== 'string' || !raw.trim()) continue;
      const decoded = decodeHtmlText(raw);
      if (decoded) fromSources.push(decoded);
    }
    const deduped = dedupe(fromSources);
    if (deduped.length > 0) return deduped;
  }

  const inner = map.getContainer?.()?.querySelector?.(
    '.maplibregl-ctrl-attrib-inner',
  );
  const rendered = inner?.textContent?.trim();
  // Deliberately NOT split. See the docstring: the separator is legal content.
  if (rendered) return [rendered];

  if (import.meta.env.DEV) {
    console.warn(
      '[attribution] no credit line available for this render; the exported image will carry none',
    );
  }
  return [];
}

/* ── Layout ────────────────────────────────────────────────────────────────
 *
 * NO OUTPUT EVER DROPS A CREDIT, and none shrinks below its documented size.
 *
 * fix(#1541 codex P1 x2): both halves of this module used to elide. The export
 * band passed a two-line budget while its docstring promised the opposite, and
 * the two crops passed `maxLines: 1`. Measured on a real export: five credits
 * on a 1056px canvas lost two of them, the basemap's included, replaced by "…".
 * An ellipsis credits nobody, and a truncated line is a worse artifact than a
 * missing one because it reads as a complete statement of provenance.
 *
 * The fix is that the elision path no longer exists, rather than being gated
 * behind a flag some future caller can re-enable. Text wraps to as many lines
 * as it needs; the export canvas grows, and the two fixed-size crops spend map
 * pixels instead of provider names. The image is fixed, the band inside it is
 * not.
 *
 * Legibility floor, with numbers. Every output renders at ONE documented size
 * and never below it:
 *
 *   PNG export   12px on white         (no scrim needed, not over imagery)
 *   OG card      16px over a scrim     (1200x630 JPEG, quality 0.85)
 *   Thumbnail    10px over a scrim     (400x250 JPEG, quality 0.7)
 *
 * 10px is the floor of the three. There is deliberately no shrink ladder:
 * shrinking traded legibility for area, and now that spending area is allowed
 * the trade is the wrong way round — 10px over a scrim is legible at 1:1, 9px
 * under JPEG chroma subsampling is where small text starts to mush. The gallery
 * displays the thumbnail at 176x112, but that is a display-size decision and
 * not an argument about the file.
 *
 * How much of each image the band can eat, and where it runs out. The line
 * counts, percentages and ceilings below are asserted in
 * lib/__tests__/map-image-attribution.test.ts rather than left as prose claims;
 * `overlayLineCapacity` computes the ceiling column. The chars/line column is
 * the only estimate, since real glyph widths are font-dependent.
 *
 *               line    usable    chars/   real 5-credit    ceiling
 *               height  width     line     load             (band fills frame)
 *   Thumbnail   13px    378px     ~75      6 lines, 33.6%   18 lines, ~1350 chars
 *   OG card     20px    1160px    ~145     4 lines, 14.3%   30 lines, ~4350 chars
 *   PNG export  16px    1016px*   ~169     4 lines, 88px    none — canvas grows
 *
 *   * the measured 1056px-wide export at dpr 1, less 20px of pad a side.
 *
 * The export has no ceiling at all: its canvas is sized AFTER the band is
 * measured, so the band's height is an input to the image rather than a budget
 * inside it. Only the two crops have one, and it is where the scrim reaches the
 * top edge — the band has by then eaten every map pixel there is.
 *
 * That ceiling is ~3.3x the measured real-world credit load for the thumbnail
 * (411 characters across five providers) and ~10x for the OG card. But the
 * SUPPORTED input is far larger: `attribution` is `max_length=5000` on the
 * dataset schema and `NonEmptyString5000` on the manifest, and 5,000 characters
 * is roughly 77 lines in a 250px-tall thumbnail. No font size anyone would call
 * legible renders that, so at the contract's maximum something must give.
 *
 * What gives is neither the frame nor silence. Past the ceiling the overlay
 * renders the credits that fit and appends a visible, counted marker naming how
 * many did not (`export.moreCredits`), with the marker itself charged against
 * the line budget. The standard is that no output may SILENTLY drop a credit; a
 * marker inside the frame is not silent, and it stops the visible list reading
 * as a complete statement of provenance. Nothing is ever drawn outside the
 * canvas — an earlier revision kept calling `fillText` below the frame, which
 * painted credits into nowhere.
 *
 * The one residual limit within the ceiling: a single credit longer than a full
 * line wraps MID-STRING, on word boundaries, and on characters for a word that
 * still does not fit. That splits a provider's name across lines, which is
 * legible and complete. It never truncates one.
 */

/** Greedy wrap on entry boundaries, so a provider's name stays on one line.
 *  Returns null when a single entry is wider than `maxWidth`, which is the one
 *  case entry-boundary wrapping cannot resolve on its own. */
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

/**
 * Split `text` into user-perceived characters.
 *
 * fix(#1541 codex P2): the wrapper used to index and `slice()` by UTF-16 code
 * unit, which splits a surrogate pair down the middle and renders two
 * replacement glyphs instead of the provider's name. Mid-STRING wrapping is the
 * one residual limit we allow; mid-CHARACTER is just truncation wearing a
 * disguise.
 *
 * `Intl.Segmenter` because it is the only option that also keeps combining
 * marks and ZWJ emoji sequences intact — `Array.from` iterates code POINTS,
 * which fixes surrogate pairs but still severs a base character from its
 * accent. It is kept as the fallback only for an engine without `Segmenter`,
 * where it is strictly better than code units.
 */
let graphemeSegmenter: Intl.Segmenter | null | undefined;

function toGraphemes(text: string): string[] {
  if (graphemeSegmenter === undefined) {
    graphemeSegmenter =
      typeof Intl !== 'undefined' && typeof Intl.Segmenter === 'function'
        ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
        : null;
  }
  if (!graphemeSegmenter) return Array.from(text);
  return Array.from(graphemeSegmenter.segment(text), (s) => s.segment);
}

/** Break a word wider than `maxWidth` into pieces that are not. Loses nothing:
 *  the pieces continue on the following lines. Binary search per piece over
 *  GRAPHEME CLUSTERS, and each piece takes at least one cluster, so it always
 *  terminates and never splits a character. */
function breakLongWord(
  ctx: CanvasRenderingContext2D,
  word: string,
  maxWidth: number,
): string[] {
  if (ctx.measureText(word).width <= maxWidth) return [word];
  const cells = toGraphemes(word);
  const pieces: string[] = [];
  let start = 0;
  while (start < cells.length) {
    // Largest end index whose slice still fits, but never fewer than one
    // cluster — that lower bound is what guarantees progress.
    let lo = start + 1;
    let hi = cells.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (ctx.measureText(cells.slice(start, mid).join('')).width <= maxWidth) lo = mid;
      else hi = mid - 1;
    }
    pieces.push(cells.slice(start, lo).join(''));
    start = lo;
  }
  return pieces;
}

/** Greedy word wrap that never drops a character. The fallback for a single
 *  credit too long to fit a line whole. */
function wrapWords(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string[] {
  const lines: string[] = [];
  let current = '';
  for (const word of text.split(' ').filter(Boolean)) {
    const candidate = current ? `${current} ${word}` : word;
    if (!current || ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
    if (ctx.measureText(current).width > maxWidth) {
      const pieces = breakLongWord(ctx, current, maxWidth);
      lines.push(...pieces.slice(0, -1));
      current = pieces[pieces.length - 1] ?? '';
    }
  }
  if (current) lines.push(current);
  return lines;
}

export interface FitAttributionOptions {
  maxWidth: number;
  fontPx: number;
}

export interface FittedAttribution {
  lines: string[];
  fontPx: number;
}

/**
 * Lay `entries` out at `fontPx`, wrapping to as many lines as they need.
 *
 * Total by construction: the returned lines always contain every character of
 * every entry. There is no code path that drops one, which is the property the
 * whole module exists to hold. Leaves `ctx.font` set.
 */
export function fitAttributionText(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  opts: FitAttributionOptions,
): FittedAttribution {
  const clean = dedupe(entries);
  if (clean.length === 0 || !(opts.maxWidth > 0)) {
    return { lines: [], fontPx: opts.fontPx };
  }
  ctx.font = attributionFont(opts.fontPx);
  const byEntry = wrapEntries(ctx, clean, opts.maxWidth);
  if (byEntry) return { lines: byEntry, fontPx: opts.fontPx };
  return {
    lines: wrapWords(ctx, clean.join(SEPARATOR), opts.maxWidth),
    fontPx: opts.fontPx,
  };
}

/* ── Overlay: the two fixed-size crops ─────────────────────────────────── */

export interface AttributionOverlaySpec {
  fontPx: number;
  /** Baseline-to-baseline step for a wrapped credit. */
  lineHeight: number;
  /** Distance from the canvas edge to the scrim. */
  inset: number;
  paddingX: number;
  paddingY: number;
  radius: number;
}

/** 400x250. It has to carry the credit because `get_share_card_image_url`
 *  falls back to the thumbnail as the og:image for every map captured before
 *  SHARE-08 — that surface has no adjacent text at all. */
export const THUMBNAIL_ATTRIBUTION: AttributionOverlaySpec = {
  fontPx: 10,
  lineHeight: 13,
  inset: 6,
  paddingX: 5,
  paddingY: 3,
  radius: 3,
};

/** 1200x630. An overlay rather than a band: the whole frame is the map, and
 *  adding a band would change the 1.91:1 ratio social platforms crop against. */
export const OG_ATTRIBUTION: AttributionOverlaySpec = {
  fontPx: 16,
  lineHeight: 20,
  inset: 12,
  paddingX: 8,
  paddingY: 5,
  radius: 4,
};

/**
 * How many lines of `spec` a `canvasHeight`-tall frame can hold before the
 * scrim reaches the top edge and the band has eaten every map pixel there is.
 *
 * The crops' only real ceiling, and the number the module's legibility floor is
 * documented against. The export band has no equivalent: its canvas is sized
 * after the band is measured, so there is nothing for it to run out of.
 */
export function overlayLineCapacity(
  spec: AttributionOverlaySpec,
  canvasHeight: number,
): number {
  const usable = canvasHeight - spec.inset - spec.paddingY * 2;
  return Math.max(0, Math.floor(usable / spec.lineHeight));
}

/**
 * The largest number of LEADING entries whose wrapped form fits `maxLines`,
 * with the lines it produced.
 *
 * Binary search rather than a scan: line count is monotonic non-decreasing in
 * the entry count, and the supported input is 5,000 characters per credit, so
 * a linear probe would re-wrap a very large string once per entry.
 */
function fitEntryPrefix(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  maxWidth: number,
  maxLines: number,
): { lines: string[]; count: number } {
  if (maxLines <= 0) return { lines: [], count: 0 };
  const wrapFirst = (count: number): string[] => {
    if (count === 0) return [];
    const slice = entries.slice(0, count);
    return wrapEntries(ctx, slice, maxWidth) ?? wrapWords(ctx, slice.join(SEPARATOR), maxWidth);
  };
  let best: { lines: string[]; count: number } = { lines: [], count: 0 };
  let lo = 0;
  let hi = entries.length;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const lines = wrapFirst(mid);
    if (lines.length <= maxLines) {
      best = { lines, count: mid };
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

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
 * Draw the credit into the bottom-right of an already-composited crop, over as
 * many lines as it takes.
 *
 * A light scrim with dark text, not a glyph halo: stroking at 10px roughly
 * doubles apparent weight, and these are JPEGs — halo plus chroma subsampling
 * is exactly where small text turns to mush. One fixed pair works over both
 * light and dark tiles because the scrim establishes its own ground, which also
 * covers the globe case (#1479), where the bottom-right may be space rather
 * than tiles.
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
  const capacity = overlayLineCapacity(spec, canvas.height);
  // Nowhere legible to put even one line. Drawing anyway would paint outside
  // the frame, which is the one thing this function must never do.
  if (maxWidth <= 0 || capacity < 1) return false;

  // Deduped here as well as inside the fitter, because the overflow marker
  // counts CREDITS and must not count the same one twice.
  const credits = dedupe(entries);
  const fitted = fitAttributionText(ctx, credits, { maxWidth, fontPx: spec.fontPx });
  if (fitted.lines.length === 0) return false;

  // fix(#1541 codex P1 round 2): removing the fitter's elision left one way to
  // lose a credit — `boxY` clamps at 0, so a band taller than the frame kept
  // calling fillText below the canvas and painted into nowhere. A DEV warning
  // did not cover it: production is exactly where it mattered.
  //
  // The supported input is 5,000 characters per credit (dataset schemas.py and
  // manifest_schemas.py), which is ~77 lines in a 250px-tall thumbnail. No font
  // size anyone would call legible renders that, so something must give and it
  // is not the frame. Render what fits and say what did not, inside the frame,
  // with the marker itself counted against the line budget. Not silent, and
  // never a claim that the visible credits are the whole set.
  let lines = fitted.lines;
  let omitted = 0;
  if (fitted.lines.length > capacity) {
    const kept = fitEntryPrefix(ctx, credits, maxWidth, capacity - 1);
    omitted = credits.length - kept.count;
    lines = [...kept.lines, i18n.t('builder:export.moreCredits', { count: omitted })];
  }

  ctx.font = attributionFont(fitted.fontPx);
  const textWidth = lines.reduce(
    (widest, line) => Math.max(widest, ctx.measureText(line).width),
    0,
  );
  const boxW = textWidth + spec.paddingX * 2;
  const boxH = lines.length * spec.lineHeight + spec.paddingY * 2;
  const boxX = Math.max(0, canvas.width - spec.inset - boxW);
  const boxY = Math.max(0, canvas.height - spec.inset - boxH);

  ctx.fillStyle = MAP_COLORS.exportImage.attributionScrim;
  fillScrim(ctx, boxX, boxY, boxW, boxH, spec.radius);

  ctx.fillStyle = MAP_COLORS.exportImage.text;
  ctx.textBaseline = 'top';
  ctx.textAlign = 'left';
  lines.forEach((line, i) => {
    ctx.fillText(line, boxX + spec.paddingX, boxY + spec.paddingY + i * spec.lineHeight);
  });
  return true;
}

/* ── Band: the full-resolution PNG export ──────────────────────────────── */

/** Unscaled band metrics; every one is multiplied by `dpr` at use, because
 *  `handleExportPNG` works entirely in srcCanvas pixel space. */
const BAND_FONT_PX = 12;
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
 * imagery, so it needs no scrim, which matters most for the path most likely to
 * be printed or pasted into a report.
 *
 * The height follows the line count, so the canvas grows to fit the credits
 * rather than the credits being cut to fit the canvas.
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
