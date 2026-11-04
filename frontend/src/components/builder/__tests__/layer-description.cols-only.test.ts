import { describeLayers } from '@/components/builder/layer-description';
import { syncRenderContext, toSyncInput } from '@/components/builder/map-sync';
import { RENDER_CONTEXTS } from '@/test/fixtures/render-contexts';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';

function tileUrl(colsOnly: boolean | undefined, layer = SAVED_LAYERS.polygon) {
  const { sources, layers } = describeLayers([toSyncInput(layer)], { ...RENDER_CONTEXTS.builder, colsOnly });
  const source = sources.get(layers[0].sourceId) as { tiles: string[] };
  return source.tiles[0];
}

describe('lean vector tiles', () => {
  it('adds cols_only to the source URL when the context asks for it', () => {
    expect(tileUrl(true)).toContain('cols_only=true');
  });

  it('keeps today\'s URL when the context does not ask', () => {
    expect(tileUrl(false)).not.toContain('cols_only');
    expect(tileUrl(undefined)).not.toContain('cols_only');
  });

  it('asks by default from the sync render context, and lets a caller opt out', () => {
    expect(syncRenderContext(new Map(), undefined, undefined, undefined).colsOnly).toBe(true);
    expect(syncRenderContext(new Map(), undefined, undefined, { colsOnly: false }).colsOnly).toBe(false);
  });
});
