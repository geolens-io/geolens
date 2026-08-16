/**
 * feat(#1486): the credit line drawn into every rendered map image.
 *
 * The fitter is the only piece with real logic, so it carries most of these
 * tests. Its stub context measures LENGTH-PROPORTIONALLY (`chars * 0.5 *
 * fontPx`), unlike the constant-width stub the hook suite uses — a constant
 * cannot exercise a size ladder or an elide boundary at all.
 */
import { describe, it, expect, vi } from 'vitest';
import {
  drawAttributionBand,
  drawAttributionOverlay,
  fitAttributionText,
  measureAttributionBand,
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
 *  size, so a shrink ladder and an entry-boundary elide are observable. */
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

describe('fitAttributionText', () => {
  const entries = ['© OpenFreeMap', '© OpenMapTiles', '© OpenStreetMap contributors'];

  it('keeps the requested size when everything fits on one line', () => {
    const ctx = makeCtx();
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 1000,
      fontPx: 16,
      minFontPx: 13,
      maxLines: 1,
    });
    expect(fitted.fontPx).toBe(16);
    expect(fitted.elided).toBe(false);
    expect(fitted.lines).toEqual([entries.join(' | ')]);
  });

  it('shrinks down the ladder before it drops anything', () => {
    const ctx = makeCtx();
    // 61 chars joined; 61 * 0.5 * 16 = 488 wide at 16px, 397 at 13px.
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 420,
      fontPx: 16,
      minFontPx: 13,
      maxLines: 1,
    });
    expect(fitted.elided).toBe(false);
    expect(fitted.fontPx).toBeLessThan(16);
    expect(fitted.lines).toEqual([entries.join(' | ')]);
  });

  it('wraps to a second line rather than dropping a credit when allowed', () => {
    const ctx = makeCtx();
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 200,
      fontPx: 12,
      minFontPx: 10,
      maxLines: 2,
    });
    expect(fitted.elided).toBe(false);
    expect(fitted.lines.length).toBeGreaterThan(1);
    // Every credit survives the wrap.
    const rendered = fitted.lines.join(' | ');
    for (const entry of entries) expect(rendered).toContain(entry);
  });

  it('elides at an entry boundary, never mid-name', () => {
    const ctx = makeCtx();
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 120,
      fontPx: 10,
      minFontPx: 9,
      maxLines: 1,
    });
    expect(fitted.elided).toBe(true);
    expect(fitted.lines).toHaveLength(1);
    expect(fitted.lines[0]).toMatch(/…$/);
    // The surviving entries are whole: no truncated provider name.
    const kept = fitted.lines[0].split(' | ').filter((s) => s !== '…');
    for (const part of kept) expect(entries).toContain(part);
  });

  it('character-truncates only when a single entry cannot fit at the floor', () => {
    const ctx = makeCtx();
    const long = '© An Extremely Long Single Data Provider Name That Cannot Fit';
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, [long], {
      maxWidth: 60,
      fontPx: 10,
      minFontPx: 9,
      maxLines: 1,
    });
    expect(fitted.elided).toBe(true);
    expect(fitted.lines[0]).toMatch(/…$/);
    expect(fitted.lines[0].length).toBeLessThan(long.length);
    expect(long.startsWith(fitted.lines[0].replace(/…$/, ''))).toBe(true);
  });

  it('returns nothing for no entries or no room', () => {
    const ctx = makeCtx();
    expect(
      fitAttributionText(ctx as unknown as CanvasRenderingContext2D, [], {
        maxWidth: 400,
        fontPx: 12,
        minFontPx: 10,
        maxLines: 1,
      }).lines,
    ).toEqual([]);
    expect(
      fitAttributionText(ctx as unknown as CanvasRenderingContext2D, ['© A'], {
        maxWidth: 0,
        fontPx: 12,
        minFontPx: 10,
        maxLines: 1,
      }).lines,
    ).toEqual([]);
  });

  it('terminates on a degenerate context that measures everything as too wide', () => {
    // Guards the one shape that could hang an export: a shrink loop driven off
    // measureText rather than a bounded ladder (a font that fails to load
    // measures like this).
    const ctx = { ...makeCtx(), measureText: vi.fn(() => ({ width: Infinity })) };
    const fitted = fitAttributionText(ctx as unknown as CanvasRenderingContext2D, entries, {
      maxWidth: 100,
      fontPx: 16,
      minFontPx: 9,
      maxLines: 2,
    });
    expect(fitted.lines).toEqual(['…']);
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
    // Bottom-right, inside the inset.
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

describe('measureAttributionBand / drawAttributionBand', () => {
  it('reserves gap + lines + gap, scaled by dpr', () => {
    const ctx = makeCtx();
    const measured = measureAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      ['© OpenStreetMap contributors'],
      { maxWidth: 2000, dpr: 2 },
    );
    expect(measured.lines).toEqual(['© OpenStreetMap contributors']);
    // 12*2 + 1 line * 16*2 + 12*2
    expect(measured.height).toBe(80);
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

  it('grows to two lines rather than dropping a credit', () => {
    const ctx = makeCtx();
    const measured = measureAttributionBand(
      ctx as unknown as CanvasRenderingContext2D,
      ['© Provider One', '© Provider Two', '© Provider Three', '© Provider Four'],
      { maxWidth: 300, dpr: 1 },
    );
    expect(measured.lines).toHaveLength(2);
    expect(measured.height).toBe(12 + 2 * 16 + 12);
    expect(measured.lines.join(' | ')).toContain('© Provider Four');
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
