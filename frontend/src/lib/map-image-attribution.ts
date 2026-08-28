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
  /** The 3D terrain in effect, whose source renders with no style layer of its
   *  own. Public MapLibre API; see `shownSourceIds`. */
  getTerrain?: () => { source?: unknown } | null | undefined;
  /** The current zoom, against which a layer's zoom range is judged. Also
   *  public, also only used to order; see `shownSourceIds`. */
  getZoom?: () => number | undefined;
  /** feat(#1553): MapLibre's live style object, reached ONLY to read the same
   *  `used`/`usedForTerrain` flags the on-screen AttributionControl renders
   *  from. Typed `unknown` because the shape is internal and has been renamed
   *  under us once already; `liveUsedSourceIds` reads it defensively and the
   *  modeled approximation stays as the fallback. */
  style?: unknown;
}

function attributionFont(fontPx: number): string {
  return `400 ${fontPx}px ${FONT_STACK}`;
}

/* ── HTML → credit text ────────────────────────────────────────────────────
 *
 * fix(#1541 codex P2 round 3): both readers used to take `textContent`, and a
 * credit is HTML. `BasemapEntry.attribution` permits it, MapLibre renders it,
 * and a provider is entitled to credit itself with a logo:
 * `<img alt="© Provider" src="logo.svg">`. A text alternative is not DOM text,
 * so `textContent` returned '' and the source was skipped — the map on screen
 * showed the credit and the exported PNG, thumbnail and OG card did not. That
 * is the silent drop this module exists to make impossible, in its worst form:
 * the user can see the discrepancy by looking at their own screen.
 *
 * So text is DERIVED from the markup rather than scraped off it, preserving
 * the accessible alternatives a sighted user is reading:
 *
 *   text nodes        as written
 *   <img>             aria-label, else alt, else title, else a placeholder
 *   any element       its own text; if it has none, the same three attributes
 *   <br> and blocks   a visual break, so credits do not run together
 *
 * The generic element rule is what makes `<svg role="img" aria-label="…">`
 * work without naming SVG anywhere, and `<svg><title>…</title></svg>` already
 * worked because a <title> element IS DOM text.
 *
 * `alt=""` is honoured as its author meant it — but LAST, after the other two
 * alternatives, because alt="" means decorative only when nothing else names
 * the image. `<img alt="" aria-label="© Provider">` has an accessible name and
 * is a credit. And a source whose WHOLE attribution reduces to nothing that
 * way is still a declared credit; see `declaredCreditText`.
 *
 * Whichever reader is in play, the parse stays inert. DOMParser documents run
 * no script and fetch no image or iframe, which `el.innerHTML = s` cannot
 * promise; the control path walks nodes MapLibre itself put in the document.
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
 * fix(#1541 codex P2 round 7): `aria-label` OVERRIDES `alt`, it does not follow
 * it. The accessible name computation takes ARIA first, the host-language
 * attribute second, `title` only as a fallback, and the realistic markup for a
 * provider logo is exactly the case the old order got wrong:
 * `<img alt="Provider logo" aria-label="© Provider 2026">` drew "Provider logo"
 * into every exported image while the credit sat in the label.
 *
 * `aria-labelledby` outranks all three in the real algorithm and is NOT
 * resolved here: it points at element ids, which for the string path would have
 * to resolve inside a parsed fragment that has no document to resolve against.
 * A credit that names itself only by id reference is unattested in practice,
 * and it degrades to the `alt`/`title` it is layered over rather than vanishing.
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
 *  feat(#1553 candidate 4): MapLibre's control sanitizer strips only <script>,
 *  `on*` handlers and javascript:/data: URLs, so every one of these renders
 *  perfectly visibly in the on-screen control — and none of them derives DOM
 *  text, so a provider crediting itself with `<object data="logo.svg">` used to
 *  contribute nothing inline and reach the image only through the source-level
 *  floor, or not at all when text stood beside it. They now take the same
 *  treatment as an unnamed <img>: the accessible alternatives first (the
 *  generic-element rule already checks those), then the host-derived
 *  placeholder. <img> keeps its own branch because `alt=""` is a decorative
 *  opt-out these elements do not have. Elements that embed nothing external
 *  (an empty <span>, a bare <canvas>) are deliberately absent: markup with no
 *  URL names nothing, and the source-level floor still counts a credit made
 *  only of them. */
