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
  drawAttributionBand,
  drawAttributionOverlay,
  fitAttributionText,
  measureAttributionBand,
  overlayLineCapacity,
  readRenderedAttribution,
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
  it('tier 1: reads the rendered control and splits on MapLibre\'s separator', () => {
    expect(
      readRenderedAttribution(
        mapWithControl('© OpenFreeMap | © OpenMapTiles | © OpenStreetMap contributors'),
      ),
    ).toEqual(['© OpenFreeMap', '© OpenMapTiles', '© OpenStreetMap contributors']);
  });

  it('tier 1: dedupes and drops empties', () => {
    expect(readRenderedAttribution(mapWithControl('© A | © A |  | © B'))).toEqual([
      '© A',
      '© B',
    ]);
  });

  it('tier 1 wins over the style even when both are available', () => {
    const map = {
      ...mapWithControl('© Rendered'),
      getStyle: () => ({ sources: { a: { attribution: '© From style' } } }),
    };
    expect(readRenderedAttribution(map)).toEqual(['© Rendered']);
  });

  it('tier 2: falls back to source attribution when the control is absent', () => {
    const map = {
      ...mapWithControl(null),
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

  it('tier 2: decodes entities and anchors without parsing live markup', () => {
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

  it('tier 3: returns nothing when neither source is available', () => {
    expect(readRenderedAttribution(mapWithControl(null))).toEqual([]);
    expect(readRenderedAttribution({})).toEqual([]);
  });

  it('an empty control falls through to the style rather than reporting no credit', () => {
    const map = {
      ...mapWithControl('   '),
      getStyle: () => ({ sources: { a: { attribution: '© Fallback' } } }),
    };
    expect(readRenderedAttribution(map)).toEqual(['© Fallback']);
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

  it('pins the export band height formula, which has no ceiling to reach', () => {
    // Line count here is the STUB's, not the browser's — the 0.5em metric only
    // approximates real glyph widths, so this pins the height FORMULA and the
    // totality, not the header table's measured "real load" column.
    const measured = measureAttributionBand(
      makeCtx() as unknown as CanvasRenderingContext2D,
      REAL_CREDITS,
      { maxWidth: 1016, dpr: 1 },
    );
    expect(measured.height).toBe(12 + measured.lines.length * 16 + 12);
    expectTotal(measured.lines, REAL_CREDITS);
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
  it('reserves gap + lines + gap, scaled by dpr', () => {
    const ctx = makeCtx();
    const measured = measureAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      ['© OpenStreetMap contributors'],
      { maxWidth: 2000, dpr: 2 },
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
      { maxWidth: 300, dpr: 1 },
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
