import type { Map as MaplibreMap } from 'maplibre-gl';

/** A layer as the fake map holds it. */
export interface RecordedLayer {
  id: string;
  type: string;
  source?: string;
  'source-layer'?: string;
  filter?: unknown;
  layout: Record<string, unknown>;
  paint: Record<string, unknown>;
  minzoom?: number;
  maxzoom?: number;
}

interface RecordedSource {
  type: string;
  tiles?: string[];
  spec: Record<string, unknown>;
  serialize: () => Record<string, unknown>;
  setTiles?: (tiles: string[]) => void;
  setData?: (data: unknown) => void;
}

/** Paint keys MapLibre rejects unless they hold an expression. */
const EXPRESSION_ONLY_PAINT = new Set(['heatmap-color', 'line-gradient', 'color-relief-color']);

/** How long a vector source takes to adopt the tiles `setTiles` hands it. */
export const TILE_ADOPTION_MS = 50;

function copy<T>(value: T): T {
  return value === undefined ? value : structuredClone(value);
}

/**
 * An in-memory MapLibre map that keeps the style it is given and records each
 * call. Like MapLibre, it refuses a write it cannot apply and reports an error
 * instead of throwing, and a vector source adopts new tiles only after a delay.
 */
export class RecordingMap {
  readonly calls: [string, ...unknown[]][] = [];
  readonly errors: string[] = [];
  private readonly order: string[] = [];
  private readonly layers = new Map<string, RecordedLayer>();
  private readonly sources = new Map<string, RecordedSource>();
  private readonly images = new Map<string, unknown>();
  private readonly sprites: { id: string; url: string }[] = [];

  /** The fake as the code under test takes it. */
  get map(): MaplibreMap {
    return this as unknown as MaplibreMap;
  }

  /** The layers in stack order, bottom first. */
  layerIds(): string[] {
    return [...this.order];
  }

  /** A layer's current state, or undefined when the map has no such layer. */
  layer(id: string): RecordedLayer | undefined {
    return copy(this.layers.get(id));
  }

  /** The calls made with one method, without the method name. */
  callsTo(method: string): unknown[][] {
    return this.calls.filter(([name]) => name === method).map(([, ...args]) => args);
  }

  getLayer(id: string) {
    return this.layers.get(id);
  }

  addLayer(layer: Record<string, unknown>, beforeId?: string) {
    this.calls.push(['addLayer', copy(layer), beforeId]);
    const id = layer.id as string;
    if (this.layers.has(id)) return this.error(`Layer "${id}" already exists on this map.`);
    const source = layer.source as string | undefined;
    if (source !== undefined && !this.sources.has(source)) return this.error(`Source "${source}" not found.`);
    const paint = (layer.paint ?? {}) as Record<string, unknown>;
    for (const [key, value] of Object.entries(paint)) {
      if (EXPRESSION_ONLY_PAINT.has(key) && !Array.isArray(value)) return this.error(`${id}: ${key} needs an expression.`);
    }
    this.layers.set(id, {
      id,
      type: layer.type as string,
      ...(source !== undefined ? { source } : {}),
      ...(layer['source-layer'] !== undefined ? { 'source-layer': layer['source-layer'] as string } : {}),
      ...(layer.filter !== undefined ? { filter: copy(layer.filter) } : {}),
      ...(layer.minzoom !== undefined ? { minzoom: layer.minzoom as number } : {}),
      ...(layer.maxzoom !== undefined ? { maxzoom: layer.maxzoom as number } : {}),
      layout: copy((layer.layout ?? {}) as Record<string, unknown>),
      paint: copy(paint),
    });
    const at = beforeId === undefined ? -1 : this.order.indexOf(beforeId);
    if (at < 0) this.order.push(id);
    else this.order.splice(at, 0, id);
    return this.map;
  }

  removeLayer(id: string) {
    this.calls.push(['removeLayer', id]);
    if (!this.layers.delete(id)) return this.error(`Cannot remove non-existing layer "${id}".`);
    this.order.splice(this.order.indexOf(id), 1);
    return this.map;
  }

  moveLayer(id: string, beforeId?: string) {
    this.calls.push(['moveLayer', id, beforeId]);
    if (!this.layers.has(id)) return this.error(`Cannot move non-existing layer "${id}".`);
    this.order.splice(this.order.indexOf(id), 1);
    const at = beforeId === undefined ? -1 : this.order.indexOf(beforeId);
    if (at < 0) this.order.push(id);
    else this.order.splice(at, 0, id);
    return this.map;
  }

  getPaintProperty(id: string, name: string) {
    // MapLibre reads through the layer it finds, so a missing layer throws.
    return copy(this.requireLayer(id).paint[name]);
  }

