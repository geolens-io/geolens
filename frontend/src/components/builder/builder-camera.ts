import type { Map as MaplibreMap } from 'maplibre-gl';

/**
 * The five viewport fields a map save persists.
 *
 * The builder has no explicit "set home view" control: the stored view is the
 * camera at the last save. `readMapCamera` and `savedMapCamera` are therefore
 * the SAME normalizer applied to the live map and to the server row, so the
 * dirty check can mean exactly "saving now would change the stored value".
 * Both sides must keep using it; comparing a raw `getCenter()` against a saved
 * float reintroduces the drift the rounding is here to absorb.
 */
export interface BuilderCamera {
  center_lng: number | null;
  center_lat: number | null;
  zoom: number | null;
  bearing: number;
  pitch: number;
}

/** A map row's stored view, as the save payload and the API response carry it. */
export interface SavedCameraFields {
  center_lng?: number | null;
  center_lat?: number | null;
  zoom?: number | null;
  bearing?: number | null;
  pitch?: number | null;
}

// fix(#1854): 6 decimals of longitude is about 11 cm, finer than any home view
// needs and far coarser than the float noise a round trip through the map
// transform introduces, so a resize or a reprojection cannot read as a pan.
const CAMERA_DECIMALS = 6;

function roundCameraValue(value: number | null | undefined): number | null {
  // A non-finite reading has to normalize to null: NaN !== NaN would pin the
  // unsaved indicator on for the rest of the session.
  if (value == null || !Number.isFinite(value)) return null;
  return Number(value.toFixed(CAMERA_DECIMALS));
}

/** The live map camera, at the precision and null handling a save persists. */
export function readMapCamera(map: MaplibreMap | null | undefined): BuilderCamera {
  const center = map?.getCenter?.();
  return {
    center_lng: roundCameraValue(center?.lng),
    center_lat: roundCameraValue(center?.lat),
    zoom: roundCameraValue(map?.getZoom?.()),
    bearing: roundCameraValue(map?.getBearing?.()) ?? 0,
    pitch: roundCameraValue(map?.getPitch?.()) ?? 0,
  };
}

/** A stored view, normalized identically to `readMapCamera`. */
export function savedMapCamera(saved: SavedCameraFields): BuilderCamera {
  return {
    center_lng: roundCameraValue(saved.center_lng),
    center_lat: roundCameraValue(saved.center_lat),
    zoom: roundCameraValue(saved.zoom),
    bearing: roundCameraValue(saved.bearing) ?? 0,
    pitch: roundCameraValue(saved.pitch) ?? 0,
  };
}

/**
 * Whether the map has a stored view at all. A map saved before it ever had a
 * camera keeps null center components, and BuilderMap's `hasSavedView` reads
 * the same two fields to decide whether to position from them.
 */
export function hasSavedMapCamera(saved: SavedCameraFields | undefined | null): boolean {
  return saved?.center_lng != null && saved?.center_lat != null;
}

export function sameMapCamera(a: BuilderCamera, b: BuilderCamera): boolean {
  return (
    a.center_lng === b.center_lng
    && a.center_lat === b.center_lat
    && a.zoom === b.zoom
    && a.bearing === b.bearing
    && a.pitch === b.pitch
  );
}
