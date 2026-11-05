import type { Map as MaplibreMap } from 'maplibre-gl';

export const LAYER_FADE_MS = 400;

/** A layer mid-fade: the factor its sync pass multiplies into its opacity. */
export interface LayerFade {
  factor: number;
  /** The paint keys given a transition, whose override is cleared when the fade ends. */
  touched: Set<string>;
  timer?: ReturnType<typeof setTimeout>;
  stopWaiting?: () => void;
}

/**
 * Writes a layer's paint, and its visibility when asked, from its current
 * state, to the map or a wrapper of it. A fade writes visibility only where it
 * changes: showing a layer and hiding it again.
 */
type Write = (map: MaplibreMap, visibility: boolean) => void;

/**
 * The map with every paint write preceded by a transition of `ms` on that key,
 * so the sync pass that writes a layer's opacity also animates it, whichever
 * keys its adapter folds the opacity into.
 */
function transitioned(map: MaplibreMap, ms: number, touched: Set<string>): MaplibreMap {
  return new Proxy(map, {
    get(target, property) {
      if (property !== 'setPaintProperty') {
        const value = Reflect.get(target, property);
        return typeof value === 'function' ? value.bind(target) : value;
      }
      return (layerId: string, name: string, value: unknown, options?: object) => {
        if (!name.endsWith('-transition') && target.getLayer(layerId)) {
          try {
            target.setPaintProperty(layerId, `${name}-transition` as never, { duration: ms, delay: 0 } as never);
            touched.add(`${layerId}\0${name}`);
          } catch {
            // A key MapLibre doesn't know has no transition to set; its write still goes through.
          }
        }
        target.setPaintProperty(layerId, name as never, value as never, options as never);
      };
    },
  });
}

function clearTransitions(map: MaplibreMap, touched: Set<string>) {
  for (const entry of touched) {
    const [layerId, name] = entry.split('\0');
    if (map.getLayer(layerId)) map.setPaintProperty(layerId, `${name}-transition` as never, undefined as never);
  }
  touched.clear();
}

/**
 * Fades layers in and out by running their ordinary sync pass with an opacity
 * factor and MapLibre paint transitions. The sync pass stays the one writer:
 * it reads `entries` for a layer that is still fading and writes it visible at
 * that factor, and a layer is hidden only when its fade-out ends.
 */
export class LayerFades {
  readonly entries = new Map<string, LayerFade>();

  /** Fades the layer out, then hides it. */
  hide(map: MaplibreMap, key: string, ms: number, write: Write) {
    const fade = this.take(key);
    fade.factor = 0;
    write(transitioned(map, ms, fade.touched), false);
    fade.timer = setTimeout(() => {
      this.entries.delete(key);
      clearTransitions(map, fade.touched);
      // Hidden by now, so the configured opacity comes back unseen.
      write(map, true);
    }, ms);
  }

  /** Shows the layer and fades it in, from where a fade-out had reached or from nothing. */
  show(map: MaplibreMap, key: string, ms: number, write: Write) {
    const resumed = this.entries.has(key);
    const fade = this.take(key);
    const end = () => {
      this.entries.delete(key);
      clearTransitions(map, fade.touched);
    };
    const animate = () => {
      fade.factor = 1;
      write(transitioned(map, ms, fade.touched), false);
      fade.timer = setTimeout(end, ms);
    };
    if (resumed) {
      animate();
      return;
    }
    // The zero write needs a frame to land before the fade runs, since MapLibre keeps only the last write of a task.
    fade.factor = 0;
    write(transitioned(map, 0, fade.touched), true);
    map.once('render', animate);
    fade.stopWaiting = () => map.off('render', animate);
  }

  /** Ends the layer's fade for good, so the caller can write its current state at once. True when it had one. */
  release(map: MaplibreMap, key: string): boolean {
    const fade = this.entries.get(key);
    if (!fade) return false;
    this.stop(fade);
    this.entries.delete(key);
    clearTransitions(map, fade.touched);
    return true;
  }

  /** Stops every fade where it is; the map is going away, so nothing is restored. */
  cancelAll() {
    this.entries.forEach((fade) => this.stop(fade));
    this.entries.clear();
  }

  private take(key: string): LayerFade {
    const previous = this.entries.get(key);
    if (previous) this.stop(previous);
    const fade: LayerFade = { factor: 1, touched: previous?.touched ?? new Set() };
    this.entries.set(key, fade);
    return fade;
  }

  private stop(fade: LayerFade) {
    clearTimeout(fade.timer);
    fade.stopWaiting?.();
  }
}
