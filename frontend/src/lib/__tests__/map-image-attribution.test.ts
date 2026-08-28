/**
 * feat(#1486): the credit line drawn into every rendered map image.
 *
 * The fitter is the only piece with real logic, so it carries most of these
 * tests. Its stub context measures LENGTH-PROPORTIONALLY (`chars * 0.5 *
 * fontPx`): a constant-width stub cannot exercise a wrap boundary at all,
 * which is how #1541's dropped credits went unseen at this level.
 */
import { describe, it, expect, vi } from 'vitest';
import {
  attributionBandHeightBudget,
  attributionBandLineCapacity,
  drawAttributionBand,
  drawAttributionOverlay,
  exportCanvasHeightCeiling,
  fitAttributionText,
  measureAttributionBand,
  overlayLineCapacity,
  readRenderedAttribution,
  EXPORT_CANVAS_MAX_AREA,
  EXPORT_CANVAS_MAX_DIMENSION,
  OG_ATTRIBUTION,
  THUMBNAIL_ATTRIBUTION,
} from '../map-image-attribution';
import { MAP_COLORS } from '../map-colors';

function fontPxOf(font: string): number {
  const match = /(\d+(?:\.\d+)?)px/.exec(font);
  return match ? parseFloat(match[1]) : 12;
}

/** A 2D context whose text metrics respond to both the string and the font
 *  size, so wrapping and line growth are observable. */
function makeCtx() {
  const ctx = {
    font: '',
    fillStyle: '' as string,
    strokeStyle: '',
    textBaseline: '',
    textAlign: '',
    fillText: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    fill: vi.fn(),
    measureText: vi.fn((text: string) => ({
      width: text.length * 0.5 * fontPxOf(ctx.font),
    })),
  };
  return ctx;
}

function makeCanvas(width: number, height: number, ctx: unknown) {
  return {
    width,
    height,
    getContext: vi.fn(() => ctx),
  } as unknown as HTMLCanvasElement;
}

function mapWithControl(text: string | null) {
  const container = document.createElement('div');
  if (text !== null) {
    const inner = document.createElement('div');
    inner.className = 'maplibregl-ctrl-attrib-inner';
    inner.textContent = text;
    container.appendChild(inner);
  }
  return { getContainer: () => container };
}

