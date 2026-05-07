/**
 * PERF-06 (Phase 274): regression-lock that map-rendering pages lazy-load
 * their Map child component, keeping map-vendor out of the eager page chunk.
 *
 * Uses Vite's `?raw` query suffix to load page sources as strings at build
 * time — no node fs needed, runs purely in the browser test environment.
 */
import { describe, it, expect } from 'vitest';
import datasetPageSrc from '@/pages/DatasetPage.tsx?raw';
import mapBuilderPageSrc from '@/pages/MapBuilderPage.tsx?raw';
import publicViewerPageSrc from '@/pages/PublicViewerPage.tsx?raw';
import publicMapViewerPageSrc from '@/pages/PublicMapViewerPage.tsx?raw';

describe('PERF-06: map-rendering pages lazy-load their Map child', () => {
  it('DatasetPage uses lazy() for DatasetMap', () => {
    const src = datasetPageSrc;
    // No eager top-level static import
    expect(src).not.toMatch(
      /^import \{[^}]*\bDatasetMap\b[^}]*\}\s+from\s+['"]@\/components\/dataset\/DatasetMap['"]/m
    );
    // Has lazy() declaration referencing the same path
    expect(src).toMatch(
      /lazy\(\(\)\s*=>\s*import\(['"]@\/components\/dataset\/DatasetMap['"]/
    );
    expect(src).toMatch(/<Suspense/);
  });

  it('MapBuilderPage uses lazy() for BuilderMap', () => {
    const src = mapBuilderPageSrc;
    expect(src).not.toMatch(
      /^import \{[^}]*\bBuilderMap\b[^}]*\}\s+from\s+['"]@\/components\/builder\/BuilderMap['"]/m
    );
    expect(src).toMatch(
      /lazy\(\(\)\s*=>\s*import\(['"]@\/components\/builder\/BuilderMap['"]/
    );
    expect(src).toMatch(/<Suspense/);
  });

  it('PublicViewerPage uses lazy() for ViewerMap', () => {
    const src = publicViewerPageSrc;
    expect(src).not.toMatch(
      /^import \{[^}]*\bViewerMap\b[^}]*\}\s+from\s+['"]@\/components\/viewer\/ViewerMap['"]/m
    );
    expect(src).toMatch(
      /lazy\(\(\)\s*=>\s*import\(['"]@\/components\/viewer\/ViewerMap['"]/
    );
    expect(src).toMatch(/<Suspense/);
  });

  it('PublicMapViewerPage uses lazy() for ViewerMap', () => {
    const src = publicMapViewerPageSrc;
    expect(src).not.toMatch(
      /^import \{[^}]*\bViewerMap\b[^}]*\}\s+from\s+['"]@\/components\/viewer\/ViewerMap['"]/m
    );
    expect(src).toMatch(
      /lazy\(\(\)\s*=>\s*import\(['"]@\/components\/viewer\/ViewerMap['"]/
    );
    expect(src).toMatch(/<Suspense/);
  });
});
