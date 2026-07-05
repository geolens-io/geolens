import { stripPrivateLayoutKeys } from '../map-sync';

// fix(#403): builder-private underscore layout keys (the _minzoom/_maxzoom
// zoom-range channel authored by LayerStyleEditor) are consumed by
// syncLayerZoomRange, never by MapLibre. Passing them into map.addLayer fails
// style validation ("unknown property") and the whole layer is silently
// dropped on reload — so they must be stripped before the adapter input.
describe('stripPrivateLayoutKeys', () => {
  it('drops underscore-prefixed keys and keeps real layout properties', () => {
    expect(
      stripPrivateLayoutKeys({
        '_minzoom': 12.5,
        '_maxzoom': 18,
        'line-cap': 'round',
        'line-join': 'round',
      }),
    ).toEqual({ 'line-cap': 'round', 'line-join': 'round' });
  });

  it('returns the same object when nothing needs stripping', () => {
    const layout = { 'line-cap': 'round' };
    expect(stripPrivateLayoutKeys(layout)).toBe(layout);
  });

  it('handles an empty layout', () => {
    expect(stripPrivateLayoutKeys({})).toEqual({});
  });
});