describe('readRenderedAttribution', () => {
  /* fix(#1541 codex P2): the credit list is never re-derived by splitting a
   * joined string. ` | ` is legal content inside a 5,000-character credit, so
   * any delimiter round-trip can cut one credit into two — or, via the dedupe,
   * delete half of one outright. Structured sources first; the rendered control
   * only as one opaque entry. */

  it('prefers the structured source list, one entry per source', () => {
    const map = {
      ...mapWithControl('ignored'),
      getStyle: () => ({
        sources: {
          base: { attribution: '© Basemap Co' },
          dem: { attribution: '© swisstopo' },
          quiet: { attribution: null },
          none: null,
        },
      }),
    };
    expect(readRenderedAttribution(map)).toEqual(['© Basemap Co', '© swisstopo']);
  });

  it('reads the LIVE source attribution, which the serialized spec can lack', () => {
    // Measured on the shipped OpenFreeMap basemap: the spec says null while the
    // live source carries the credit, because a vector source loaded from a
    // TileJSON `url` receives its attribution in that response. Reading the
    // spec alone dropped every basemap credit whenever a dataset declared one.
    const map = {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: { basemap: { attribution: null }, dem: { attribution: '© swisstopo' } },
      }),
      getSource: (id: string) =>
        id === 'basemap' ? { attribution: '<a href="#">© OpenMapTiles</a>' } : undefined,
    };
    expect(readRenderedAttribution(map)).toEqual(['© OpenMapTiles', '© swisstopo']);
  });

  it('falls back to the serialized spec for a source the map has not instantiated', () => {
    const map = {
      ...mapWithControl(null),
      getStyle: () => ({ sources: { a: { attribution: '© From spec' } } }),
      getSource: () => undefined,
    };
    expect(readRenderedAttribution(map)).toEqual(['© From spec']);
  });

  it('never splits a credit that contains the separator as content', () => {
    const credit = '© Acme | © Acme';
    const map = {
      ...mapWithControl(null),
      getStyle: () => ({ sources: { a: { attribution: credit } } }),
    };
    // One credit, whole. Splitting produced two identical fragments that the
    // dedupe then collapsed to one, deleting half a real credit.
    expect(readRenderedAttribution(map)).toEqual([credit]);
  });

  it('keeps two distinct credits that share a separator-containing prefix', () => {
    const map = {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: {
          a: { attribution: '© Acme | Division One' },
          b: { attribution: '© Acme | Division Two' },
        },
      }),
    };
    expect(readRenderedAttribution(map)).toEqual([
      '© Acme | Division One',
      '© Acme | Division Two',
    ]);
  });

  it('dedupes identical source credits, which is one credit not two', () => {
    const map = {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: { a: { attribution: '© Same' }, b: { attribution: '© Same' } },
      }),
    };
    expect(readRenderedAttribution(map)).toEqual(['© Same']);
  });

  it('decodes entities and anchors without parsing live markup', () => {
    const map = {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: {
          a: { attribution: '<a href="https://osm.org">OpenStreetMap</a> contributors' },
          b: { attribution: 'Rand &amp; McNally' },
        },
      }),
    };
    expect(readRenderedAttribution(map)).toEqual([
      'OpenStreetMap contributors',
      'Rand & McNally',
    ]);
  });

  it('falls back to the rendered control as ONE opaque entry, never split', () => {
    const joined = '© OpenFreeMap | © OpenMapTiles | © OpenStreetMap contributors';
    expect(readRenderedAttribution(mapWithControl(joined))).toEqual([joined]);
  });

  it('falls back to the control when no source declares a credit', () => {
    const map = {
      ...mapWithControl('© From the control'),
      getStyle: () => ({ sources: { a: { attribution: null }, b: {} } }),
    };
    expect(readRenderedAttribution(map)).toEqual(['© From the control']);
  });

  it('returns nothing when neither source is available', () => {
    expect(readRenderedAttribution(mapWithControl(null))).toEqual([]);
    expect(readRenderedAttribution({})).toEqual([]);
    expect(readRenderedAttribution({ ...mapWithControl('   ') })).toEqual([]);
  });

  /* fix(#1541 codex P2 round 3): a credit is HTML — `BasemapEntry.attribution`
   * permits it and MapLibre renders it — so a provider may credit itself with a
   * logo. An image's text alternative is not DOM text, so a `textContent` read
   * returned '' and the source was skipped: the interactive map showed the
   * credit and every exported image did not. Both readers derive text from the
   * markup now, preserving the alternatives a sighted user is reading. */

  function sourcesMap(...attributions: (string | null)[]) {
    return {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: Object.fromEntries(
          attributions.map((attribution, i) => [`src-${i}`, { attribution }]),
        ),
      }),
    };
  }

  it('takes an image credit from its alt text', () => {
    expect(
      readRenderedAttribution(
        sourcesMap('<img src="https://tiles.example.com/logo.svg" alt="© Provider">'),
      ),
    ).toEqual(['© Provider']);
  });

  it('takes aria-label and title when there is no alt', () => {
    expect(
      readRenderedAttribution(
        sourcesMap(
          '<img src="https://a.example/l.png" aria-label="© Aria Provider">',
          '<img src="https://b.example/l.png" title="© Title Provider">',
          // The generic element rule, which is what makes a labelled SVG work
          // without this module ever naming SVG.
          '<svg role="img" aria-label="© Svg Provider"></svg>',
          '<svg><title>© Svg Title Provider</title></svg>',
        ),
      ),
    ).toEqual([
      '© Aria Provider',
      '© Title Provider',
      '© Svg Provider',
      '© Svg Title Provider',
    ]);
  });

  it('prefers aria-label over alt over title', () => {
    // fix(#1541 codex P2 round 7): ARIA OVERRIDES the host-language attribute
    // in the accessible name computation; it does not follow it.
    expect(
      readRenderedAttribution(
        sourcesMap('<img src="https://a.example/l.png" alt="© Alt" aria-label="© Aria" title="© Title">'),
      ),
    ).toEqual(['© Aria']);
    expect(
      readRenderedAttribution(
        sourcesMap('<img src="https://a.example/l.png" alt="© Alt" title="© Title">'),
      ),
    ).toEqual(['© Alt']);
  });

  it('draws the ARIA credit, not the generic alt text a logo carries', () => {
    // The realistic markup: alt names the picture, aria-label carries the
    // credit. The old order drew "Provider logo" into every exported image.
    expect(
      readRenderedAttribution(
        sourcesMap('<img src="https://a.example/l.png" alt="Provider logo" aria-label="© Provider 2026">'),
      ),
    ).toEqual(['© Provider 2026']);
  });

  it('keeps text around an image credit rather than replacing it', () => {
    expect(
      readRenderedAttribution(
        sourcesMap('Imagery <img src="https://a.example/l.png" alt="© Provider"> and data'),
      ),
    ).toEqual(['Imagery © Provider and data']);
  });

  it('does not credit a labelled wrapper twice', () => {
    // The element fallback is checked AFTER the children, so an <a title="…">
    // around real text contributes its text once, not its text and its title.
    expect(
      readRenderedAttribution(
        sourcesMap('<a href="https://osm.org" title="© OpenStreetMap">© OpenStreetMap contributors</a>'),
      ),
    ).toEqual(['© OpenStreetMap contributors']);
  });

  /* The class, not just the reported site: `attribution` permits HTML
   * generally, and a `textContent` read mangles more than images. */

  it('separates credits that a break or block would show on their own lines', () => {
    expect(
      readRenderedAttribution(
        sourcesMap(
          '© Provider A<br>© Provider B',
          '<div>© Block A</div><div>© Block B</div>',
          '<ul><li>© List A</li><li>© List B</li></ul>',
        ),
      ),
    ).toEqual([
      '© Provider A | © Provider B',
      '© Block A | © Block B',
      '© List A | © List B',
    ]);
  });

  it('collapses source whitespace and nesting into one legible line', () => {
    expect(
      readRenderedAttribution(
        sourcesMap('<span>  <b>©</b>\n  <a href="#">Nested\tProvider</a>  </span>'),
      ),
    ).toEqual(['© Nested Provider']);
  });

  it('still decodes entities, which are text not markup', () => {
    expect(readRenderedAttribution(sourcesMap('Rand &amp; McNally &copy; 2026'))).toEqual([
      'Rand & McNally © 2026',
    ]);
  });

  it('honours alt="" as the decorative image its author declared', () => {
    // Explicitly decorative, so it is not a credit and gets no placeholder.
    // The one case where an image yields nothing by design.
    expect(
      readRenderedAttribution(
        sourcesMap('© Provider <img src="https://a.example/spacer.gif" alt="">'),
      ),
    ).toEqual(['© Provider']);
  });

  /* An image with NO alternative at all cannot be named. The decision is that
   * it renders a placeholder rather than vanishing: an unnamed credit is still
   * a credit, and the standard is that no output may silently drop one. */

  it('names an unnamed image credit by its host rather than dropping it', () => {
    expect(
      readRenderedAttribution(sourcesMap('<img src="https://tiles.acme.com/logo.png">')),
    ).toEqual(['(image credit: tiles.acme.com)']);
  });

  it('keeps two unnamed image credits from different hosts distinct', () => {
    // A bare placeholder for both would dedupe to one, dropping a credit.
    expect(
      readRenderedAttribution(
        sourcesMap(
          '<img src="https://a.example.com/logo.png">',
          '<img src="https://b.example.com/logo.png">',
        ),
      ),
    ).toEqual(['(image credit: a.example.com)', '(image credit: b.example.com)']);
  });

  it('falls back to a bare placeholder for an image with no usable host', () => {
    expect(
      readRenderedAttribution(sourcesMap('<img src="data:image/gif;base64,R0lGOD">')),
    ).toEqual(['(image credit)']);
    expect(readRenderedAttribution(sourcesMap('<img>'))).toEqual(['(image credit)']);
  });

  it('derives the control fallback the same way, not from textContent', () => {
    // The sibling reader. Fixing one and leaving the other still loses the
    // credit, on exactly the maps that reach the fallback.
    const container = document.createElement('div');
    const inner = document.createElement('div');
    inner.className = 'maplibregl-ctrl-attrib-inner';
    inner.innerHTML =
      '<a href="https://provider.example"><img src="https://provider.example/l.svg" alt="© Control Provider"></a>';
    container.appendChild(inner);
    expect(readRenderedAttribution({ getContainer: () => container })).toEqual([
      '© Control Provider',
    ]);
  });

  it('returns nothing only when the control declares nothing at all', () => {
    const control = (html: string) => {
      const container = document.createElement('div');
      const inner = document.createElement('div');
      inner.className = 'maplibregl-ctrl-attrib-inner';
      inner.innerHTML = html;
      container.appendChild(inner);
      return { getContainer: () => container };
    };
    // No elements and no text: nothing was declared to lose.
    expect(readRenderedAttribution(control('   '))).toEqual([]);
    // But a lone decorative image IS a declaration; see the source-level rule.
    expect(readRenderedAttribution(control('<img src="https://a.example/l.gif" alt="">'))).toEqual([
      '(image credit: a.example)',
    ]);
    // And so is markup that renders without naming itself (round 8).
    expect(readRenderedAttribution(control('<svg><path d="M0 0h4v4H0z"/></svg>'))).toEqual([
      '(image credit)',
    ]);
  });

  /* fix(#1541 codex P2 round 4): honouring alt="" opened the gap beside it.
   * The shortcut ran BEFORE the ARIA alternatives, and a source whose whole
   * attribution reduced to nothing was dropped from the list entirely — so it
   * was counted nowhere, marker included. */

  it('lets an ARIA alternative override an empty alt', () => {
    // alt="" means decorative only when nothing else names the image. These
    // all have an accessible name, so MapLibre renders a credit and so do we.
    expect(
      readRenderedAttribution(
        sourcesMap(
          '<img src="https://a.example/l.png" alt="" aria-label="© Aria Provider">',
          '<img src="https://b.example/l.png" alt="" title="© Title Provider">',
          '<img src="https://c.example/l.png" alt="  " aria-label="© Spaces Provider">',
        ),
      ),
    ).toEqual(['© Aria Provider', '© Title Provider', '© Spaces Provider']);
  });

  it('still drops a decorative image from INSIDE a credit that has text', () => {
    // The alt="" rule is intact where it belongs: a spacer next to real text
    // adds nothing. The placeholder is a source-level floor, not a per-image one.
    expect(
      readRenderedAttribution(
        sourcesMap('© Provider <img src="https://a.example/spacer.gif" alt="">'),
      ),
    ).toEqual(['© Provider']);
  });

  it('counts a source whose whole credit is a decorative image, rather than swallowing it', () => {
    const credits = readRenderedAttribution(
      sourcesMap('© Named Provider', '<img src="https://logo.example.com/l.gif" alt="">'),
    );
    // Two sources declared a credit, so two credits reach the images — the
    // second un-nameable but present, and therefore counted by the marker.
    expect(credits).toEqual(['© Named Provider', '(image credit: logo.example.com)']);
  });

  /* fix(#1541 codex P2 round 8): the unnameable-credit fallback recognised
   * only <img>, so an unlabelled inline <svg> or a CSS-backed logo — both of
   * which MapLibre renders visibly — derived no text, matched no image, and
   * vanished without even reaching the marker. The test is now the question
   * itself: did the declaration put something on screen we could not name? */

  it('counts an unlabelled inline SVG credit rather than dropping it', () => {
    const credits = readRenderedAttribution(
      sourcesMap('© Named Provider', '<svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'),
    );
    expect(credits).toEqual(['© Named Provider', '(image credit)']);
  });

  it('counts a CSS-backed logo with no element we could name', () => {
    expect(
      readRenderedAttribution(sourcesMap('<div class="provider-logo"></div>')),
    ).toEqual(['(image credit)']);
  });

  it('still names an image by its host when the declaration has one', () => {
    // The image path keeps its better placeholder even when other elements
    // are present, since a host is the only identifying text available.
    expect(
      readRenderedAttribution(
        sourcesMap('<span><svg></svg><img src="https://tiles.acme.com/l.png"></span>'),
      ),
    ).toEqual(['(image credit: tiles.acme.com)']);
  });

  it('drops a declaration with no elements and no text', () => {
    // The only genuinely empty case left: nothing was declared to lose.
    expect(readRenderedAttribution(sourcesMap('   ', '\n\t'))).toEqual([]);
  });

  /* feat(#1553 candidate 4): <object>, <embed>, <iframe> and <video> render
   * perfectly visibly in the on-screen control — MapLibre's sanitizer strips
   * only <script>, on* handlers and javascript:/data: URLs — and none of them
   * derives DOM text. They take the same treatment as an unnamed <img>:
   * accessible alternatives first, then the host-derived placeholder. */

  it('names an unnamed object logo by its host, like an image', () => {
    expect(
      readRenderedAttribution(sourcesMap('<object data="https://assets.acme.com/logo.svg"></object>')),
    ).toEqual(['(image credit: assets.acme.com)']);
  });

  it('names embed, iframe and video credits the same way', () => {
    expect(
      readRenderedAttribution(
        sourcesMap(
          '<embed src="https://a.example.com/logo.svg">',
          '<iframe src="https://b.example.com/badge"></iframe>',
          '<video poster="https://c.example.com/still.jpg"></video>',
        ),
      ),
    ).toEqual([
      '(image credit: a.example.com)',
      '(image credit: b.example.com)',
      '(image credit: c.example.com)',
    ]);
  });

  it('lets an embed\'s accessible alternative outrank its host placeholder', () => {
    // The generic-element rule already reads aria-label/title on these; the
    // placeholder is only for an embed nothing names.
    expect(
      readRenderedAttribution(
        sourcesMap('<object data="https://assets.acme.com/logo.svg" aria-label="© Acme 2026"></object>'),
      ),
    ).toEqual(['© Acme 2026']);
  });

  it('lets object fallback content, which is DOM text, win over the placeholder', () => {
    expect(
      readRenderedAttribution(
        sourcesMap('<object data="https://assets.acme.com/logo.svg">© Acme Provider</object>'),
      ),
    ).toEqual(['© Acme Provider']);
  });

  it('keeps text around an unnamed embed rather than replacing or dropping it', () => {
    // The inline mirror of the <img> rule: the embed is on screen beside the
    // text, so the derivation says so.
    expect(
      readRenderedAttribution(
        sourcesMap('© Provider <embed src="https://cdn.acme.com/logo.svg">'),
      ),
    ).toEqual(['© Provider (image credit: cdn.acme.com)']);
  });

  it('falls back to the bare placeholder for an embed with no usable URL', () => {
    // data: URIs are what MapLibre's sanitizer strips anyway, so a host is
    // never derived from one.
    expect(
      readRenderedAttribution(sourcesMap('<object data="data:image/svg+xml,<svg/>"></object>')),
    ).toEqual(['(image credit)']);
    // <video> tries src first, then poster.
    expect(
      readRenderedAttribution(sourcesMap('<video src="blob:whatever"></video>')),
    ).toEqual(['(image credit)']);
  });

  /* fix(#1541 codex P1): "no `used` gating — over-crediting is the safe
   * direction" was true while the band could grow without limit. Once the
   * outputs gained a capacity limit and a prefix fit, an unused credit stopped
   * being extra information and became a credit that DISPLACES a required one,
   * and prefix-fitting makes position decisive. Shown sources sort first. */

  /** A style with layers, so the reader can tell shown sources from hidden. */
  function layeredMap(
    sources: Record<string, string>,
    layers: { source: string; hidden?: boolean }[],
  ) {
    return {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: Object.fromEntries(
          Object.entries(sources).map(([id, attribution]) => [id, { attribution }]),
        ),
        layers: layers.map(({ source, hidden }, i) => ({
          id: `layer-${i}`,
          source,
          layout: hidden ? { visibility: 'none' } : {},
        })),
      }),
    };
  }

  it('puts shown sources ahead of hidden ones, whatever order the style declares', () => {
    const credits = readRenderedAttribution(
      layeredMap(
        { hiddenFirst: '© Hidden Provider', basemap: '© Visible Provider' },
        [
          { source: 'hiddenFirst', hidden: true },
          { source: 'basemap' },
        ],
      ),
    );
    // The hidden source is declared FIRST and would otherwise lead — which is
    // what let it consume a bounded budget and reduce the visible provider to
    // a bare marker.
    expect(credits).toEqual(['© Visible Provider', '© Hidden Provider']);
  });

  it('credits a hidden source when there is room, rather than filtering it out', () => {
    // Ordering, not filtering: a source hidden at capture time can still be
    // part of what the map is of, so nothing is dropped while it fits.
    const credits = readRenderedAttribution(
      layeredMap({ a: '© Shown', b: '© Hidden' }, [{ source: 'a' }, { source: 'b', hidden: true }]),
    );
    expect(credits).toEqual(['© Shown', '© Hidden']);
  });

  it('keeps the style order inside each group', () => {
    const credits = readRenderedAttribution(
      layeredMap(
        { h1: '© Hidden One', s1: '© Shown One', h2: '© Hidden Two', s2: '© Shown Two' },
        [
          { source: 'h1', hidden: true },
          { source: 's1' },
          { source: 'h2', hidden: true },
          { source: 's2' },
        ],
      ),
    );
    expect(credits).toEqual(['© Shown One', '© Shown Two', '© Hidden One', '© Hidden Two']);
  });

  it('treats a source no layer references as hidden', () => {
    const credits = readRenderedAttribution(
      layeredMap({ orphan: '© Orphan', live: '© Live' }, [{ source: 'live' }]),
    );
    expect(credits).toEqual(['© Live', '© Orphan']);
  });

  it('keeps the shown position for a credit that both a shown and a hidden source carry', () => {
    // Deduped across the groups, not within them, or the hidden copy would win
    // the leading slot back.
    const credits = readRenderedAttribution(
      layeredMap(
        { hidden: '© Shared', other: '© Other', shown: '© Shared' },
        [
          { source: 'hidden', hidden: true },
          { source: 'other' },
          { source: 'shown' },
        ],
      ),
    );
    expect(credits).toEqual(['© Other', '© Shared']);
  });

  /* fix(#1541 codex P2 round 7): the zoom range is the other half of
   * MapLibre's own `isHidden`, so a visible layer outside its range leaves its
   * source unused — and could displace the credit for what IS rendering. */

  function zoomedMap(
    sources: Record<string, string>,
    layers: { source: string; minzoom?: number; maxzoom?: number }[],
    zoom: number,
  ) {
    return {
      ...mapWithControl(null),
      getZoom: () => zoom,
      getStyle: () => ({
        sources: Object.fromEntries(
          Object.entries(sources).map(([id, attribution]) => [id, { attribution }]),
        ),
        layers: layers.map(({ source, minzoom, maxzoom }, i) => ({
          id: `layer-${i}`,
          source,
          layout: {},
          ...(minzoom === undefined ? {} : { minzoom }),
          ...(maxzoom === undefined ? {} : { maxzoom }),
        })),
      }),
    };
  }

  it('treats a visible layer outside its zoom range as not shown', () => {
    const credits = readRenderedAttribution(
      zoomedMap(
        { tooDeep: '© Out Of Range', live: '© In Range' },
        [
          { source: 'tooDeep', minzoom: 14 },
          { source: 'live' },
        ],
        8,
      ),
    );
    expect(credits).toEqual(['© In Range', '© Out Of Range']);
  });

  it('uses MapLibre\'s own boundary semantics: minzoom inclusive, maxzoom exclusive', () => {
    // At zoom 10 exactly: a layer with minzoom 10 renders, one with maxzoom 10
    // does not. Mirrors `isHidden`: zoom < minzoom || zoom >= maxzoom.
    const atBoundary = readRenderedAttribution(
      zoomedMap(
        { ending: '© Ends Here', starting: '© Starts Here' },
        [
          { source: 'ending', maxzoom: 10 },
          { source: 'starting', minzoom: 10 },
        ],
        10,
      ),
    );
    expect(atBoundary).toEqual(['© Starts Here', '© Ends Here']);
  });

  it('treats a zero bound as no bound, as MapLibre does', () => {
    // `!!(this.minzoom && ...)` — a zero minzoom is falsy and never hides.
    const credits = readRenderedAttribution(
      zoomedMap({ zeroBound: '© Zero Min', other: '© Other' }, [
        { source: 'zeroBound', minzoom: 0 },
        { source: 'other' },
      ], 0),
    );
    expect(credits).toEqual(['© Zero Min', '© Other']);
  });

  it('leaves every layer in range when the map exposes no zoom', () => {
    // Over-report rather than demote: the partial mocks the builder suites
    // pass have no getZoom, and a missing signal must not hide a credit.
    const credits = readRenderedAttribution(
      layeredMap({ a: '© Shown', b: '© Also Shown' }, [{ source: 'a' }, { source: 'b' }]),
    );
    expect(credits).toEqual(['© Shown', '© Also Shown']);
  });

  it('counts a filter-excluded source as shown, exactly as the control does', () => {
    // feat(#1553 candidate 2), settled by parity rather than by evaluation:
    // MapLibre sets `used` from `!layer.isHidden(zoom)` alone (verified in the
    // 6.5.0 source), so a layer whose filter matches no feature still puts its
    // source's credit in the on-screen control. Matching the control means
    // counting it shown here too; evaluating filters ourselves would OPEN a
    // divergence, not close one.
    const credits = readRenderedAttribution({
      ...mapWithControl(null),
      getStyle: () => ({
        sources: {
          filtered: { attribution: '© Filtered But Credited' },
          plain: { attribution: '© Plain' },
        },
        layers: [
          { id: 'l0', source: 'filtered', layout: {}, filter: ['==', ['get', 'kind'], 'nothing-has-this'] },
          { id: 'l1', source: 'plain', layout: {} },
        ],
      }),
    });
    expect(credits).toEqual(['© Filtered But Credited', '© Plain']);
  });

  /* feat(#1553 candidate 1): the priority set reads MapLibre's OWN live
   * `used`/`usedForTerrain` flags — the exact state the on-screen control
   * renders from (`map.style.tileManagers` in 6.5.0) — whenever the map
   * exposes them, so the partition cannot drift from the control. The modeled
   * signals below survive only as the fallback for a partial map, or for the
   * next time MapLibre renames the internal collection (it already went
   * `sourceCaches` → `tileManagers` once). */

  function liveFlagMap(
    sources: Record<string, string>,
    managers: Record<string, { used?: boolean; usedForTerrain?: boolean }> | 'absent',
    layers?: { source: string; hidden?: boolean }[],
  ) {
    const layerDefs: { source: string; hidden?: boolean }[] =
      layers ?? Object.keys(sources).map((source) => ({ source }));
    return {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: Object.fromEntries(
          Object.entries(sources).map(([id, attribution]) => [id, { attribution }]),
        ),
        layers: layerDefs.map(({ source, hidden }, i) => ({
          id: `layer-${i}`,
          source,
          layout: hidden ? { visibility: 'none' } : {},
        })),
      }),
      ...(managers === 'absent' ? {} : { style: { tileManagers: managers } }),
    };
  }

  it('reads the live used flags in preference to the modeled signals', () => {
    // Both layers are visible and in range, so the model would call both
    // shown. MapLibre itself says one is unused — its judgement wins, and the
    // unused credit is ordered back, never dropped.
    const credits = readRenderedAttribution(
      liveFlagMap(
        { idle: '© Live-Unused Provider', busy: '© Live-Used Provider' },
        { idle: { used: false }, busy: { used: true } },
      ),
    );
    expect(credits).toEqual(['© Live-Used Provider', '© Live-Unused Provider']);
  });

  it('counts a live usedForTerrain source as shown, as the control does', () => {
    // Terrain through the flag itself, with no layer reference and no
    // getTerrain on the mock: exactly what the control reads.
    const credits = readRenderedAttribution(
      liveFlagMap(
        { dem: '© swisstopo swissALTI3D', hiddenSrc: '© Hidden Provider' },
        { dem: { usedForTerrain: true }, hiddenSrc: { used: false } },
        [{ source: 'hiddenSrc' }],
      ),
    );
    expect(credits).toEqual(['© swisstopo swissALTI3D', '© Hidden Provider']);
  });

  it('lets a live used flag overrule a hidden layer', () => {
    // Live REPLACES the model rather than intersecting with it: whatever made
    // MapLibre count the source used (another layer, terrain, a state the
    // model cannot see), the control credits it, so the image leads with it.
    const credits = readRenderedAttribution(
      liveFlagMap(
        { contested: '© Contested Provider', plain: '© Plain Provider' },
        { contested: { used: true }, plain: { used: false } },
        [{ source: 'contested', hidden: true }, { source: 'plain' }],
      ),
    );
    expect(credits).toEqual(['© Contested Provider', '© Plain Provider']);
  });

  it('falls back to the modeled signals when the live collection is absent', () => {
    // No `style` at all (every partial mock the builder suites pass) …
    const modelOnly = readRenderedAttribution(
      liveFlagMap({ a: '© Shown', b: '© Hidden' }, 'absent', [
        { source: 'a' },
        { source: 'b', hidden: true },
      ]),
    );
    expect(modelOnly).toEqual(['© Shown', '© Hidden']);
    // … and a style whose collection is missing or reshaped (the rename risk:
    // `sourceCaches` → `tileManagers` has already happened once).
    for (const style of [{}, { tileManagers: null }, { tileManagers: 'renamed-away' }]) {
      const credits = readRenderedAttribution({
        ...liveFlagMap({ a: '© Shown', b: '© Hidden' }, 'absent', [
          { source: 'a' },
          { source: 'b', hidden: true },
        ]),
        style,
      });
      expect(credits, `style shape: ${JSON.stringify(style)}`).toEqual(['© Shown', '© Hidden']);
    }
  });

  it('treats an empty live collection as a live answer, not a fallback', () => {
    // Sources are declared but none is instantiated, so the control shows
    // nothing. Everything goes to the hidden group in style order — still
    // credited while there is room, per the ordering-not-filtering rule. The
    // model would instead have promoted `visible` ahead of `declared-first`.
    const credits = readRenderedAttribution(
      liveFlagMap(
        { hiddenByLayer: '© Declared First', visible: '© Visible By Layer' },
        {},
        [{ source: 'hiddenByLayer', hidden: true }, { source: 'visible' }],
      ),
    );
    expect(credits).toEqual(['© Declared First', '© Visible By Layer']);
  });

  it('ignores a manager entry that is not an object', () => {
    const credits = readRenderedAttribution({
      ...mapWithControl(null),
      getStyle: () => ({ sources: { a: { attribution: '© Provider' } } }),
      style: { tileManagers: { a: null } },
    });
    expect(credits).toEqual(['© Provider']);
  });

  /* fix(#1541 codex P2 round 8): MapLibre's AttributionControl drops an entry
   * another entry contains whole, so `© Acme` beside `© Acme — CC BY 4.0`
   * showed once on screen and twice in the image. Asymmetric failure: source
   * order could let the redundant fragment take the budget and leave the
   * complete licensing statement as the thing elided. */

  it('drops a credit another credit already contains whole', () => {
    expect(
      readRenderedAttribution(sourcesMap('© Acme', '© Acme — CC BY 4.0')),
    ).toEqual(['© Acme — CC BY 4.0']);
    // Order-independent: the fragment goes whichever side it is declared.
    expect(
      readRenderedAttribution(sourcesMap('© Acme — CC BY 4.0', '© Acme')),
    ).toEqual(['© Acme — CC BY 4.0']);
  });

  it('keeps two credits that merely share a prefix', () => {
    expect(
      readRenderedAttribution(sourcesMap('© Acme Northern', '© Acme Southern')),
    ).toEqual(['© Acme Northern', '© Acme Southern']);
  });

  it('never lets a hidden credit suppress a shown one', () => {
    // The caveat that matters: suppression runs WITHIN a group. Across them it
    // would delete the shown text and leave the superstring in the group the
    // marker elides first — the crowding-out bug through a different door.
    const credits = readRenderedAttribution(
      layeredMap(
        { hiddenLong: '© Acme — CC BY 4.0', shownShort: '© Acme' },
        [
          { source: 'hiddenLong', hidden: true },
          { source: 'shownShort' },
        ],
      ),
    );
    expect(credits).toEqual(['© Acme', '© Acme — CC BY 4.0']);
  });

  it('does not collapse two identical credits into nothing', () => {
    // Strictly-longer containment, so equal strings cannot suppress each
    // other; the exact dedupe owns that case and keeps one.
    expect(readRenderedAttribution(sourcesMap('© Same', '© Same'))).toEqual(['© Same']);
  });

  it('collapses raw-distinct credits whose rendered text is identical', () => {
    // chore(#1553 candidate 3): the one DELIBERATE divergence from the
    // control's dedupe, which compares raw HTML and renders `© OSM | © OSM`
    // for two anchors differing only in href. Text is what the image renders,
    // so text-identical credits are visual duplicates here and keep one line.
    expect(
      readRenderedAttribution(
        sourcesMap(
          '<a href="https://www.openstreetmap.org/copyright">© OSM</a>',
          '<a href="https://osm.org/copyright">© OSM</a>',
        ),
      ),
    ).toEqual(['© OSM']);
  });

  it('suppresses a chain of containments down to the fullest statement', () => {
    expect(
      readRenderedAttribution(
        sourcesMap('© Acme', '© Acme — CC BY', '© Acme — CC BY 4.0, all rights reserved'),
      ),
    ).toEqual(['© Acme — CC BY 4.0, all rights reserved']);
  });

  it('leaves a style with no layers in its declared order', () => {
    // Nothing to sort by, and no reason to invent one.
    expect(readRenderedAttribution(sourcesMap('© First', '© Second'))).toEqual([
      '© First',
      '© Second',
    ]);
  });

  /* fix(#1541 codex P2 round 6): terrain renders with NO style layer of its
   * own — `ensureRasterDemTerrainSource` (map-sync.ts) creates an attributed
   * source and lets MapLibre count it through `usedForTerrain` — so defining
   * "shown" as "referenced by a layer" put the credit for plainly visible 3D
   * relief in the hidden group, behind credits for invisible content. */

  /** The terrain source id map-sync creates; it appears in `sources` and in
   *  `getTerrain()`, and in no layer. */
  const TERRAIN_SRC = 'geolens-terrain-dem';

  function terrainMap(
    sources: Record<string, string>,
    layers: { source: string; hidden?: boolean }[],
    terrain: string | null = TERRAIN_SRC,
  ) {
    return {
      ...mapWithControl(null),
      getStyle: () => ({
        sources: Object.fromEntries(
          Object.entries(sources).map(([id, attribution]) => [id, { attribution }]),
        ),
        layers: layers.map(({ source, hidden }, i) => ({
          id: `layer-${i}`,
          source,
          layout: hidden ? { visibility: 'none' } : {},
        })),
      }),
      getTerrain: () => (terrain ? { source: terrain } : null),
    };
  }

  it('treats the terrain source as shown though no layer references it', () => {
    const credits = readRenderedAttribution(
      terrainMap(
        // Declared in the order map-sync creates them: layer sources first,
        // the terrain source after, which is what put it behind the hidden one.
        { hiddenSrc: '© Hidden Provider', [TERRAIN_SRC]: '© swisstopo swissALTI3D' },
        [{ source: 'hiddenSrc', hidden: true }],
      ),
    );
    expect(credits).toEqual(['© swisstopo swissALTI3D', '© Hidden Provider']);
  });

  it('leaves the terrain source hidden when terrain is off', () => {
    const credits = readRenderedAttribution(
      terrainMap(
        { [TERRAIN_SRC]: '© swisstopo swissALTI3D', shownSrc: '© Visible Provider' },
        [{ source: 'shownSrc' }],
        null,
      ),
    );
    expect(credits).toEqual(['© Visible Provider', '© swisstopo swissALTI3D']);
  });

  it('reads a map that has no getTerrain at all', () => {
    // Every existing caller shape, and the partial mocks the builder suites
    // pass. An absent method is not a terrain-less map crashing.
    expect(
      readRenderedAttribution(
        layeredMap({ a: '© Shown' }, [{ source: 'a' }]),
      ),
    ).toEqual(['© Shown']);
  });

  it('keeps a terrain credit out of the marker in a bounded output', () => {
    // The reported shape, asserted at an output: 3D relief is on screen and a
    // long hidden credit is not, so the marker must elide the hidden one.
    const hidden = `© Hidden Provider ${'licensing statement '.repeat(300)}`.slice(0, 5000);
    const map = terrainMap(
      { hiddenSrc: hidden, [TERRAIN_SRC]: '© swisstopo swissALTI3D' },
      [{ source: 'hiddenSrc', hidden: true }],
    );
    const ctx = makeCtx();
    drawAttributionOverlay(
      makeCanvas(400, 250, ctx),
      readRenderedAttribution(map),
      THUMBNAIL_ATTRIBUTION,
    );
    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(drawn.join(' ')).toContain('© swisstopo swissALTI3D');
    expect(drawn[drawn.length - 1]).toBe('+1 more credit');
  });

  it('does not let a hidden credit crowd a visible one out of a bounded output', () => {
    // The whole point, asserted at an output rather than at the reader: a
    // 5,000-character hidden credit against a 250px thumbnail.
    const hidden = `© Hidden Provider ${'licensing statement '.repeat(300)}`.slice(0, 5000);
    const map = layeredMap({ hiddenSrc: hidden, shownSrc: '© Visible Provider' }, [
      { source: 'hiddenSrc', hidden: true },
      { source: 'shownSrc' },
    ]);
    const ctx = makeCtx();
    drawAttributionOverlay(
      makeCanvas(400, 250, ctx),
      readRenderedAttribution(map),
      THUMBNAIL_ATTRIBUTION,
    );
    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(drawn.join(' ')).toContain('© Visible Provider');
    // The hidden one is what the marker elides, which is the correct loss.
    expect(drawn[drawn.length - 1]).toBe('+1 more credit');
  });
});

