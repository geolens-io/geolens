/** Longitude relative to the origin, wrapped into [-180, 180) so a cloud across the antimeridian stays contiguous. */
export function lngOffset(lng: number, originLng: number): number {
  return ((((lng - originLng) % 360) + 540) % 360) - 180;
}