  setPaintProperty(id: string, name: string, value: unknown) {
    this.calls.push(['setPaintProperty', id, name, copy(value)]);
    const layer = this.layers.get(id);
    if (!layer) return this.error(`Cannot style non-existing layer "${id}".`);
    if (value === undefined) {
      delete layer.paint[name];
    } else if (EXPRESSION_ONLY_PAINT.has(name) && !Array.isArray(value)) {
      return this.error(`${id}: ${name} needs an expression.`);
    } else {
      layer.paint[name] = copy(value);
    }
    return this.map;
  }

  getLayoutProperty(id: string, name: string) {
    return copy(this.requireLayer(id).layout[name]);
  }

  setLayoutProperty(id: string, name: string, value: unknown) {
    this.calls.push(['setLayoutProperty', id, name, copy(value)]);
    const layer = this.layers.get(id);
    if (!layer) return this.error(`Cannot style non-existing layer "${id}".`);
    if (value === undefined) delete layer.layout[name];
    else layer.layout[name] = copy(value);
    return this.map;
  }

  getFilter(id: string) {
    return copy(this.requireLayer(id).filter);
  }

  setFilter(id: string, filter: unknown) {
    this.calls.push(['setFilter', id, copy(filter)]);
    const layer = this.layers.get(id);
    if (!layer) return this.error(`Cannot filter non-existing layer "${id}".`);
    if (filter === null || filter === undefined) delete layer.filter;
    else layer.filter = copy(filter);
    return this.map;
  }

  setLayerZoomRange(id: string, minzoom: number, maxzoom: number) {
    this.calls.push(['setLayerZoomRange', id, minzoom, maxzoom]);
    const layer = this.layers.get(id);
    if (!layer) return this.error(`Cannot set the zoom range of non-existing layer "${id}".`);
    layer.minzoom = minzoom;
    layer.maxzoom = maxzoom;
    return this.map;
  }

  getSource(id: string) {
    return this.sources.get(id);
  }

  addSource(id: string, spec: Record<string, unknown>) {
    this.calls.push(['addSource', id, copy(spec)]);
    if (this.sources.has(id)) return this.error(`Source "${id}" already exists.`);
    const source: RecordedSource = {
      type: spec.type as string,
      ...(Array.isArray(spec.tiles) ? { tiles: [...(spec.tiles as string[])] } : {}),
      spec: copy(spec),
      serialize: () => copy(source.spec),
    };
    if (source.type === 'vector') {
      source.setTiles = (tiles: string[]) => {
        this.calls.push(['setTiles', id, [...tiles]]);
        source.spec = { ...source.spec, tiles: [...tiles] };
        setTimeout(() => { source.tiles = [...tiles]; }, TILE_ADOPTION_MS);
      };
    }
    if (source.type === 'geojson') {
      source.setData = (data: unknown) => {
        this.calls.push(['setData', id, copy(data)]);
        source.spec = { ...source.spec, data: copy(data) };
      };
    }
    this.sources.set(id, source);
    return this.map;
  }

  removeSource(id: string) {
    this.calls.push(['removeSource', id]);
    const user = this.order.find((layerId) => this.layers.get(layerId)?.source === id);
    if (user) return this.error(`Source "${id}" cannot be removed while layer "${user}" is using it.`);
    this.sources.delete(id);
    return this.map;
  }

  refreshTiles(id: string) {
    this.calls.push(['refreshTiles', id]);
  }

  getStyle() {
    return {
      version: 8,
      sources: Object.fromEntries([...this.sources].map(([id, source]) => [id, source.serialize()])),
      layers: this.order.map((id) => copy(this.layers.get(id))),
    };
  }

  hasImage(id: string) {
    return this.images.has(id);
  }

  addImage(id: string, image: unknown, options?: unknown) {
    this.calls.push(['addImage', id, options]);
    if (this.images.has(id)) return this.error(`An image named "${id}" already exists.`);
    this.images.set(id, image);
    return this.map;
  }

  getSprite() {
    return this.sprites.map((sprite) => ({ ...sprite }));
  }

  addSprite(id: string, url: string) {
    this.calls.push(['addSprite', id, url]);
    if (this.sprites.some((sprite) => sprite.id === id)) return this.error(`Sprite "${id}" already exists.`);
    this.sprites.push({ id, url });
    return this.map;
  }

  isStyleLoaded() {
    return true;
  }

  triggerRepaint() {
    this.calls.push(['triggerRepaint']);
  }

  private requireLayer(id: string): RecordedLayer {
    const layer = this.layers.get(id);
    if (!layer) throw new TypeError(`Cannot read properties of undefined (layer "${id}")`);
    return layer;
  }

  private error(message: string) {
    this.errors.push(message);
    return this.map;
  }
}