const EMBED_URL_ATTRS: Record<string, readonly string[]> = {
  OBJECT: ['data'],
  EMBED: ['src'],
  IFRAME: ['src'],
  VIDEO: ['src', 'poster'],
};

/** A name for an embed that offers no alternative at all. Its host, where it
 *  has one: that is the only provider-identifying text such a credit carries,
 *  and it also keeps two distinct unnamed logos from deduping into one. Two
 *  hostless ones (a data: URI) still collapse — they are indistinguishable in
 *  text, which is the residual of a credit that ships no words. */
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
    // fix(#1541 codex P2 round 4): alternatives FIRST. The decorative shortcut
    // used to run ahead of them, so `<img alt="" aria-label="© Provider">` was
    // suppressed even though the ARIA label gives it an accessible name and
    // MapLibre renders the logo. alt="" means decorative only when nothing
    // else names the image — that is the accessibility rule, and a shortcut
    // that runs before the thing it is a shortcut for is just a bug.
    const alternative = textAlternative(el);
    if (alternative) return alternative;
    // Nothing names it. An author who wrote alt="" said "not content"; one who
    // omitted alt said nothing at all, and gets the placeholder.
    if (el.getAttribute('alt')?.trim() === '') return '';
    return unnamedImageCredit(el);
  }

  let inner = '';
  for (const child of Array.from(el.childNodes)) inner += collectCreditText(child);
  // An element that contributes no text of its own falls back to its own
  // alternative. Checked AFTER the children so a labelled wrapper around real
  // text does not credit the same provider twice — and so <object>/<iframe>
  // fallback content, which IS DOM text, wins over the placeholder.
  if (!inner.split(BREAK).join('').trim()) {
    const alternative = textAlternative(el);
    const urlAttrs = EMBED_URL_ATTRS[tag];
    if (alternative) inner = alternative;
    // feat(#1553 candidate 4): an unnamed URL-bearing embed is displaying
    // something we cannot name, exactly like an unnamed <img>. Placeholder,
    // not silence — mirroring the image rule keeps the two forms a provider
    // actually ships (img and object/embed logos) from diverging.
    else if (urlAttrs) inner = unnamedEmbedCredit(el, urlAttrs);
  }
  return BLOCK_CREDIT_TAGS.has(tag) ? `${BREAK}${inner}${BREAK}` : inner;
}

