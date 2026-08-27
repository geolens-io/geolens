import { describe, expect, it, vi } from 'vitest';
import * as maplibregl from 'maplibre-gl';
import { Protocol } from 'pmtiles';

/**
 * feat(pmtiles): `@/lib/maplibre-worker` registers the `pmtiles://` protocol
 * at module scope (alongside the pre-existing `setWorkerUrl` call), so every
 * surface that constructs a map picks it up for free via the shared
 * side-effect import. `maplibre-gl` and `pmtiles` are mocked globally in
 * `src/test/setup.ts`; this just asserts the module wires them together.
 */
describe('maplibre-worker pmtiles protocol registration', () => {
  it('registers the pmtiles protocol against maplibre-gl on import', async () => {
    await import('../maplibre-worker');

    expect(Protocol).toHaveBeenCalled();
    expect(maplibregl.addProtocol).toHaveBeenCalledWith('pmtiles', expect.any(Function));
    expect(maplibregl.setWorkerUrl).toHaveBeenCalled();
  });

  it('is safe to import more than once (idempotent module singleton)', async () => {
    vi.resetModules();
    await import('../maplibre-worker');
    const callsAfterFirstImport = (maplibregl.addProtocol as ReturnType<typeof vi.fn>).mock.calls.length;

    // A second import of the same specifier resolves to the cached module —
    // no re-execution, no duplicate registration.
    await import('../maplibre-worker');
    expect((maplibregl.addProtocol as ReturnType<typeof vi.fn>).mock.calls.length).toBe(
      callsAfterFirstImport,
    );
  });
});
