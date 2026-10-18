/**
 * Attribution for the images the builder renders.
 *
 * The PNG export, the 400x250 thumbnail and the 1200x630 OG card all leave the
 * application showing basemap tiles whose licence requires visible credit, and
 * dataset tiles whose source terms may too. All three composite from
 * `map.getCanvas()`, a flat WebGL fill, while MapLibre's attribution control is
 * a DOM overlay that no capture path sees. A credit only reaches an image if it
 * is drawn into the canvas, which the two draw helpers here do.
 *
 * The text comes from the style's own per-source `attribution` values, as a
 * LIST (see `readRenderedAttribution`). Composing `BasemapEntry.attribution`
 * with `collectLayerAttributions` instead would be wrong for the builder:
 *
 *  1. `toMaplibreStyle` (lib/basemap-utils.ts) only threads `attribution` onto
 *     the source for XYZ tile URLs. A `/styles/` or `.json` basemap URL is
 *     returned unchanged and MapLibre reads the remote style's own attribution,
 *     so the stored field is not what the screen shows.
 *  2. `collectLayerAttributions` returns HTML-escaped strings (they are bound
 *     for `innerHTML`; see lib/attribution-safety.ts), and canvas `fillText`
 *     draws literally: "Rand & McNally" would export as "Rand &amp; McNally".
 *  3. It is keyed on the viewer's `visibleLayers` set, which the builder does
 *     not maintain: `map-sync.ts` feeds dataset credits through MapLibre's
 *     source-level `attribution` and lets MapLibre gate them on the live
 *     `used` flag.
 *
 * Reading the live style keeps the image and the screen agreeing on which
 * credits exist, and the HTML in those values is decoded through an inert
 * DOMParser rather than a regex.
 */
import { MAP_COLORS } from '@/lib/map-colors';
// The overflow marker is translated through the i18n singleton because canvas
// drawing happens outside React.
import i18n from '@/i18n/i18n';

/** The separator MapLibre's AttributionControl joins entries with. */
const SEPARATOR = ' | ';
const FONT_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

/** Only the two methods this module needs, so tests can pass a plain object
 *  and so a partial map mock (the shape the builder suites already use) is a
 *  valid argument rather than a cast. */
interface AttributionMapLike {
  getContainer?: () => HTMLElement | null | undefined;
  getStyle?: () => unknown;
  /** Live source objects. Their `attribution` is the RESOLVED value; the
   *  serialized style's is not. See `readRenderedAttribution`. */
  getSource?: (id: string) => { attribution?: string | null } | null | undefined;
  /** The 3D terrain in effect, whose source renders with no style layer of its
   *  own. Public MapLibre API; see `shownSourceIds`. */
  getTerrain?: () => { source?: unknown } | null | undefined;
  /** The current zoom, against which a layer's zoom range is judged. Also
   *  public, also only used to order; see `shownSourceIds`. */
  getZoom?: () => number | undefined;
  /** MapLibre's live style object, reached ONLY to read the same
   *  `used`/`usedForTerrain` flags the on-screen AttributionControl renders
   *  from. Typed `unknown` because the shape is internal and can be renamed
   *  between releases; `liveUsedSourceIds` reads it defensively and the
   *  modeled approximation stays as the fallback. */
  style?: unknown;
}

function attributionFont(fontPx: number): string {
  return `400 ${fontPx}px ${FONT_STACK}`;
}

/* ── HTML → credit text ────────────────────────────────────────────────────
 *
 * A credit is HTML: `BasemapEntry.attribution` permits it, MapLibre renders it,
 * and a provider may credit itself with a logo, `<img alt="© Provider">`. A
 * text alternative is not DOM text, so scraping `textContent` returned '' and
 * dropped the source from the exported image while the screen showed it. Text
 * is therefore derived from the markup, preserving the accessible alternatives:
 *
 *   text nodes        as written
 *   <img>             aria-label, else alt, else title, else a placeholder
 *   any element       its own text; if it has none, the same three attributes
 *   <br> and blocks   a visual break, so credits do not run together
 *
 * The generic element rule makes `<svg role="img" aria-label="…">` work without
 * naming SVG, and `<svg><title>…</title></svg>` works because a <title> element
 * is DOM text.
 *
 * `alt=""` is honoured as decorative, but last: it means decorative only when
 * nothing else names the image, so `<img alt="" aria-label="© Provider">` is a
 * credit. A source whose whole attribution reduces to nothing that way is still
 * a declared credit; see `declaredCreditText`.
 *
 * The parse stays inert whichever reader is in play. DOMParser documents run no
 * script and fetch no image or iframe, which `el.innerHTML = s` cannot promise;
 * the control path walks nodes MapLibre itself put in the document.
 */