/* fix(#1541 codex P1 x2): every output used to elide — the export band via a
 * two-line budget that contradicted its own docstring, the two crops via
 * `maxLines: 1`. The measured live failure was five credits on a 1056px export
 * losing two, the basemap's included. There is no elision path left, and these
 * pin that to behaviour rather than to a comment. */

/** The exact credit set that produced the measured live failure. */
const REAL_CREDITS = [
  'MapLibre',
  '© OpenStreetMap contributors, climbing route geometry retrieved via the Overpass API, licensed under ODbL 1.0',
  '© U.S. Geological Survey Earthquake Hazards Program, ANSS Comprehensive Earthquake Catalog (ComCat), public domain',
  '© swisstopo swissALTI3D, 2m lidar digital elevation model, Federal Office of Topography, reproduced with authorisation',
  'OpenFreeMap © OpenMapTiles Data from OpenStreetMap',
];

/** Every character of every entry survived, and nothing was marked as dropped. */
function expectTotal(lines: string[], entries: string[]) {
  const rendered = lines.join(' ');
  for (const entry of entries) {
    expect(rendered, `missing credit: ${entry}`).toContain(entry);
  }
  expect(rendered).not.toContain('…');
}

describe('fitAttributionText', () => {
  const entries = ['© OpenFreeMap', '© OpenMapTiles', '© OpenStreetMap contributors'];

  it('keeps everything on one line when it fits', () => {
    const ctx = makeCtx();
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 1000,
      fontPx: 16,
    });
    expect(fitted.fontPx).toBe(16);
    expect(fitted.lines).toEqual([entries.join(' | ')]);
  });

  it('wraps on entry boundaries, so a provider name is never split needlessly', () => {
    const ctx = makeCtx();
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 200,
      fontPx: 12,
    });
    expect(fitted.lines.length).toBeGreaterThan(1);
    expectTotal(fitted.lines, entries);
    // Each line is made of whole entries joined by the separator.
    for (const line of fitted.lines) {
      for (const part of line.split(' | ')) expect(entries).toContain(part);
    }
  });

  it('never shrinks below the requested size', () => {
    const ctx = makeCtx();
    for (const maxWidth of [1000, 300, 120, 40]) {
      const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
        maxWidth,
        fontPx: 12,
      });
      expect(fitted.fontPx).toBe(12);
    }
  });

  it('keeps every provider at the real export width, past the old two-line cap', () => {
    const ctx = makeCtx();
    // 1056px canvas at dpr 1 less 20px padding a side: the measured export.
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, REAL_CREDITS, {
      maxWidth: 1016,
      fontPx: 12,
    });
    expect(fitted.lines.length).toBeGreaterThan(2);
    expectTotal(fitted.lines, REAL_CREDITS);
  });

  it('keeps every provider under an absurd credit count', () => {
    const ctx = makeCtx();
    const many = Array.from(
      { length: 25 },
      (_, i) => `© Provider Number ${i} With A Reasonably Long Attribution String`,
    );
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, many, {
      maxWidth: 1016,
      fontPx: 12,
    });
    expectTotal(fitted.lines, many);
  });

  it('wraps a single credit wider than the band mid-string without losing a word', () => {
    const ctx = makeCtx();
    const huge = `© ${'Extremely Long Provider Name '.repeat(12)}End`;
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, [huge], {
      maxWidth: 300,
      fontPx: 12,
    });
    expect(fitted.lines.length).toBeGreaterThan(1);
    expect(fitted.lines.join(' ').replace(/\s+/g, ' ').trim()).toBe(
      huge.replace(/\s+/g, ' ').trim(),
    );
  });

  it('breaks an unbreakable word rather than dropping it', () => {
    const ctx = makeCtx();
    const word = 'A'.repeat(200);
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, [word], {
      maxWidth: 100,
      fontPx: 12,
    });
    expect(fitted.lines.join('')).toBe(word);
  });

  it('returns nothing for no entries or no room', () => {
    const ctx = makeCtx();
    expect(
      fitAttributionText(ctx as unknown as CanvasRenderingContext2D, [], {
        maxWidth: 400,
        fontPx: 12,
      }).lines,
    ).toEqual([]);
    expect(
      fitAttributionText(ctx as unknown as CanvasRenderingContext2D, ['© A'], {
        maxWidth: 0,
        fontPx: 12,
      }).lines,
    ).toEqual([]);
  });

  it('terminates on a degenerate context that measures everything as too wide', () => {
    // A font that fails to load is the realistic version of this. It must not
    // spin: every loop here is bounded by the string length, not by a width
    // comparison that can never become true.
    const ctx = { ...makeCtx(), measureText: vi.fn(() => ({ width: Infinity })) };
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, ['ABC'], {
      maxWidth: 100,
      fontPx: 12,
    });
    expect(fitted.lines.join('')).toBe('ABC');
  });
});

