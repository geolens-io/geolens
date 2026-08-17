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

  it('prefers alt over aria-label over title', () => {
    expect(
      readRenderedAttribution(
        sourcesMap('<img src="https://a.example/l.png" alt="© Alt" aria-label="© Aria" title="© Title">'),
      ),
    ).toEqual(['© Alt']);
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

  it('warns and returns nothing only when the control is genuinely empty', () => {
    const container = document.createElement('div');
    const inner = document.createElement('div');
    inner.className = 'maplibregl-ctrl-attrib-inner';
    inner.innerHTML = '<img src="https://a.example/spacer.gif" alt="">';
    container.appendChild(inner);
    expect(readRenderedAttribution({ getContainer: () => container })).toEqual([]);
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
    // The documented header-table row: 983 lines of ceiling for a real load of
    // four, so the bound is nowhere near the ordinary export.
    expect(attributionBandLineCapacity(budget, 1)).toBe(983);
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

  it('is side-limited at ordinary export widths and area-limited at extreme ones', () => {
    expect(exportCanvasHeightCeiling(EXPORT_WIDTH)).toBe(EXPORT_CANVAS_MAX_DIMENSION);
    // The crossover sits at ~7,629px wide; past it the area limit binds first.
    expect(exportCanvasHeightCeiling(8000)).toBe(Math.floor(EXPORT_CANVAS_MAX_AREA / 8000));
    expect(exportCanvasHeightCeiling(8000)).toBeLessThan(EXPORT_CANVAS_MAX_DIMENSION);
    expect(exportCanvasHeightCeiling(0)).toBe(0);
  });

  it('costs the same pixels at any dpr, so the cap is a canvas budget not a line count', () => {
    expect(attributionBandLineCapacity(1000, 1)).toBe(61); // (1000 - 24) / 16
    expect(attributionBandLineCapacity(1000, 2)).toBe(29); // (1000 - 48) / 32
    expect(attributionBandLineCapacity(10, 1)).toBe(0);
  });

  it('hands the band no height when the rest of the image has spent the ceiling', () => {
    expect(attributionBandHeightBudget(EXPORT_WIDTH, EXPORT_CANVAS_MAX_DIMENSION)).toBe(0);
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      REAL_CREDITS,
      { maxWidth: EXPORT_MAX_TEXT_WIDTH, dpr: 1, maxHeight: 0 },
    );
    expect(measured).toEqual({ lines: [], fontPx: 12, height: 0 });
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
