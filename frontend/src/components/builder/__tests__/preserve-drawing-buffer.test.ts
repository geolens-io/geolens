/**
 * PERF-08 (Phase 274): regression-lock that BuilderMap drops the always-on
 * preserveDrawingBuffer constructor flag and that capture paths use the
 * documented triggerRepaint() + once('render') pattern instead.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const builderMapPath = resolve(__dirname, '../BuilderMap.tsx');
const useSavePath = resolve(__dirname, '../hooks/use-builder-save.ts');

function read(p: string): string {
  return readFileSync(p, 'utf-8');
}

describe('PERF-08: WebGL canvas buffer is not retained permanently', () => {
  it('BuilderMap does NOT set preserveDrawingBuffer: true', () => {
    const src = read(builderMapPath);
    // Strip /* */ comments and // line comments to avoid false positives
    const codeOnly = src
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
    // The literal `preserveDrawingBuffer: true` must not appear in code.
    expect(codeOnly).not.toMatch(/preserveDrawingBuffer\s*:\s*true/);
  });

  it('BuilderMap has a PERF-08 marker comment explaining the change', () => {
    const src = read(builderMapPath);
    expect(src).toMatch(/PERF-08/);
  });

  it('use-builder-save.ts calls triggerRepaint in at least 2 places', () => {
    const src = read(useSavePath);
    const matches = src.match(/triggerRepaint\(\)/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("use-builder-save.ts uses map.once('render', ...) for capture paths", () => {
    const src = read(useSavePath);
    const matches = src.match(/once\(\s*['"]render['"]/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it('captureThumbnail docstring no longer claims preserveDrawingBuffer guarantees persistence', () => {
    const src = read(useSavePath);
    // The phrase "preserveDrawingBuffer guarantees" must be absent from
    // the active code/comments — its presence indicated the prior
    // mechanism. Reference mention in a "see also" link is fine.
    expect(src).not.toMatch(/preserveDrawingBuffer guarantees canvas contents persist/);
  });
});