/* fix(#1541 codex P2): mid-STRING wrapping is the one residual limit we allow.
 * Mid-CHARACTER is truncation in disguise — a surrogate pair split across two
 * drawn lines renders replacement glyphs where the provider's name should be. */
describe('grapheme safety in the wrapping path', () => {
  const EMOJI = '\u{1F30D}'; // U+1F30D EARTH GLOBE EUROPE-AFRICA, non-BMP
  const FAMILY = '\u{1F468}\u200D\u{1F469}\u200D\u{1F467}'; // ZWJ sequence
  const ACCENTED = 'e\u0301'; // e + COMBINING ACUTE, two code units, one grapheme

  /** Every drawn line, for a credit forced to break many times. */
  function linesFor(credit: string, maxWidth: number): string[] {
    const ctx = makeCtx();
    return fitAttributionText(ctx as unknown as CanvasRenderingContext2D, [credit], {
      maxWidth,
      fontPx: 12,
    }).lines;
  }

  it('never emits a lone surrogate when breaking a non-BMP run', () => {
    const credit = `© ${EMOJI.repeat(200)}`;
    // Swept across widths on purpose. Each emoji is exactly two code units, so
    // a single width can land every code-unit break on an even boundary and
    // pass while the implementation is unsafe — this test did exactly that
    // before the sweep was added.
    for (let maxWidth = 25; maxWidth <= 100; maxWidth += 7) {
      const lines = linesFor(credit, maxWidth);
      expect(lines.length).toBeGreaterThan(1);
      for (const line of lines) {
        // A split pair leaves an unpaired surrogate at a line edge.
        expect(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(line), `width ${maxWidth}`).toBe(false);
        expect(/(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(line), `width ${maxWidth}`).toBe(false);
      }
      // Whitespace-insensitive totality: a word break consumes the space it
      // broke at while a character break inserts none, so where the spaces
      // land is not the property under test. Losing a CHARACTER is.
      expect(lines.join('').replace(/\s+/g, '')).toBe(credit.replace(/\s+/g, ''));
    }
  });

  it('keeps ZWJ sequences and combining marks intact across a break', () => {
    for (const cluster of [FAMILY, ACCENTED]) {
      const credit = cluster.repeat(120);
      const lines = linesFor(credit, 60);
      expect(lines.length).toBeGreaterThan(1);
      // No spaces in these fixtures, so the pieces concatenate exactly.
      expect(lines.join('')).toBe(credit);
      // No line starts with a combining mark or a ZWJ, which is what a
      // mid-cluster break looks like from the next line's side.
      for (const line of lines) {
        expect(/^[\u0300-\u036F\u200D]/.test(line)).toBe(false);
      }
    }
  });

  it('loses nothing when a provider name mixes scripts and emoji', () => {
    const credit = `© Ácme ${EMOJI} 地図データ ${FAMILY} contributors`.repeat(30);
    const lines = linesFor(credit, 80);
    expect(lines.join('').replace(/\s+/g, '')).toBe(credit.replace(/\s+/g, ''));
  });
});

describe('drawAttributionOverlay', () => {
  it('draws a scrim under dark text in the bottom-right', () => {
    const ctx = makeCtx();
    const canvas = makeCanvas(400, 250, ctx);
    expect(drawAttributionOverlay(canvas, ['© OpenStreetMap'], THUMBNAIL_ATTRIBUTION)).toBe(
      true,
    );

    expect(ctx.fillRect).toHaveBeenCalledTimes(1);
    const [x, y, w, h] = ctx.fillRect.mock.calls[0] as unknown as number[];
    expect(x + w).toBe(400 - THUMBNAIL_ATTRIBUTION.inset);
    expect(y + h).toBe(250 - THUMBNAIL_ATTRIBUTION.inset);
    expect(x).toBeGreaterThan(0);
    expect(y).toBeGreaterThan(0);

    // Scrim first, text second — the reverse would erase the line.
    expect(ctx.fillRect.mock.invocationCallOrder[0]).toBeLessThan(
      ctx.fillText.mock.invocationCallOrder[0],
    );
    expect(ctx.fillText).toHaveBeenCalledWith('© OpenStreetMap', expect.any(Number), expect.any(Number));
    expect(ctx.fillStyle).toBe(MAP_COLORS.exportImage.text);
  });

  it('joins multiple credits with MapLibre\'s separator', () => {
    const ctx = makeCtx();
    drawAttributionOverlay(makeCanvas(1200, 630, ctx), ['© A', '© B'], OG_ATTRIBUTION);
    expect(ctx.fillText).toHaveBeenCalledWith('© A | © B', expect.any(Number), expect.any(Number));
  });

  // The second codex P1. These crops cannot grow, so they spend map pixels.
  it('wraps to multiple lines rather than dropping a credit on the thumbnail', () => {
    const ctx = makeCtx();
    const canvas = makeCanvas(400, 250, ctx);
    expect(drawAttributionOverlay(canvas, REAL_CREDITS, THUMBNAIL_ATTRIBUTION)).toBe(true);

    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(drawn.length).toBeGreaterThan(1);
    expectTotal(drawn, REAL_CREDITS);

    // The scrim covers every line and still sits inside the frame.
    const [x, y, w, h] = ctx.fillRect.mock.calls[0] as unknown as number[];
    expect(h).toBe(drawn.length * THUMBNAIL_ATTRIBUTION.lineHeight + THUMBNAIL_ATTRIBUTION.paddingY * 2);
    expect(x).toBeGreaterThanOrEqual(0);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(x + w).toBeLessThanOrEqual(400);
    expect(y + h).toBeLessThanOrEqual(250);
  });

  it('wraps to multiple lines rather than dropping a credit on the OG card', () => {
    const ctx = makeCtx();
    const canvas = makeCanvas(1200, 630, ctx);
    expect(drawAttributionOverlay(canvas, REAL_CREDITS, OG_ATTRIBUTION)).toBe(true);
    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));
    expectTotal(drawn, REAL_CREDITS);
  });

  it('renders at the documented size and never smaller', () => {
    const ctx = makeCtx();
    drawAttributionOverlay(makeCanvas(400, 250, ctx), REAL_CREDITS, THUMBNAIL_ATTRIBUTION);
    expect(ctx.font).toContain(`${THUMBNAIL_ATTRIBUTION.fontPx}px`);
  });

  it('draws nothing when there is no credit to draw', () => {
    const ctx = makeCtx();
    expect(drawAttributionOverlay(makeCanvas(400, 250, ctx), [], THUMBNAIL_ATTRIBUTION)).toBe(
      false,
    );
    expect(ctx.fillText).not.toHaveBeenCalled();
    expect(ctx.fillRect).not.toHaveBeenCalled();
  });

  it('draws nothing when the canvas has no 2D context', () => {
    const canvas = { width: 400, height: 250, getContext: () => null } as unknown as HTMLCanvasElement;
    expect(drawAttributionOverlay(canvas, ['© A'], THUMBNAIL_ATTRIBUTION)).toBe(false);
  });
});

