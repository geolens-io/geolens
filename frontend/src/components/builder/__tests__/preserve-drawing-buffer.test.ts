/**
 * PERF-08 (Phase 274): regression-lock that BuilderMap drops the always-on
 * preserveDrawingBuffer constructor flag and that capture paths use the
 * documented triggerRepaint() + once('render') pattern instead.
 *
 * Uses Vite `?raw` imports (no node:fs / @types/node dependency in tsconfig.app.json).
 */
import { describe, it, expect } from 'vitest';
import builderMapSrc from '../BuilderMap.tsx?raw';
import useSaveSrc from '../hooks/use-builder-save.ts?raw';

describe('PERF-08: WebGL canvas buffer is not retained permanently', () => {
  it('BuilderMap does NOT set preserveDrawingBuffer: true', () => {
    // Strip /* */ comments and // line comments to avoid false positives
    const codeOnly = builderMapSrc
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
    // The literal `preserveDrawingBuffer: true` must not appear in code.
    expect(codeOnly).not.toMatch(/preserveDrawingBuffer\s*:\s*true/);
  });

  it('BuilderMap has a PERF-08 marker comment explaining the change', () => {
    expect(builderMapSrc).toMatch(/PERF-08/);
  });

  it('use-builder-save.ts calls triggerRepaint in at least 2 places', () => {
    const matches = useSaveSrc.match(/triggerRepaint\(\)/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("use-builder-save.ts uses map.once('render', ...) for capture paths", () => {
    const matches = useSaveSrc.match(/once\(\s*['"]render['"]/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it('captureThumbnail docstring no longer claims preserveDrawingBuffer guarantees persistence', () => {
    // The phrase "preserveDrawingBuffer guarantees" must be absent from
    // the active code/comments — its presence indicated the prior
    // mechanism. Reference mention in a "see also" link is fine.
    expect(useSaveSrc).not.toMatch(/preserveDrawingBuffer guarantees canvas contents persist/);
  });
});
