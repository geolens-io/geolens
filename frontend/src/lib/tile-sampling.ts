/**
 * Which first-party vector tiles the server sent as a sample because the tile
 * held more features than its cap, keyed by the tile URL MapLibre requested.
 */

export const TILE_SAMPLED_HEADER = 'X-GeoLens-Tile-Sampled';

// A long session over a dense layer visits many tiles; only the view matters.
const MAX_SAMPLED_TILES = 2000;

const sampledTiles = new Set<string>();
const listeners = new Set<() => void>();

export function recordTileSampling(url: string, sampled: boolean): void {
  const changed = sampled ? !sampledTiles.has(url) : sampledTiles.delete(url);
  if (!changed) return;
  if (sampled) {
    sampledTiles.add(url);
    if (sampledTiles.size > MAX_SAMPLED_TILES) {
      sampledTiles.delete(sampledTiles.values().next().value as string);
    }
  }
  for (const listener of listeners) listener();
}

export function isTileSampled(url: string): boolean {
  return sampledTiles.has(url);
}

/** Call `listener` whenever a tile becomes sampled or stops being sampled. */
export function subscribeTileSampling(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
