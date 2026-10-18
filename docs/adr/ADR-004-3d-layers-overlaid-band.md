# ADR-004: 3D layers draw in an overlaid band

**Status:** accepted. **Scope:** how point cloud and 3D tileset saved layers
render beside MapLibre layers in the builder, shared viewer and embed.

## Context

Point clouds and 3D tilesets render through deck.gl on top of the MapLibre map.
deck.gl can draw either interleaved with MapLibre's own layers, sharing its
WebGL context, or on a separate canvas laid over the map.

Interleaved mode respects drawing order and depth against fill-extrusions, but
the layer does not come back after a WebGL context loss: luma.gl caches its
device on the shared context, so a remounted overlay attaches to the dead
device, and clearing that cache blanks the basemap. The overlaid canvas
recovers cleanly when it remounts on its own `webglcontextrestored`.

## Decision

3D layers draw on the overlaid canvas, in a band above every MapLibre layer,
including basemap labels, 2D saved layers and extrusions. The layer list keeps
3D layers in their own group and allows reordering only inside it.

Saved layers still store their full drawing order across both bands, so a later
switch to interleaved rendering needs no migration.

Overlaid rendering has two other effects. Thumbnails and PNG downloads
composite the deck canvas over the map canvas, and 3D layers neither follow
MapLibre terrain nor depth-test against 2D content.

## Revisit when

Interleaved deck.gl layers survive context loss on the maplibre-gl and deck.gl
versions we ship, or users need 2D layers drawn over 3D content.