/** Element boundaries that read as a line break in the rendered credit. Inline
 *  tags (a, span, b, img …) are deliberately absent: they continue the line. */
const BLOCK_CREDIT_TAGS = new Set([
  'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'DD', 'DIV', 'DL', 'DT',
  'FIELDSET', 'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3',
  'H4', 'H5', 'H6', 'HEADER', 'HR', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE',
  'SECTION', 'TABLE', 'TD', 'TH', 'TR', 'UL',
]);

/** Internal break sentinel. NUL cannot survive into rendered text — the
 *  normalizer consumes every one of them — so it cannot collide with content
 *  the way a printable delimiter would. */
const BREAK = '\u0000';

/**
 * The text alternative an assistive technology would announce for `el`.
 *
 * `aria-label` overrides `alt`, which overrides `title`, following the
 * accessible name computation: `<img alt="Provider logo" aria-label="© Provider
 * 2026">` credits the label, not "Provider logo". `aria-labelledby` outranks all
 * three in the real algorithm and is not resolved here: it points at element
 * ids, and a parsed fragment has no document to resolve against. A credit that
 * names itself only that way degrades to its `alt`/`title`.
 */
function textAlternative(el: Element): string | null {
  for (const attr of ['aria-label', 'alt', 'title']) {
    const value = el.getAttribute(attr);
    if (value !== null && value.trim()) return value;
  }
  return null;
}

/** Replaced elements that, like an image, display external content identified
 *  only by a URL, mapped to the attribute carrying that URL.
 *
 *  MapLibre's control sanitizer strips only <script>, `on*` handlers and
 *  javascript:/data: URLs, so these render visibly on screen while deriving no
 *  DOM text. They take the same treatment as an unnamed <img>: the accessible
 *  alternatives first, then the host-derived placeholder. <img> keeps its own
 *  branch because `alt=""` is a decorative opt-out these elements do not have.
 *  Elements that embed nothing external (an empty <span>, a bare <canvas>) are
 *  absent: markup with no URL names nothing, and the source-level floor still
 *  counts a credit made only of them. */
const EMBED_URL_ATTRS: Record<string, readonly string[]> = {
  OBJECT: ['data'],
  EMBED: ['src'],
  IFRAME: ['src'],
  VIDEO: ['src', 'poster'],
};

/** A name for an embed that offers no alternative at all: its host, where it
 *  has one. That is the only provider-identifying text such a credit carries,
 *  and it keeps two distinct unnamed logos from deduping into one. Hostless
 *  ones (a data: URI) still collapse, being indistinguishable in text. */
function unnamedEmbedCredit(el: Element, urlAttrs: readonly string[]): string {
  for (const attr of urlAttrs) {
    const src = el.getAttribute(attr);
    if (!src) continue;
    try {
      const url = new URL(src, window.location.href);
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        return i18n.t('builder:export.imageCreditFrom', { host: url.hostname });
      }
    } catch {
      // Unparseable URL: try the next attribute, then the bare placeholder.
    }
  }
  return i18n.t('builder:export.imageCredit');
}

function unnamedImageCredit(el: Element): string {
  return unnamedEmbedCredit(el, ['src']);
}

/** Walk `node`, collecting text and text alternatives with break sentinels at
 *  the visual boundaries. Not normalized — `normalizeCreditText` does that. */
function collectCreditText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? '';
  if (node.nodeType !== Node.ELEMENT_NODE) return '';

  const el = node as Element;
  const tag = el.tagName.toUpperCase();
  if (tag === 'BR') return BREAK;
  const isImage =
    tag === 'IMG' || (tag === 'INPUT' && el.getAttribute('type')?.toLowerCase() === 'image');
  if (isImage) {
    // Alternatives first: alt="" means decorative only when nothing else names
    // the image.
    const alternative = textAlternative(el);
    if (alternative) return alternative;
    // alt="" is an explicit "not content"; an omitted alt gets the placeholder.
    if (el.getAttribute('alt')?.trim() === '') return '';
    return unnamedImageCredit(el);
  }

  let inner = '';
  for (const child of Array.from(el.childNodes)) inner += collectCreditText(child);
  // Checked after the children so a labelled wrapper around real text does not
  // credit the same provider twice, and <object>/<iframe> fallback content
  // (which is DOM text) wins over the placeholder.
  if (!inner.split(BREAK).join('').trim()) {
    const alternative = textAlternative(el);
    const urlAttrs = EMBED_URL_ATTRS[tag];
    if (alternative) inner = alternative;
    // An unnamed URL-bearing embed gets the placeholder, as an unnamed <img> does.
    else if (urlAttrs) inner = unnamedEmbedCredit(el, urlAttrs);
  }
  return BLOCK_CREDIT_TAGS.has(tag) ? `${BREAK}${inner}${BREAK}` : inner;
}

