/**
 * PERF-07 (Phase 274): regression-lock that AttributeTable uses
 * @tanstack/react-virtual for row windowing and that the virtualizer is wired
 * against the parent scroll element.
 *
 * Uses Vite's `?raw` query suffix to load the source as a string at build time
 * — no node fs needed, runs purely in the browser test environment. Same
 * pattern used by `DatasetMap.lazy.test.tsx` for PERF-06.
 *
 * jsdom does not compute layout (getBoundingClientRect returns zeros), so a
 * full DOM render test cannot meaningfully assert that virtualization renders
 * the correct subset of rows. Instead, this suite uses static-source
 * assertions to lock the wiring contract: the imports, the parentRef, the
 * useVirtualizer call, and the key shape of the body render path.
 * Render-correctness is exercised manually + via Playwright in the existing
 * dataset E2E spec.
 */
import { describe, it, expect } from 'vitest';
import attributeTableSrc from '@/components/dataset/AttributeTable.tsx?raw';

describe('PERF-07: AttributeTable virtualization wiring', () => {
  it('imports useVirtualizer from @tanstack/react-virtual', () => {
    expect(attributeTableSrc).toMatch(
      /import\s*\{[^}]*\buseVirtualizer\b[^}]*\}\s*from\s*['"]@tanstack\/react-virtual['"]/,
    );
  });

  it('declares a parentRef wired into the scroll container', () => {
    expect(attributeTableSrc).toMatch(/parentRef\s*=\s*useRef/);
    expect(attributeTableSrc).toMatch(/ref=\{parentRef\}/);
  });

  it('calls useVirtualizer with getScrollElement returning parentRef.current', () => {
    expect(attributeTableSrc).toMatch(/getScrollElement:[^,}]*parentRef/);
  });

  it('renders the body via getVirtualItems()', () => {
    expect(attributeTableSrc).toMatch(/virtualizer\.getVirtualItems\(\)/);
  });

  it('uses getTotalSize for the scrollable height', () => {
    expect(attributeTableSrc).toMatch(/virtualizer\.getTotalSize\(\)/);
  });

  it('preserves cellPadding and existing column visibility logic', () => {
    expect(attributeTableSrc).toMatch(/cellPadding/);
    expect(attributeTableSrc).toMatch(/columnVisibility/);
  });
});
