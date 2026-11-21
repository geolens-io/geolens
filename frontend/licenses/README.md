# Vendored license texts

These bundled packages publish no license file to npm, so the build reads
their notice from here when it writes `third-party-licenses.txt`. The build
fails if a bundled package has no license text in either place.

A `<package>.notice.txt` file is appended to that package's section, for a
notice the package's own license file leaves out.

| File | Source |
| --- | --- |
| `bidi-js.notice.txt` | https://www.unicode.org/license.txt, for the Unicode data tables inside bidi-js |
| `draco3d.txt` | https://github.com/google/draco/blob/main/LICENSE |
| `laz-perf.txt` | https://github.com/hobuinc/laz-perf/blob/master/COPYING |
| `murmurhash-js.txt` | the License section of https://github.com/mikolalysenko/murmurhash-js/blob/master/README.md |
| `pmtiles.txt` | https://github.com/protomaps/PMTiles/blob/main/LICENSE |
| `react-remove-scroll-bar.txt` | https://github.com/theKashey/react-remove-scroll-bar/blob/master/LICENSE |
| `terra-draw.txt`, `terra-draw-maplibre-gl-adapter.txt` | https://github.com/JamesLMilner/terra-draw/blob/main/LICENSE |