/* fix(#1541 codex P1): the documented legibility floor, as assertions rather
 * than as prose. Removing the fitter's elision left exactly one way for a crop
 * to lose a credit — a band taller than the image it annotates — and these pin
 * both where that is and that it is loud when reached. */
describe('overlayLineCapacity: the documented ceiling', () => {
  it('matches the header table for both crops', () => {
    // 250 - 6 inset - 3*2 padding = 238 usable / 13 line height.
    expect(overlayLineCapacity(THUMBNAIL_ATTRIBUTION, 250)).toBe(18);
    // 630 - 12 inset - 5*2 padding = 608 usable / 20 line height.
    expect(overlayLineCapacity(OG_ATTRIBUTION, 630)).toBe(30);
  });

  it('never returns a negative capacity for a frame smaller than its own inset', () => {
    expect(overlayLineCapacity(THUMBNAIL_ATTRIBUTION, 4)).toBe(0);
    expect(overlayLineCapacity(OG_ATTRIBUTION, 0)).toBe(0);
  });

  it('leaves the real credit load a long way clear of the ceiling', () => {
    // The documented "real 5-credit load" column: 6 of 18 lines on the
    // thumbnail (33.6% of a 250px frame), 4 of 30 on the OG card (14.3%).
    for (const [spec, w, h, lines, pct] of [
      [THUMBNAIL_ATTRIBUTION, 400, 250, 6, 33.6],
      [OG_ATTRIBUTION, 1200, 630, 4, 14.3],
    ] as const) {
      const ctx = makeCtx();
      drawAttributionOverlay(makeCanvas(w, h, ctx), REAL_CREDITS, spec);
      const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(drawn).toHaveLength(lines);
      expect(drawn.length).toBeLessThan(overlayLineCapacity(spec, h));
      const [, , , boxH] = ctx.fillRect.mock.calls[0] as unknown as number[];
      expect(((boxH / h) * 100).toFixed(1)).toBe(pct.toFixed(1));
    }
  });

  it('pins the export band height formula, a long way inside its ceiling', () => {
    // Line count here is the STUB's, not the browser's — the 0.5em metric only
    // approximates real glyph widths, so this pins the height FORMULA and the
    // totality, not the header table's measured "real load" column.
    const budget = attributionBandHeightBudget(1056, 600 + 32);
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      REAL_CREDITS,
      { maxWidth: 1016, dpr: 1, maxHeight: budget },
    );
    expect(measured.height).toBe(12 + measured.lines.length * 16 + 12);
    expectTotal(measured.lines, REAL_CREDITS);
    // The documented header-table row: 951 lines of ceiling for a real load of
    // four, so the bound is nowhere near the ordinary export.
    expect(attributionBandLineCapacity(budget, 1)).toBe(951);
    expect(measured.lines.length).toBeLessThan(20);
  });

  /* fix(#1541 codex P1 round 2): the schema accepts 5,000 characters per
   * credit (datasets/domain/schemas.py, processing/ingest/manifest_schemas.py).
   * That is ~77 lines in a 250px thumbnail — unrenderable at any legible size.
   * So the invariant is asserted at the CONTRACT's maximum, not at the 411
   * characters real data happens to carry: nothing is painted outside the
   * canvas, and rendered credits plus marked credits equals the input. */

  /** Every line lands inside the frame, and so does the scrim behind them. */
  function expectNothingOutsideFrame(
    ctx: ReturnType<typeof makeCtx>,
    spec: typeof THUMBNAIL_ATTRIBUTION,
    w: number,
    h: number,
  ) {
    for (const call of ctx.fillText.mock.calls) {
      const y = call[2] as number;
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y + spec.lineHeight).toBeLessThanOrEqual(h);
      expect(call[1] as number).toBeGreaterThanOrEqual(0);
    }
    const [x, y, bw, bh] = ctx.fillRect.mock.calls[0] as unknown as number[];
    expect(x).toBeGreaterThanOrEqual(0);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(x + bw).toBeLessThanOrEqual(w);
    expect(y + bh).toBeLessThanOrEqual(h);
  }

  /** The count named by a trailing "+N more credits" marker, or 0. */
  function markedCount(drawn: string[]): number {
    const match = /\+(\d+) more credit/.exec(drawn[drawn.length - 1] ?? '');
    return match ? Number(match[1]) : 0;
  }

  it('at the 5,000-character contract maximum: nothing outside the frame, every credit accounted for', () => {
    // Five credits, each exactly the schema's max_length.
    const maxed = Array.from({ length: 5 }, (_, i) =>
      `© Provider ${i} ${'licensing statement '.repeat(260)}`.slice(0, 4999).padEnd(5000, '.'),
    );
    for (const c of maxed) expect(c).toHaveLength(5000);

    for (const [spec, w, h] of [
      [THUMBNAIL_ATTRIBUTION, 400, 250],
      [OG_ATTRIBUTION, 1200, 630],
    ] as const) {
      const ctx = makeCtx();
      expect(drawAttributionOverlay(makeCanvas(w, h, ctx), maxed, spec)).toBe(true);
      const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));

      expect(drawn.length).toBeLessThanOrEqual(overlayLineCapacity(spec, h));
      expectNothingOutsideFrame(ctx, spec, w, h);

      // Rendered whole + marked == input. Nothing falls between the two.
      const joined = drawn.join(' ');
      const rendered = maxed.filter((c) => joined.includes(c)).length;
      expect(rendered + markedCount(drawn)).toBe(maxed.length);
      // Non-vacuous: at 5,000 characters a credit, NOTHING fits either frame,
      // so the marker must be carrying the whole count rather than the sum
      // balancing because everything rendered.
      expect(markedCount(drawn)).toBe(maxed.length);
      expect(drawn).toEqual(['+5 more credits']);
    }
  });

  it('renders what fits and marks the rest, rather than clipping', () => {
    const ctx = makeCtx();
    // 40 medium credits: some fit the 18-line thumbnail, most do not.
    const flood = Array.from(
      { length: 40 },
      (_, i) => `© Data Provider Number ${i}, a licensing statement of some length`,
    );
    expect(drawAttributionOverlay(makeCanvas(400, 250, ctx), flood, THUMBNAIL_ATTRIBUTION)).toBe(
      true,
    );
    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));

    expect(drawn.length).toBeLessThanOrEqual(overlayLineCapacity(THUMBNAIL_ATTRIBUTION, 250));
    expectNothingOutsideFrame(ctx, THUMBNAIL_ATTRIBUTION, 400, 250);

    // Some real credits DID render — this is not a bare marker.
    const joined = drawn.join(' ');
    const rendered = flood.filter((c) => joined.includes(c)).length;
    expect(rendered).toBeGreaterThan(0);
    expect(markedCount(drawn)).toBeGreaterThan(0);
    expect(rendered + markedCount(drawn)).toBe(flood.length);

    // The marker is the last line, so it reads as a footnote to what precedes it.
    expect(drawn[drawn.length - 1]).toMatch(/\+\d+ more credit/);
  });

  it("counts CREDITS not fragments when credits contain the separator", () => {
    // fix(#1541 codex P2): the marker's N used to be derived from a joined
    // string re-split on ` | `, so a credit containing the separator inflated
    // the count and could be cut in half with its remainder counted as another
    // provider. Each of these is ONE credit that happens to contain ` | `.
    const ctx = makeCtx();
    const credits = Array.from(
      { length: 24 },
      (_, i) => `© Provider ${i} | Division A | Division B, a licensing statement`,
    );
    expect(drawAttributionOverlay(makeCanvas(400, 250, ctx), credits, THUMBNAIL_ATTRIBUTION))
      .toBe(true);
    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));

    // The true omitted count: credits not present whole in the rendered text.
    const joined = drawn.join(' ');
    const renderedWhole = credits.filter((c) => joined.includes(c)).length;
    expect(renderedWhole).toBeGreaterThan(0);
    expect(markedCount(drawn)).toBe(credits.length - renderedWhole);
    expectNothingOutsideFrame(ctx, THUMBNAIL_ATTRIBUTION, 400, 250);
  });

  it('draws nothing at all rather than outside a frame too small for one line', () => {
    const ctx = makeCtx();
    // 12px tall: capacity 0. Painting here could only land off-frame.
    expect(drawAttributionOverlay(makeCanvas(400, 12, ctx), REAL_CREDITS, THUMBNAIL_ATTRIBUTION))
      .toBe(false);
    expect(ctx.fillText).not.toHaveBeenCalled();
    expect(ctx.fillRect).not.toHaveBeenCalled();
  });

  it('adds no marker when everything fits', () => {
    const ctx = makeCtx();
    drawAttributionOverlay(makeCanvas(1200, 630, ctx), REAL_CREDITS, OG_ATTRIBUTION);
    const drawn = ctx.fillText.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(drawn.join(' ')).not.toMatch(/more credit/);
    expectTotal(drawn, REAL_CREDITS);
  });

  it('stays quiet for a credit load that fits', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      drawAttributionOverlay(makeCanvas(400, 250, makeCtx()), REAL_CREDITS, THUMBNAIL_ATTRIBUTION);
      expect(warn).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });
});