/** Collapse the walker's output into one credit line. Segments separated by a
 *  visual break are joined with the separator the images already use between
 *  credits — presentation only. It creates no new counted credit: a credit is
 *  counted per SOURCE, and this is the text of one source. */
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
 * fix(#1541 codex P2 round 4): honouring alt="" opened the gap beside it. A
 * source whose entire attribution is a lone decorative image derives no text,
 * and an empty derivation used to drop the source from the list — so it was
 * counted nowhere, marker included, which is the silent loss this module
 * exists to prevent. Empty text with an image present is an UN-NAMEABLE
 * credit, not an absent one: it gets the same host-derived placeholder an
 * image with no alternative gets, which both renders it and makes it one of
 * the `credits.length` the overflow marker counts.
 *
 * fix(#1541 codex P2 round 8): that fallback then recognised only `<img>`, so
 * an unlabelled inline `<svg>` or a CSS-backed logo — both of which MapLibre
 * renders perfectly visibly — derived no text, matched no image, and vanished
 * without even reaching the marker. Enumerating a third tag list would only
 * move the boundary, so the question asked here is the one actually meant: DID
 * THIS DECLARATION PUT SOMETHING ON SCREEN THAT WE COULD NOT NAME? Any element
 * is the answer. Markup with no text is displaying something graphical — a
 * logo, a glyph, a background — and no tag list is needed to know that.
 *
 * The conservatism is deliberate and one-directional. Neither a parsed fragment
 * (no layout, no CSS) nor a headless read can prove an element paints pixels,
 * so `<div></div>` is counted as a credit it probably is not. That costs a
 * `(image credit)` line on a declaration no provider would author. The other
 * direction costs a real provider its credit, silently. Only a declaration with
 * no elements AND no text (`'   '`, `''`) contributes nothing: there is
 * genuinely nothing there to lose.
 *
 * Note the layering: within a credit, alt="" still contributes nothing —
 * `© Provider <img alt="">` is "© Provider", not "© Provider (image credit)".
 * The placeholder is a SOURCE-level floor, not a per-image one.
 */
function declaredCreditText(root: Element): string {
  const text = normalizeCreditText(collectCreditText(root));
  if (text) return text;
  const rendered = root.querySelector?.('*');
  if (!rendered) return '';
  // An image can at least be named by its host; anything else takes the bare
  // placeholder. Both are counted, which is the point.
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
 *  string path — fixing one reader and leaving its sibling is how a credit
 *  goes missing from exactly one of the two ways it can be read. */
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
 *  1. The live sources' own `attribution`, one entry per source, derived from
 *     its HTML and never split on anything. This is the only place the individual
 *     credits exist as separate values, so it is the only honest input to a
 *     per-credit count. Read from `getSource(id)` rather than from
 *     `getStyle().sources[id]`: MEASURED on the shipped OpenFreeMap basemap,
 *     the serialized spec reports `attribution: null` while the live source
 *     carries the OpenMapTiles and OpenStreetMap credits, because a vector
 *     source loaded from a TileJSON `url` receives them in that response and
 *     `getStyle()` serializes the spec as authored. Reading the spec alone
 *     dropped every basemap credit whenever a dataset declared one.
 *  2. `.maplibregl-ctrl-attrib-inner`, derived the same way, as ONE opaque
 *     entry. This path genuinely only has the joined line, so it does not
 *     guess: the whole thing is treated as a single credit rather than split
 *     back apart. It renders identically; only the marker's granularity is
 *     coarser, and only on a map whose sources declare nothing. Both readers
 *     run the same derivation — see `collectCreditText` — because a credit
 *     that survives one reader and not its sibling is still a lost credit.
 *  3. Nothing, with a DEV warning.
 *
 * Within (1), SHOWN SOURCES COME FIRST.
 *
 * fix(#1541 codex P1): the list used to be in whatever order the style declared
 * its sources, and "no `used` gating — over-crediting is the safe direction"
 * was an accepted cost of that. It stopped being safe the moment the outputs
 * gained a capacity limit and a prefix fit. Over-crediting is free only while
 * everything fits; once entries compete for a bounded budget an unused credit
 * does not add information, it DISPLACES a required one, and prefix-fitting
 * makes position decisive. A hidden source that happened to sort first could
 * eat all 18 lines of a thumbnail and reduce the visible provider to "+1 more
 * credit". The builder deliberately leaves attribution on hidden sources
 * (map-sync.ts: MapLibre recomputes its own control from the live `used` flag,
 * so hiding every layer on a source drops its credit with no code of ours
 * running), so the reader sees credits the screen does not.
 *
 * Ordering rather than filtering, deliberately: a source hidden at capture time
 * can still be part of what the map is OF. Everything is still credited when
 * there is room — the over-crediting property is intact — and what the marker
 * elides first is now the hidden sources, which is the correct thing to lose.
 * The on-screen control filters (an unused source's credit simply is not
 * there), so a bounded export with room to spare renders a SUPERSET of the
 * control's line. That is the one deliberate, decided divergence (#1541
 * review) and it errs in the licensing-safe direction.
 *
 * feat(#1553): `shownSourceIds` now reads MapLibre's live `used` /
 * `usedForTerrain` flags — the control's own input — whenever the map exposes
 * them, and falls back to the documented approximation (layer visibility, zoom
 * range, terrain) only when it does not. See its comment for the two tiers and
 * their gaps. Every gap errs toward calling a source shown, which costs
 * nothing: the answer only ORDERS the list, so a source it gets wrong is
 * mis-sorted, never dropped.
 *
 * One cost of preferring (1), accepted:
 *
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
 * That is the price of a credit list that cannot be mangled by its own content,
 * which is the property the whole marker count rests on.
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
 * fix(#1541 codex P2 round 8): MapLibre's own AttributionControl does this —
 * `sort((a, b) => a.length - b.length)`, then drop any entry a later one
 * `includes` — so `© Acme` beside `© Acme — CC BY 4.0` shows once on screen and
 * showed twice in the image. The failure is asymmetric, which is why it earns a
 * fix: source order could let the redundant fragment take the line budget and
 * leave the COMPLETE licensing statement as "+1 more credit".
 *
 * Only the suppression is mirrored, not the sort. MapLibre reorders by length;
 * this list is ordered shown-first and by style order within that, which is
 * load-bearing (see `readRenderedAttribution`).
 *
 * chore(#1553 candidate 3): re-verified line-by-line against the installed
 * maplibre-gl 6.5.0 (`_updateAttributions`): exact-duplicate skip at
 * collection, whitespace-only filter, length sort, then drop any entry a
 * LATER — post-sort, longer — entry `includes`. Two rules line up exactly:
 * strictly-longer containment (after the sort and the exact dedupe, an
 * equal-length distinct entry can never contain another) and the ` | ` join.
 * One divergence is deliberate and stays: the control compares RAW HTML
 * strings, this module compares DERIVED TEXT. Text is what the image renders,
 * so two anchors differing only in `href` — which the control shows twice —
 * are indistinguishable visual duplicates here and collapse to one; and
 * raw-level containment that normalization breaks (`©  Acme` beside
 * `© Acme Data`) still suppresses at the text level. Both directions only ever
 * REMOVE a line whose text another line carries whole, so no credit text is
 * lost either way.
 *
 * STRICTLY longer, and WITHIN ONE PRIORITY GROUP ONLY. Strictly longer so two
 * equal strings cannot suppress each other into nothing — `dedupe` owns that
 * case. Within one group because a hidden credit suppressing a shown one would
 * reinstate the crowding-out bug through a different door: the shown text would
 * leave the list, and the hidden superstring still carrying it could then be
 * the entry the marker elides.
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
 * Source ids that are rendering, in TWO TIERS: MapLibre's own live
 * `used`/`usedForTerrain` flags where they are reachable (feat(#1553)), and
 * the modeled approximation of them where they are not.
 *
 * TIER 1 — the live flags (`liveUsedSourceIds`). The on-screen
 * AttributionControl renders exactly the sources for which
 * `map.style.tileManagers[id].used || .usedForTerrain` holds (maplibre-gl
 * 6.5.0, src/ui/control/attribution_control.ts `_updateAttributions`), and
 * `map.style` IS reachable from the live Map instance both capture paths
 * already hold — the export is canvas-composited, not headless. Reading the
 * control's own input removes the approximation class of drift outright: the
 * partition cannot disagree with the control, including when MapLibre next
 * changes what counts as used. The one residual is timing — the flags are
 * recomputed per rendered frame, and both captures run inside a render
 * callback, so they are at most one frame old, strictly fresher than a model.
 *
 * The collection is internal, though, typed on `Style` but not API, and it has
 * been renamed once already — `sourceCaches` until maplibre-gl 5.24,
 * `tileManagers` since. So it is read defensively: an unreachable collection
 * (absent, renamed again, not an object) falls back to tier 2 rather than
 * degrading to an everything-hidden answer, which is why null and an empty
 * live collection are distinguished.
 *
 * TIER 2 — the approximation, kept as the fallback for a partial map (the
 * builder suites' mocks) and for the next rename. It recomputes the flag from
 * what `getStyle()`, `getZoom()` and `getTerrain()` expose.
 *
 * WHAT TIER 2 MODELS, which is MapLibre's own definition of the flag — "at
 * least one of its layers becomes visible in style sense (inside the layer's
 * zoom range and with layout.visibility set to 'visible')", and in the source
 * `!layer.isHidden(zoom) && layer.source && tileManagers[layer.source].used =
 * true`, where `isHidden` is `zoom < minzoom || zoom >= maxzoom || visibility
 * === 'none'`:
 *
 *   - `layout.visibility` (fix(#1541 codex P1))
 *   - the layer's zoom range (fix(#1541 codex P2 round 7)), with MapLibre's own
 *     boundary semantics: minzoom inclusive, maxzoom exclusive, and a zero
 *     treated as absent exactly as its truthiness test does. Read from the
 *     serialized `minzoom`/`maxzoom`, not the builder-private
 *     `_minzoom`/`_maxzoom`, which `stripPrivateLayoutKeys` removes before
 *     MapLibre sees them and which reach the style through `setLayerZoomRange`.
 *   - terrain (fix(#1541 codex P2 round 6)), whose source renders with NO style
 *     layer at all: `ensureRasterDemTerrainSource` creates an attributed source
 *     that only `usedForTerrain` counts, so layer references alone put a credit
 *     for plainly visible 3D relief in the hidden group.
 *
 * WHAT NEITHER TIER MODELS — and neither does the CONTROL, verified against
 * the 6.5.0 source: `used` is set from `!layer.isHidden(zoom)` alone, so these
 * make a source render nothing while the on-screen control still credits it:
 *
 *   - a layer `filter` that matches no feature (#1553 candidate 2: the control
 *     counts such a source used and shows its credit, so PARITY with the
 *     control means counting it shown here too — evaluating filters ourselves
 *     would open a divergence, not close one)
 *   - zero opacity, or paint that renders invisibly
 *   - tiles that are empty, absent, or outside the viewport
 *
 * And two that are tier 2's alone:
 *
 *   - anything not in the serialized style, since `getStyle()` is the input
 *   - timing: MapLibre recomputes per frame, this reads once at capture
 *
 * Every gap errs toward calling a source SHOWN, which is the safe way to be
 * wrong: the answer only ORDERS the credit list, so a source it misjudges is
 * mis-sorted, never dropped.
 */
interface LiveTileManagerLike {
  used?: unknown;
  usedForTerrain?: unknown;
}

/**
 * feat(#1553): the ids MapLibre itself counts used, read from the live flags
 * the on-screen control renders from, or null when the internal collection is
 * not reachable. The truthiness test mirrors the control's own
 * (`tileManager.used || tileManager.usedForTerrain`).
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
  // feat(#1553): the live flags first — this is the state the on-screen
  // control renders from, so the partition cannot drift from it. The model
  // below is the fallback for a map that does not expose them.
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
    // Partitioned rather than sorted, so the style's own order survives inside
    // each group and the result is stable without depending on sort stability.
    const shown = shownSourceIds(map, style);
    const fromShown: string[] = [];
    const fromHidden: string[] = [];
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
      if (decoded) (shown.has(id) ? fromShown : fromHidden).push(decoded);
    }
    // Contained credits are suppressed inside each group and never across
    // them; the exact-duplicate dedupe then runs ACROSS both, so a credit
    // carried by a shown and a hidden source keeps the shown one's position.
    const deduped = dedupe([
      ...suppressContainedCredits(fromShown),
      ...suppressContainedCredits(fromHidden),
    ]);
    if (deduped.length > 0) return deduped;
  }

  const inner = map.getContainer?.()?.querySelector?.(
    '.maplibregl-ctrl-attrib-inner',
  );
  // Derived, not `textContent` — an image-only credit rendered here is just as
  // real as one declared on a source, and reading text off it dropped both.
  const rendered = inner ? elementCreditText(inner) : '';
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
 *               height  width     line     load             (band runs out)
 *   Thumbnail   13px    378px     ~75      6 lines, 33.6%   18 lines, ~1350 chars
 *   OG card     20px    1160px    ~145     4 lines, 14.3%   30 lines, ~4350 chars
 *   PNG export  16px    1016px*   ~169     4 lines, 88px    951 lines, ~161k chars
 *
 *   * the measured 1056px-wide export at dpr 1, less 20px of pad a side.
 *
 * The two crops run out where the scrim reaches the top edge — the band has by
 * then eaten every map pixel there is. The export runs out somewhere else: its
 * canvas is sized AFTER the band is measured, so the band is not competing with
 * the map for a fixed frame, but it is still spending height a browser has to
 * allocate and encode. Its ceiling is the largest canvas a browser will hand
 * back a blob for; see EXPORT_CANVAS_MAX_DIMENSION.
 *
 * Every ceiling above is far clear of the measured real-world credit load —
 * ~3.3x for the thumbnail (411 characters across five providers), ~10x for the
 * OG card, ~400x for the export. But the SUPPORTED input is far larger:
 * `attribution` is `max_length=5000` on the dataset schema and
 * `NonEmptyString5000` on the manifest, a map may carry 200 layers, and 5,000
 * characters alone is roughly 77 lines in a 250px-tall thumbnail. No font size
 * anyone would call legible renders that, so at the contract's maximum
 * something must give.
 *
 * What gives is neither the image nor silence. Past its ceiling each output
 * renders the credits that fit and appends a visible, counted marker naming how
 * many did not (`export.moreCredits`), with the marker itself charged against
 * the line budget. The standard is that no output may SILENTLY drop a credit; a
 * marker inside the image is not silent, and it stops the visible list reading
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

/*
 * The export canvas's own ceiling, and why it has one.
 *
 * fix(#1541 codex P2 round 2): the band's measured height is assigned straight
 * to the export canvas, and #1541 review had ruled that growth UNLIMITED, on
 * the reasoning that the export canvas has no height constraint. Browsers do.
 * Every engine caps a canvas both per side and by total area, and past either
 * one the canvas is unusable with nothing raised to say so: `toBlob` hands back
 * null, the export toasts a failure, and no image is produced at all. At the
 * contract's maximum — 200 layers, each dataset credit up to 5,000 characters —
 * the band alone asked for tens of thousands of pixels of height, so the
 * unlimited ruling turned a partial-credit bug into a total-export-failure bug.
 * A bounded band with a counted marker loses some provider names; an
 * unencodable canvas loses every one of them along with the map.
 *
 * The figures are the SMALLEST measured for any engine in canvas-size's table
 * (jhildenbiddle/canvas-size, src/test-sizes.js), the only published per-engine
 * measurement of these limits:
 *
 *   per side  Chrome 83 65,535 · Chrome 70 and Firefox 63 32,767 · Edge 17 and
 *             IE 11 16,384. We take 16,384: half the floor of any engine this
 *             app supports, and the only browsers that ever enforced it are
 *             retired, so the margin is free.
 *   area      Chrome 70 / Edge 17 / Safari 7-12 (Mac) 16,384² = 268,435,456 ·
 *             Firefox 63 11,180² = 124,992,400 · Safari on iOS 4,096² =
 *             16,777,216. We take iOS Safari's.
 *
 * fix(#1541 codex P2 round 4): iOS Safari's is deliberately conservative, and
 * an earlier revision of this comment named it and then budgeted against the
 * desktop figure anyway. That is a bound that holds only where it was measured:
 * an iPad's 2048x2732 canvas is valid and exports today, and enough supported
 * credits grew it past 8,192px high, `toBlob` returned null, and the credit
 * band broke the very export it was added to. A bound is worth only the worst
 * environment it has to hold in. We do not probe the engine's real capability
 * and we never sniff the user agent, so the cap is the floor of what every
 * supported engine can do.
 *
 * What it costs a desktop export: nothing until the MAP canvas alone is around
 * 4,096x4,096 device pixels. The measured 1056px-wide export still gets 951
 * lines of band; a 4400x2400 canvas (a maximized builder on a 5K display at
 * dpr 2) still gets 41. Past that the fixed blocks have spent the ceiling on
 * their own and the band gets whatever is left, down to nothing — see
 * `attributionBandHeightBudget` for why it does not overrun the cap to keep a
 * line, and what that costs.
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
 * fix(#1541 codex P2 round 5): this used to be floored at one minimum band, so
 * that a canvas whose fixed blocks had eaten the ceiling still got a credit.
 * A floor and a ceiling that did not know about each other: at width 2048, dpr
 * 2 and 8,140px reserved, the ceiling is 8,192, and the floor replaced the
 * remaining 52px with 80 — an 8,220px canvas, past the very area limit the
 * ceiling exists to hold. It defeated the fix it was sitting inside.
 *
 * ACTUAL POSITIVE HEADROOM, never more. Under one line's worth the band
 * declines entirely rather than drawing something invalid, which is the same
 * call `drawAttributionOverlay` makes at `capacity < 1`.
 *
 * The residual, stated rather than hidden: in that window the export carries no
 * credit and no marker, because there is nowhere to put either. It is reachable
 * only when the fixed blocks are within one band-height of the cap — for the
 * 200-layer legend at dpr 2 on an iPad-sized canvas, the legend alone is past
 * the ceiling before the band is measured. Such a canvas is at or over the cap
 * whatever the band does, and the alternative is the one the ceiling was added
 * to prevent: an image that cannot be encoded at all. Collapsing the band's own
 * gaps would buy back a ~40px window; it is not worth threading a variable gap
 * through the measure/draw pair for a window that narrow.
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
 * rather than the credits being cut to fit the canvas — up to `maxHeight`,
 * which is what the browser will still encode. Pass it from
 * `attributionBandHeightBudget`; it is required rather than optional so no
 * future caller can reach the unbounded behaviour by omission.
 */
export function measureAttributionBand(
  ctx: CanvasRenderingContext2D,
  entries: string[],
  opts: { maxWidth: number; dpr: number; maxHeight: number },
): MeasuredAttributionBand {
  const dpr = opts.dpr || 1;
  const fallback = { lines: [], fontPx: BAND_FONT_PX * dpr, height: 0 };
  if (entries.length === 0 || opts.maxWidth <= 0) return fallback;

  // Deduped here as well as inside the fitter, because the overflow marker
  // counts CREDITS and must not count the same one twice.
  const credits = dedupe(entries);
  const fitted = fitAttributionText(ctx, credits, {
    maxWidth: opts.maxWidth,
    fontPx: BAND_FONT_PX * dpr,
  });
  if (fitted.lines.length === 0) return fallback;

  // Past the budget, the same counted marker the two crops use. Below it —
  // every ordinary export, by three orders of magnitude — nothing changes and
  // the band still grows a line at a time.
  let lines = fitted.lines;
  const capacity = attributionBandLineCapacity(opts.maxHeight, dpr);
  if (lines.length > capacity) {
    // No room for even a marker: a band here could only make an already
    // unencodable canvas taller. See `attributionBandHeightBudget`.
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
