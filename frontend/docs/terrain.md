# Terrain (3D Elevation)

GeoLens can drape the map surface over a Digital Elevation Model (DEM) to produce
a 3D terrain mesh. Enable it from the map builder's **Terrain** settings by
selecting a DEM raster layer as the elevation source.

## How terrain reads a DEM

The DEM raster is served as `terrainrgb`-encoded tiles (the Mapbox/MapLibre
RGB elevation encoding). MapLibre decodes the RGB channels back into an elevation
per pixel and raises the surface accordingly.

### Nodata masking (#186)

DEMs commonly carry a **nodata** sentinel (e.g. `-9999`) for pixels outside the
captured area. Tiles that only partially overlap the DEM footprint contain a mix
of real elevations and nodata fill. Left unmasked, a `-9999` fill encodes as an
extreme elevation and produces spikes or cliffs at the DEM boundary.

GeoLens masks the DEM's nodata when building the `terrainrgb` tiles so those
fill pixels render transparent instead of as bogus elevation:

- The mask value is taken from the dataset's **recorded nodata** (captured from
  the COG metadata at ingest).
- When the DEM declares no nodata, GeoLens falls back to the canonical DEM
  sentinel **`-9999`**, which is far below any real terrestrial elevation, so the
  mask never removes valid terrain.

The fully-outside-the-footprint case (a tile entirely beyond the DEM bounds) is
already handled separately — the tile source carries the DEM `bounds`, so those
tiles are never requested and the surface stays at sea level there.

## Small / high-resolution DEMs over a large view

A high-resolution DEM (e.g. swissALTI3D over a single AOI) typically covers only
a small geographic extent. When you zoom out, that DEM covers just a sliver of
the viewport — you get a small raised patch surrounded by flat ground, which
reads as a "pedestal".

**Recommendation: drape the high-res DEM over a coarse global DEM.**

For small AOIs, layer your high-resolution DEM *on top of* a coarse global DEM
such as **Copernicus GLO-30** (~30 m global coverage). The global DEM provides
continuous, smooth elevation across the whole map, while the high-res DEM refines
the terrain inside its footprint. This avoids the pedestal effect and keeps the
surrounding terrain plausible.

If you only have the small DEM loaded, either:

- **Zoom in** to the DEM's extent so it fills the view, or
- **Add a coarse global DEM** beneath it as described above.

The builder surfaces a non-blocking warning when an active terrain DEM covers
less than ~25% of the current viewport, pointing you at these options.

## Related limitations

- **Vertical units:** terrain assumes elevation values are in **meters**. DEMs
  in other units (e.g. US survey feet) will exaggerate the terrain. The builder
  warns when the DEM's vertical units are non-meter or unknown.
- **Partial-DEM "pedestal" at the footprint edge** is expected for an isolated
  small DEM — see the recommendation above to mitigate it.

---

> **Cross-repo follow-up:** the public user documentation lives at
> `docs.getgeolens.com` (the `getgeolens.com` repo). The draping recommendation
> and the nodata-masking behaviour above should be mirrored into the public
> terrain docs there. Tracked as a follow-up to issue #186.