/** Collapse the walker's output into one credit line. Segments separated by a
 *  visual break are joined with the separator the images use between credits.
 *  Presentation only: a credit is counted per source, and this is one source. */
function normalizeCreditText(raw: string): string {
  return raw
    .split(BREAK)
    .map((segment) => segment.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(SEPARATOR);
}

/**
 * Credit text for a node whose owner DECLARED an attribution.
 *
 * Empty derived text with an element present is an un-nameable credit, not an
 * absent one: a source whose whole attribution is a lone decorative image, an
 * unlabelled inline `<svg>` or a CSS-backed logo renders visibly in MapLibre but
 * derives no text. Dropping it would lose it silently, marker included, so it
 * gets the host-derived placeholder an image with no alternative gets, which
 * both renders it and counts it in the overflow marker. The test is whether the
 * declaration put something on screen we could not name, which any element
 * answers without a tag list.
 *
 * The conservatism is one-directional. A parsed fragment (no layout, no CSS)
 * cannot prove an element paints pixels, so `<div></div>` is counted as a credit
 * it probably is not; that costs an `(image credit)` line on a declaration no
 * provider would author, while the other direction costs a real provider its
 * credit. Only a declaration with no elements and no text contributes nothing.
 *
 * Within a credit, alt="" still contributes nothing: `© Provider <img alt="">`
 * is "© Provider". The placeholder is a source-level floor, not a per-image one.
 */
function declaredCreditText(root: Element): string {
  const text = normalizeCreditText(collectCreditText(root));
  if (text) return text;
  const rendered = root.querySelector?.('*');
  if (!rendered) return '';
  // An image can be named by its host; anything else takes the bare placeholder.
  const image = root.querySelector?.('img[src], input[type="image"][src]');
  return unnamedImageCredit(image ?? rendered);
}

/** Credit text for an editor-supplied HTML string, parsed inertly. */
function decodeHtmlText(raw: string): string {
  try {
    return declaredCreditText(new DOMParser().parseFromString(raw, 'text/html').body);
  } catch {
    return raw.trim();
  }
}

/** Credit text for a live element MapLibre rendered. Same derivation as the
 *  string path, so a credit cannot survive one reader and vanish in the other. */
function elementCreditText(el: Element): string {
  try {
    return declaredCreditText(el);
  } catch {
    return el.textContent?.trim() ?? '';
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
 * The rendered control's joined text cannot be split back apart: ` | ` is legal
 * content (the backend accepts it anywhere in a 5,000-character credit), so a
 * credit reading `© Acme | © Acme` split into two fragments that the dedupe
 * collapsed, deleting half a real credit and skewing the overflow marker's
 * count. Any delimiter can appear in content, so the round-trip is avoided.
 *
 * Sources, in order of preference:
 *
 *  1. The live sources' own `attribution`, one entry per source, derived from
 *     its HTML and never split. This is the only place individual credits
 *     exist as separate values, so it is the only honest input to a per-credit
 *     count. Read from `getSource(id)`, not `getStyle().sources[id]`: a vector
 *     source loaded from a TileJSON `url` receives its credits in that response
 *     while the serialized spec reports `attribution: null` (measured on the
 *     shipped OpenFreeMap basemap).
 *  2. `.maplibregl-ctrl-attrib-inner`, derived the same way, as ONE opaque
 *     entry. Only the joined line exists on this path, so it is not guessed
 *     apart; the marker's granularity is coarser, and only on a map whose
 *     sources declare nothing. Both readers share `collectCreditText`.
 *  3. Nothing, with a DEV warning.
 *
 * Within (1), shown sources come first. Once outputs have a capacity limit and
 * prefix-fit, an unused credit displaces a required one: a hidden source
 * sorting first could eat all 18 lines of a thumbnail and reduce the visible
 * provider to "+1 more credit". The builder leaves attribution on hidden
 * sources (map-sync.ts: MapLibre recomputes its control from the live `used`
 * flag), so the reader sees credits the screen does not. This orders rather
 * than filters, because a source hidden at capture time can still be part of
 * what the map is of. Everything is credited when there is room, and the
 * marker elides hidden sources first. A bounded export with room to spare
 * therefore renders a superset of the control's line, which errs in the
 * licensing-safe direction.
 *
 * `shownSourceIds` reads MapLibre's live `used` / `usedForTerrain` flags when
 * the map exposes them and falls back to a documented approximation otherwise.
 * Every gap errs toward calling a source shown, so a wrong answer mis-sorts a
 * source and never drops it.
 *
 * MapLibre's own "MapLibre" self-credit does not reach the image. It is a
 * control default rather than a source, and MapLibre GL JS is BSD-3-Clause,
 * which requires its notice in source and binary distributions, not in rendered
 * output. The interactive map still shows it.
 */
interface AttributionStyle {
  sources?: Record<string, { attribution?: string | null } | null>;
  layers?: ({
    source?: unknown;
    layout?: { visibility?: string } | null;
    minzoom?: unknown;
    maxzoom?: unknown;
  } | null)[];
}

/**
 * Drop each credit that another credit already contains whole.
 *
 * MapLibre's AttributionControl does the same (`sort((a, b) => a.length -
 * b.length)`, then drop any entry a later one `includes`), so `© Acme` beside
 * `© Acme — CC BY 4.0` shows once on screen. Without it the redundant fragment
 * could take line budget and leave the complete licensing statement as "+1 more
 * credit". Only the suppression is mirrored, not the sort: this list is ordered
 * shown-first and by style order within that (see `readRenderedAttribution`).
 *
 * Matches maplibre-gl 6.5.0 (`_updateAttributions`): exact-duplicate skip,
 * whitespace-only filter, then strictly-longer containment and the ` | ` join.
 * One divergence is deliberate: the control compares raw HTML strings, this
 * module compares derived text, because text is what the image renders. Two
 * anchors differing only in `href` collapse to one here, and containment that
 * normalization breaks (`©  Acme` beside `© Acme Data`) still suppresses. Both
 * only remove a line whose text another line carries whole.
 *
 * Strictly longer, so equal strings cannot suppress each other into nothing
 * (`dedupe` owns that case). Within one priority group only, because a hidden
 * credit suppressing a shown one would let the hidden superstring be the entry
 * the marker elides.
 */
function suppressContainedCredits(entries: string[]): string[] {
  return entries.filter(
    (entry, i) =>
      !entries.some(
        (other, j) => j !== i && other.length > entry.length && other.includes(entry),
      ),
  );
}

/**
 * Source ids that are rendering, in two tiers.
 *
 * Tier 1, the live flags (`liveUsedSourceIds`): the on-screen control renders
 * the sources for which `map.style.tileManagers[id].used || .usedForTerrain`
 * holds (maplibre-gl 6.5.0, `_updateAttributions`), and `map.style` is
 * reachable from the live Map both capture paths hold. Reading the control's own
 * input means the partition cannot disagree with it; the flags are at most one
 * frame old because captures run inside a render callback. The collection is
 * internal and has been renamed once (`sourceCaches` until maplibre-gl 5.24), so
 * it is read defensively: an unreachable collection falls back to tier 2, which
 * is why null and an empty live collection are distinguished.
 *
 * Tier 2, the approximation, for a partial map (the builder suites' mocks) and
 * the next rename. It models MapLibre's own definition of the flag, "at least
 * one layer visible in style sense": `!layer.isHidden(zoom)`, where `isHidden`
 * is `zoom < minzoom || zoom >= maxzoom || visibility === 'none'`.
 *
 *   - `layout.visibility`
 *   - the layer's zoom range with MapLibre's boundary semantics: minzoom
 *     inclusive, maxzoom exclusive, zero treated as absent. Read from the
 *     serialized `minzoom`/`maxzoom`, not the builder-private
 *     `_minzoom`/`_maxzoom`, which `stripPrivateLayoutKeys` removes before
 *     MapLibre sees them.
 *   - Terrain, whose source renders with no style layer:
 *     `ensureRasterDemTerrainSource` creates an attributed source that only
 *     `usedForTerrain` counts.
 *
 * Neither tier models, and neither does the control (`used` is set from
 * `!layer.isHidden(zoom)` alone): a layer `filter` matching no feature (the
 * control still credits it, so parity means counting it shown), zero opacity or
 * invisible paint, and empty or off-viewport tiles. Tier 2 alone also misses
 * anything not in the serialized style and the per-frame recompute.
 *
 * Every gap errs toward calling a source shown: the answer only orders the
 * credit list, so a misjudged source is mis-sorted, never dropped.
 */
interface LiveTileManagerLike {
  used?: unknown;
  usedForTerrain?: unknown;
}

/**
 * The ids MapLibre itself counts used, from the live flags the on-screen control
 * renders from, or null when the internal collection is not reachable. The
 * truthiness test mirrors the control's (`used || usedForTerrain`).
 */
function liveUsedSourceIds(map: AttributionMapLike): Set<string> | null {
  const style = map.style as
    | { tileManagers?: Record<string, LiveTileManagerLike | null | undefined> | null }
    | null
    | undefined;
  const managers = style?.tileManagers;
  if (!managers || typeof managers !== 'object') return null;
  const used = new Set<string>();
  for (const id of Object.keys(managers)) {
    const manager = managers[id];
    if (manager && (manager.used || manager.usedForTerrain)) used.add(id);
  }
  return used;
}

function layerHiddenAtZoom(
  layer: { minzoom?: unknown; maxzoom?: unknown },
  zoom: number | undefined,
): boolean {
  if (typeof zoom !== 'number' || !Number.isFinite(zoom)) return false;
  const { minzoom, maxzoom } = layer;
  // The `&&` mirrors MapLibre's own truthiness test, under which a zero bound
  // is no bound at all.
  if (typeof minzoom === 'number' && minzoom && zoom < minzoom) return true;
  if (typeof maxzoom === 'number' && maxzoom && zoom >= maxzoom) return true;
  return false;
}

function shownSourceIds(
  map: AttributionMapLike,
  style: AttributionStyle | null | undefined,
): Set<string> {
  // The live flags are what the on-screen control renders from; the model below
  // is the fallback for a map that does not expose them.
  const live = liveUsedSourceIds(map);
  if (live) return live;

  const shown = new Set<string>();
  const terrainSource = map.getTerrain?.()?.source;
  if (typeof terrainSource === 'string') shown.add(terrainSource);
  // Absent `getZoom` leaves every layer in range, per the over-report rule.
  const zoom = map.getZoom?.();
  for (const layer of style?.layers ?? []) {
    if (!layer || layer.layout?.visibility === 'none') continue;
    if (layerHiddenAtZoom(layer, zoom)) continue;
    if (typeof layer.source === 'string') shown.add(layer.source);
  }
  return shown;
}

export function readRenderedAttribution(map: AttributionMapLike): string[] {
  const style = map.getStyle?.() as AttributionStyle | null | undefined;
  const sources = style?.sources;
  if (sources) {
    // Partitioned rather than sorted, so the style's order survives in each group.
    const shown = shownSourceIds(map, style);
    const fromShown: string[] = [];
    const fromHidden: string[] = [];
    for (const id of Object.keys(sources)) {
      // The live source first: a TileJSON-`url` source receives its attribution
      // in that response, while the serialized spec says null. The serialized
      // value is the fallback for a source the map has not instantiated.
      const live = map.getSource?.(id)?.attribution;
      const raw = typeof live === 'string' && live.trim() ? live : sources[id]?.attribution;
      if (typeof raw !== 'string' || !raw.trim()) continue;
      const decoded = decodeHtmlText(raw);
      if (decoded) (shown.has(id) ? fromShown : fromHidden).push(decoded);
    }
    // Containment is suppressed within each group only; the exact-duplicate
    // dedupe runs across both, so a credit on a shown and a hidden source keeps
    // the shown one's position.
    const deduped = dedupe([
      ...suppressContainedCredits(fromShown),
      ...suppressContainedCredits(fromHidden),
    ]);
    if (deduped.length > 0) return deduped;
  }

  const inner = map.getContainer?.()?.querySelector?.(
    '.maplibregl-ctrl-attrib-inner',
  );
  // Derived, not `textContent`: an image-only credit is as real as one declared
  // on a source.
  const rendered = inner ? elementCreditText(inner) : '';
  // Not split: the separator is legal content.
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
 * No output drops a credit silently, and none shrinks below its documented
 * size. An ellipsis credits nobody, and a truncated line reads as a complete
 * statement of provenance, so there is no elision path: text wraps to as many
 * lines as it needs, the export canvas grows, and the two fixed-size crops spend
 * map pixels instead of provider names.
 *
 * Every output renders at one documented size and never below it:
 *
 *   PNG export   12px on white         (no scrim needed, not over imagery)
 *   OG card      16px over a scrim     (1200x630 JPEG, quality 0.85)
 *   Thumbnail    10px over a scrim     (400x250 JPEG, quality 0.7)
 *
 * There is no shrink ladder: 10px over a scrim is legible at 1:1, while 9px
 * under JPEG chroma subsampling is where small text turns to mush. The gallery
 * shows the thumbnail at 176x112, but that is a display-size decision.
 *
 * How much of each image the band can eat. The line counts and ceilings are
 * asserted in lib/__tests__/map-image-attribution.test.ts, and
 * `overlayLineCapacity` computes the ceiling column. Chars/line is the only
 * estimate, since glyph widths are font-dependent.
 *
 *               line    usable    chars/   real 5-credit    ceiling
 *               height  width     line     load             (band runs out)
 *   Thumbnail   13px    378px     ~75      6 lines, 33.6%   18 lines, ~1350 chars
 *   OG card     20px    1160px    ~145     4 lines, 14.3%   30 lines, ~4350 chars
 *   PNG export  16px    1016px*   ~169     4 lines, 88px    951 lines, ~161k chars
 *
 *   * the measured 1056px-wide export at dpr 1, less 20px of pad a side.
 *
 * The crops run out where the scrim reaches the top edge. The export's canvas is
 * sized after the band is measured, so it runs out at the largest canvas a
 * browser will hand back a blob for; see EXPORT_CANVAS_MAX_DIMENSION.
 *
 * The ceilings are well clear of the measured real-world load (~3.3x for the
 * thumbnail, ~10x for the OG card, ~400x for the export), but the supported
 * input is far larger: `attribution` is `max_length=5000` on the dataset schema
 * and `NonEmptyString5000` on the manifest, and a map may carry 200 layers.
 * Past its ceiling each output renders the credits that fit and appends a
 * visible, counted marker naming how many did not (`export.moreCredits`), with
 * the marker itself charged against the line budget. The marker keeps the
 * visible list from reading as a complete statement of provenance. Nothing is
 * drawn outside the canvas.
 *
 * A single credit longer than a full line wraps mid-string, on word boundaries
 * and then on characters, which splits a provider's name across lines but never
 * truncates it.
 */

/** Greedy wrap on entry boundaries, so a provider's name stays on one line.
 *  Returns null when a single entry is wider than `maxWidth`, which wrapping
 *  on entry boundaries cannot resolve. The width scan is its own first pass so
 *  `maxLines` cannot change the answer; only the layout stops early. */
function wrapEntries(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  maxWidth: number,
  maxLines = Infinity,
): string[] | null {
  for (const entry of entries) {
    if (ctx.measureText(entry).width > maxWidth) return null;
  }
  const lines: string[] = [];
  let current = '';
  for (const entry of entries) {
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
      if (lines.length > maxLines) return lines;
    }
  }
  if (current) lines.push(current);
  return lines;
}

/**
 * Split `text` into user-perceived characters. Indexing by UTF-16 code unit
 * would split a surrogate pair and render replacement glyphs in place of a
 * provider's name.
 *
 * `Intl.Segmenter` also keeps combining marks and ZWJ emoji sequences intact,
 * which `Array.from` (code points) does not. `Array.from` is the fallback for an
 * engine without `Segmenter`.
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

/** Break a word wider than `maxWidth` into pieces that are not, losing nothing.
 *  Binary search per piece over grapheme clusters; each piece takes at least one
 *  cluster, so it terminates and never splits a character. */
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
  maxLines = Infinity,
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
    // Lines already emitted are final; past the budget the caller re-fits a
    // counted prefix, so finishing the wrap would only be discarded work.
    if (lines.length > maxLines) return lines;
  }
  if (current) lines.push(current);
  return lines;
}

interface FitAttributionOptions {
  maxWidth: number;
  fontPx: number;
  /** Stop once the result is known to exceed this many lines. */
  maxLines?: number;
}

interface FittedAttribution {
  lines: string[];
  fontPx: number;
}

/**
 * Lay `entries` out at `fontPx`, wrapping to as many lines as they need.
 *
 * Total by construction: the returned lines contain every character of every
 * entry. Leaves `ctx.font` set.
 *
 * `maxLines` makes it a bounded probe whose lines are a prefix once the budget
 * is exceeded, so only a caller that discards them there may pass it. The
 * wrappers are greedy, so the under-budget result is unchanged.
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
  const byEntry = wrapEntries(ctx, clean, opts.maxWidth, opts.maxLines);
  if (byEntry) return { lines: byEntry, fontPx: opts.fontPx };
  return {
    lines: wrapWords(ctx, clean.join(SEPARATOR), opts.maxWidth, opts.maxLines),
    fontPx: opts.fontPx,
  };
}

/* ── Overlay: the two fixed-size crops ─────────────────────────────────── */

interface AttributionOverlaySpec {
  fontPx: number;
  /** Baseline-to-baseline step for a wrapped credit. */
  lineHeight: number;
  /** Distance from the canvas edge to the scrim. */
  inset: number;
  paddingX: number;
  paddingY: number;
  radius: number;
}

/** 400x250. It carries the credit because `get_share_card_image_url` falls back
 *  to the thumbnail as the og:image for maps without a dedicated OG image, and
 *  that surface has no adjacent text. */
export const THUMBNAIL_ATTRIBUTION: AttributionOverlaySpec = {
  fontPx: 10,
  lineHeight: 13,
  inset: 6,
  paddingX: 5,
  paddingY: 3,
  radius: 3,
};

/** 1200x630. An overlay rather than a band, which would change the 1.91:1 ratio
 *  social platforms crop against. */
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
 * scrim reaches the top edge. The crops' only real ceiling; the export band has
 * no equivalent because its canvas is sized after the band is measured.
 */
export function overlayLineCapacity(
  spec: AttributionOverlaySpec,
  canvasHeight: number,
): number {
  const usable = canvasHeight - spec.inset - spec.paddingY * 2;
  return Math.max(0, Math.floor(usable / spec.lineHeight));
}

/**
 * The largest number of leading entries whose wrapped form fits `maxLines`,
 * with the lines it produced. Binary search, because line count is monotonic in
 * the entry count and a linear probe would re-wrap a very large string once per
 * entry.
 */
function fitEntryPrefix(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  maxWidth: number,
  maxLines: number,
): { lines: string[]; count: number } {
  if (maxLines <= 0) return { lines: [], count: 0 };
  // Each probe only has to answer "more than maxLines?", so it stops there.
  const wrapFirst = (count: number): string[] => {
    if (count === 0) return [];
    const slice = entries.slice(0, count);
    return (
      wrapEntries(ctx, slice, maxWidth, maxLines) ??
      wrapWords(ctx, slice.join(SEPARATOR), maxWidth, maxLines)
    );
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
 * doubles apparent weight, and halo plus JPEG chroma subsampling turns small
 * text to mush. One fixed pair works over light and dark tiles, and over the
 * globe case where the bottom-right may be space, because the scrim sets its
 * own ground.
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
  // Nowhere legible to put even one line; drawing would paint outside the frame.
  if (maxWidth <= 0 || capacity < 1) return false;

  // Deduped here too: the overflow marker counts credits.
  const credits = dedupe(entries);
  const fitted = fitAttributionText(ctx, credits, {
    maxWidth,
    fontPx: spec.fontPx,
    maxLines: capacity,
  });
  if (fitted.lines.length === 0) return false;

  // `boxY` clamps at 0, so a band taller than the frame would draw below the
  // canvas. The supported input (5,000 characters per credit, dataset
  // schemas.py and manifest_schemas.py) is ~77 lines in a 250px thumbnail, so
  // render what fits and add a counted marker, itself charged against the line
  // budget.
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

/*
 * The export canvas's own ceiling. The band's measured height is assigned
 * straight to the export canvas, and browsers cap a canvas per side and by total
 * area; past either, `toBlob` returns null with nothing raised, the export
 * toasts a failure and no image is produced. At the contract's maximum (200
 * layers, 5,000 characters each) the band alone asks for tens of thousands of
 * pixels. A bounded band with a counted marker loses some provider names; an
 * unencodable canvas loses every one along with the map.
 *
 * The figures are the smallest measured for any engine in canvas-size's table
 * (jhildenbiddle/canvas-size, src/test-sizes.js):
 *
 *   per side  Chrome 83 65,535 · Chrome 70 and Firefox 63 32,767 · Edge 17 and
 *             IE 11 16,384. We take 16,384, half the floor of any engine this
 *             app supports.
 *   area      Chrome 70 / Edge 17 / Safari 7-12 (Mac) 16,384² = 268,435,456 ·
 *             Firefox 63 11,180² = 124,992,400 · Safari on iOS 4,096² =
 *             16,777,216. We take iOS Safari's.
 *
 * A bound is worth only the worst environment it has to hold in: an iPad's
 * 2048x2732 canvas is valid, and enough credits grew it past 8,192px high for
 * `toBlob` to return null when budgeting against the desktop figure. We neither
 * probe the engine nor sniff the user agent, so the cap is the floor of what
 * every supported engine can do.
 *
 * A desktop export loses nothing until the map canvas alone is around
 * 4,096x4,096 device pixels: the measured 1056px-wide export still gets 951 band
 * lines, and a 4400x2400 canvas (a maximized builder on a 5K display at dpr 2)
 * gets 41. Past that the fixed blocks take the ceiling and the band gets what is
 * left, down to nothing; see `attributionBandHeightBudget`.
 */
export const EXPORT_CANVAS_MAX_DIMENSION = 16_384;
export const EXPORT_CANVAS_MAX_AREA = 16_777_216;

/** The tallest export canvas a browser will still encode at `canvasWidth`,
 *  in device pixels. Area-limited for a very wide canvas, side-limited for the
 *  ordinary ones (anything narrower than ~7,600px). */
export function exportCanvasHeightCeiling(canvasWidth: number): number {
  if (!(canvasWidth > 0)) return 0;
  return Math.min(
    EXPORT_CANVAS_MAX_DIMENSION,
    Math.floor(EXPORT_CANVAS_MAX_AREA / canvasWidth),
  );
}

/**
 * How much of that ceiling is left for the band once the fixed blocks (title,
 * map, legend, footer) have taken theirs. The band is the only elastic term in
 * the export's height, so it absorbs the whole clamp.
 *
 * Actual positive headroom, never more: a minimum-band floor would push a
 * canvas past the very limit the ceiling holds (width 2048, dpr 2 and 8,140px
 * reserved leaves 52px under an 8,192 ceiling, and an 80px floor gives 8,220).
 * Under one line's worth the band declines entirely, as
 * `drawAttributionOverlay` does at `capacity < 1`.
 *
 * Residual: in that window the export carries no credit and no marker, because
 * there is nowhere to put either. It is reachable only when the fixed blocks are
 * within one band-height of the cap (the 200-layer legend at dpr 2 on an
 * iPad-sized canvas is already past the ceiling before the band is measured),
 * where the alternative is an image that cannot be encoded at all.
 */
export function attributionBandHeightBudget(
  canvasWidth: number,
  reservedHeight: number,
): number {
  return Math.max(0, exportCanvasHeightCeiling(canvasWidth) - Math.ceil(reservedHeight));
}

/** How many credit lines fit a band budget of `maxHeight` device pixels, the
 *  band's counterpart to `overlayLineCapacity`. Both gaps are charged first:
 *  a band is not a band without its surrounding whitespace. */
export function attributionBandLineCapacity(maxHeight: number, dpr: number): number {
  const scale = dpr || 1;
  const usable = maxHeight - BAND_GAP * scale * 2;
  return Math.max(0, Math.floor(usable / (BAND_LINE_HEIGHT * scale)));
}

interface MeasuredAttributionBand {
  lines: string[];
  /** Already dpr-scaled: the caller draws with it directly. */
  fontPx: number;
  /** Already dpr-scaled: the caller adds it into the canvas height. */
  height: number;
}

/**
 * Measure the export's attribution band before the canvas is sized.
 *
 * It is its own band rather than a share of the branding footer row: sharing
 * would need horizontal collision math against the branding width and a special
 * case for `showBranding === false`. It sits on white, so it needs no scrim.
 *
 * The height follows the line count, up to `maxHeight`, which is what the
 * browser will still encode. Pass it from `attributionBandHeightBudget`; it is
 * required so no caller reaches the unbounded behaviour by omission.
 */
export function measureAttributionBand(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  opts: { maxWidth: number; dpr: number; maxHeight: number },
): MeasuredAttributionBand {
  const dpr = opts.dpr || 1;
  const fallback = { lines: [], fontPx: BAND_FONT_PX * dpr, height: 0 };
  if (entries.length === 0 || opts.maxWidth <= 0) return fallback;

  // Deduped here too: the overflow marker counts credits.
  const credits = dedupe(entries);
  const capacity = attributionBandLineCapacity(opts.maxHeight, dpr);
  const fitted = fitAttributionText(ctx, credits, {
    maxWidth: opts.maxWidth,
    fontPx: BAND_FONT_PX * dpr,
    maxLines: capacity,
  });
  if (fitted.lines.length === 0) return fallback;

  // Past the budget, the same counted marker the two crops use.
  let lines = fitted.lines;
  if (lines.length > capacity) {
    // No room for even a marker; see `attributionBandHeightBudget`.
    if (capacity < 1) return fallback;
    const kept = fitEntryPrefix(ctx, credits, opts.maxWidth, capacity - 1);
    const omitted = credits.length - kept.count;
    lines = [...kept.lines, i18n.t('builder:export.moreCredits', { count: omitted })];
  }

  return {
    lines,
    fontPx: fitted.fontPx,
    height: Math.round(
      BAND_GAP * dpr + lines.length * BAND_LINE_HEIGHT * dpr + BAND_GAP * dpr,
    ),
  };
}

/**
 * Draw a measured band with its top-left at (`x`, `y`).
 *
 * `mutedText` (#666666, ~5.7:1 on white) rather than the #999999 the branding
 * footer uses (~2.8:1): a legally required line is not the place for a
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