describe('measureAttributionBand / drawAttributionBand', () => {
  /** The budget a real 1056x600 export at dpr 1 hands the band. Big enough
   *  that these cases never reach it; the ceiling has its own describe below. */
  const ROOMY = attributionBandHeightBudget(1056, 632);

  it('reserves gap + lines + gap, scaled by dpr', () => {
    const ctx = makeCtx();
    const measured = measureAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      ['© OpenStreetMap contributors'],
      { maxWidth: 2000, dpr: 2, maxHeight: ROOMY },
    );
    expect(measured.lines).toEqual(['© OpenStreetMap contributors']);
    expect(measured.height).toBe(80); // 12*2 + 1 * 16*2 + 12*2
    expect(measured.fontPx).toBe(24); // 12 * dpr
  });

  it('reserves no height at all when there is no credit', () => {
    const ctx = makeCtx();
    expect(
      measureAttributionBand(ctx as unknown as CanvasRenderingContext2D, [], {
        maxWidth: 2000,
        dpr: 1,
        maxHeight: ROOMY,
      }).height,
    ).toBe(0);
  });

  it('grows the band height with the line count, dropping nothing', () => {
    const ctx = makeCtx();
    const credits = Array.from(
      { length: 12 },
      (_, i) => `© Data Provider ${i} With A Long Attribution Line`,
    );
    const measured = measureAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      credits,
      { maxWidth: 300, dpr: 1, maxHeight: ROOMY },
    );
    expect(measured.lines.length).toBeGreaterThan(2);
    expect(measured.height).toBe(12 + measured.lines.length * 16 + 12);
    expectTotal(measured.lines, credits);
  });

  it('draws each line at the muted contrast, stepping by the line height', () => {
    const ctx = makeCtx();
    drawAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      { lines: ['line one', 'line two'], fontPx: 12, height: 56 },
      { x: 20, y: 100, dpr: 1 },
    );
    expect(ctx.fillStyle).toBe(MAP_COLORS.exportImage.mutedText);
    expect(ctx.fillText.mock.calls).toEqual([
      ['line one', 20, 112],
      ['line two', 20, 128],
    ]);
  });

  it('draws nothing for an empty measurement', () => {
    const ctx = makeCtx();
    drawAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      { lines: [], fontPx: 12, height: 0 },
      { x: 20, y: 100, dpr: 1 },
    );
    expect(ctx.fillText).not.toHaveBeenCalled();
  });
});

