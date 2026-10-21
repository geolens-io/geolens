/**
 * regression-lock that map-rendering pages lazy-load
 * their Map child component, keeping map-vendor out of the eager page chunk.
 *
 * Uses Vite's `?raw` query suffix to load page sources as strings at build
 * time — no node fs needed, runs purely in the browser test environment.
 */
import { describe, it, expect } from 'vitest';
import datasetPageSrc from '@/pages/DatasetPage.tsx?raw';
import datasetMapSrc from '@/components/dataset/DatasetMap.tsx?raw';
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

  it('DatasetMap lazy-loads the 3D overlay, and the overlay lazy-loads the deck.gl layers', async () => {
    expect(datasetMapSrc).not.toMatch(/^import .*viewer3d\/Dataset3DOverlay/m);
    expect(datasetMapSrc).toMatch(
      /lazy\(\(\)\s*=>\s*import\(['"]@\/components\/dataset\/viewer3d\/Dataset3DOverlay['"]/
    );
    const overlaySrc = (await import('@/components/dataset/viewer3d/Dataset3DOverlay.tsx?raw')).default;
    expect(overlaySrc).not.toMatch(/^import .*['"]\.\/tileset-layers['"]/m);
    expect(overlaySrc).toMatch(/import\(['"]\.\/tileset-layers['"]\)/);
    expect(overlaySrc).not.toMatch(/from ['"]@loaders\.gl|from ['"]@deck\.gl\/(geo-layers|layers|mesh-layers)/);
  });
});