/* fix(#1541 codex P2 round 2): the export band is bounded too.
 *
 * #1541 review had ruled its growth unlimited, on the reasoning that the export
 * canvas is sized after the band is measured and so has no height constraint.
 * Browsers do: a canvas is capped per side and by total area, and past either
 * one `toBlob` hands back null and the export fails outright. At the contract's
 * maximum — 200 layers, 5,000 characters of credit each — the unlimited band
 * asked for a canvas no engine would encode, which is strictly worse than the
 * partial credit it was meant to avoid. */
describe('export canvas ceiling', () => {
  /** Exactly 5,000 characters — the schema maximum — of ordinary short words,
   *  so wrapping breaks on spaces and joining the lines back with a space
   *  reconstructs the credit. A long unbroken run would wrap mid-word and make
   *  the accounting below measure the stub's word-breaker instead. */
  function maxedCredit(i: number): string {
    const body = `© Provider ${i} ${'licensing statement for the exported map image '.repeat(120)}`;
    return body.slice(0, 5000).trimEnd().padEnd(5000, 'x');
  }

  /** The count named by a trailing "+N more credits" marker, or 0. */
  function markedCount(lines: string[]): number {
    const match = /\+(\d+) more credit/.exec(lines[lines.length - 1] ?? '');
    return match ? Number(match[1]) : 0;
  }

  const EXPORT_WIDTH = 1056;
  const EXPORT_MAX_TEXT_WIDTH = EXPORT_WIDTH - 40; // 20px of pad a side
  // 600px of map plus a 32px branding footer, the shape the hook composes.
  const RESERVED = 632;

  it('budgets against the smallest measured engine ceiling, not the roomiest', () => {
    // fix(#1541 codex P2 round 4): the area cap is iOS Safari's 4,096² and NOT
    // a desktop figure. codex's case: an iPad's 2048x2732 canvas is valid and
    // exports today, and the desktop budget let the band grow it past 8,192px
    // high, where toBlob returns null and the export produces nothing.
    expect(EXPORT_CANVAS_MAX_AREA).toBe(4096 * 4096);
    expect(exportCanvasHeightCeiling(2048)).toBe(8192);
    // Side-limited only for a narrow canvas; the area cap binds past 1,024px.
    expect(exportCanvasHeightCeiling(1024)).toBe(EXPORT_CANVAS_MAX_DIMENSION);
    expect(exportCanvasHeightCeiling(EXPORT_WIDTH)).toBe(
      Math.floor(EXPORT_CANVAS_MAX_AREA / EXPORT_WIDTH),
    );
    expect(exportCanvasHeightCeiling(EXPORT_WIDTH)).toBeLessThan(EXPORT_CANVAS_MAX_DIMENSION);
    expect(exportCanvasHeightCeiling(0)).toBe(0);
  });

  it('costs an ordinary desktop export nothing', () => {
    // The numbers the constants' comment quotes, so they cannot drift from it.
    expect(attributionBandLineCapacity(attributionBandHeightBudget(1056, 632), 1)).toBe(951);
    // A maximized builder on a 5K display at dpr 2: 4400x2400 map, 32px footer.
    expect(attributionBandLineCapacity(attributionBandHeightBudget(4400, 2432), 2)).toBe(41);
  });

  it('costs the same pixels at any dpr, so the cap is a canvas budget not a line count', () => {
    expect(attributionBandLineCapacity(1000, 1)).toBe(61); // (1000 - 24) / 16
    expect(attributionBandLineCapacity(1000, 2)).toBe(29); // (1000 - 48) / 32
    expect(attributionBandLineCapacity(10, 1)).toBe(0);
  });

  /* fix(#1541 codex P2 round 5): the budget used to be floored at one minimum
   * band, which overran the very ceiling it sat inside — a floor and a ceiling
   * that did not know about each other. It never exceeds actual headroom now,
   * and under one line's worth it declines rather than drawing something
   * invalid. codex's case is the first assertion. */

  it('never exceeds actual headroom, even to keep one line', () => {
    // width 2048, dpr 2, 8,140px reserved: 52px of headroom against an 8,192px
    // ceiling. The old floor answered 80 and produced an 8,220px canvas whose
    // area is past 16,777,216.
    const budget = attributionBandHeightBudget(2048, 8140);
    expect(budget).toBe(52);
    expect(8140 + budget).toBeLessThanOrEqual(exportCanvasHeightCeiling(2048));
    expect(2048 * (8140 + budget)).toBeLessThanOrEqual(EXPORT_CANVAS_MAX_AREA);

    // 52px cannot hold a line at dpr 2, so the band declines outright: no
    // credit, no marker, and critically no pixels added to a canvas at the cap.
    expect(attributionBandLineCapacity(budget, 2)).toBe(0);
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      REAL_CREDITS,
      { maxWidth: EXPORT_MAX_TEXT_WIDTH, dpr: 2, maxHeight: budget },
    );
    expect(measured).toEqual({ lines: [], fontPx: 24, height: 0 });
  });

  it('gives the band nothing once the fixed blocks have spent the ceiling', () => {
    expect(attributionBandHeightBudget(EXPORT_WIDTH, EXPORT_CANVAS_MAX_DIMENSION)).toBe(0);
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      REAL_CREDITS,
      { maxWidth: EXPORT_MAX_TEXT_WIDTH, dpr: 1, maxHeight: 0 },
    );
    expect(measured).toEqual({ lines: [], fontPx: 12, height: 0 });
  });

  it('still marks rather than declines when one line does fit', () => {
    // The boundary above it: exactly one line of budget renders the marker,
    // so declining is reserved for genuinely having nowhere to put anything.
    const budget = 12 + 16 + 12;
    expect(attributionBandLineCapacity(budget, 1)).toBe(1);
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      REAL_CREDITS,
      { maxWidth: EXPORT_MAX_TEXT_WIDTH, dpr: 1, maxHeight: budget },
    );
    expect(measured.lines).toEqual([`+${REAL_CREDITS.length} more credits`]);
    expect(measured.height).toBe(40);
  });

  it('at 200 credits x 5,000 characters: the canvas stays encodable, every credit accounted for', () => {
    const credits = Array.from({ length: 200 }, (_, i) => maxedCredit(i));
    for (const c of credits) expect(c).toHaveLength(5000);

    const budget = attributionBandHeightBudget(EXPORT_WIDTH, RESERVED);
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      credits,
      { maxWidth: EXPORT_MAX_TEXT_WIDTH, dpr: 1, maxHeight: budget },
    );

    // The canvas the hook would build from this measurement is one a browser
    // will still encode, on both limits.
    const canvasHeight = RESERVED + measured.height;
    expect(measured.height).toBeLessThanOrEqual(budget);
    expect(canvasHeight).toBeLessThanOrEqual(EXPORT_CANVAS_MAX_DIMENSION);
    expect(EXPORT_WIDTH * canvasHeight).toBeLessThanOrEqual(EXPORT_CANVAS_MAX_AREA);

    // Rendered whole + marked == input. Nothing falls between the two.
    const joined = measured.lines.join(' ');
    const rendered = credits.filter((c) => joined.includes(c)).length;
    expect(rendered + markedCount(measured.lines)).toBe(credits.length);
    expect(joined).not.toContain('…');
    // Non-vacuous in both directions: real credits DID render (this is not a
    // bare marker), and the marker IS carrying a count (the sum is not
    // balancing because everything happened to fit).
    expect(rendered).toBeGreaterThan(0);
    expect(markedCount(measured.lines)).toBeGreaterThan(0);
  });

  it('leaves a mid-sized credit load growing and complete, with no marker', () => {
    const credits = Array.from(
      { length: 40 },
      (_, i) => `© Data Provider ${i}, a licensing statement of some reasonable length`,
    );
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      credits,
      {
        maxWidth: EXPORT_MAX_TEXT_WIDTH,
        dpr: 1,
        maxHeight: attributionBandHeightBudget(EXPORT_WIDTH, RESERVED),
      },
    );
    expect(measured.lines.length).toBeGreaterThan(2);
    expect(measured.height).toBe(12 + measured.lines.length * 16 + 12);
    expect(measured.lines.join(' ')).not.toMatch(/more credit/);
    expectTotal(measured.lines, credits);
  });
});
