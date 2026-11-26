# SPDX-License-Identifier: Apache-2.0
"""Land mask for the sign-in globe's dot lattice (`LAND_MASK` in
`frontend/src/lib/login-globe.ts`).

Input: `ne_110m_land.geojson` from `nvkelso/natural-earth-vector`, tag `v5.1.2`
(Natural Earth, public domain). A lattice point is land when its centre lies
inside a land polygon and outside its holes.

    python3 scripts/login-globe-land-mask.py ne_110m_land.geojson 3 120

The arguments are the latitude step in degrees and the dot count on the
equator. The command prints a JSON object whose `mask` is the base64 string
to paste. A fourth argument also draws the lattice as ASCII on stderr.
"""

import base64
import json
import math
import sys

src, step, per_equator = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
rings = []
for f in json.load(open(src))["features"]:
    g = f["geometry"]
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    for p in polys:
        xs = [c[0] for c in p[0]]
        ys = [c[1] for c in p[0]]
        rings.append((min(xs), max(xs), min(ys), max(ys), p))


def inside_ring(x, y, ring):
    c = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def land(lon, lat):
    for x0, x1, y0, y1, p in rings:
        if (
            x0 <= lon <= x1
            and y0 <= lat <= y1
            and inside_ring(lon, lat, p[0])
            and not any(inside_ring(lon, lat, h) for h in p[1:])
        ):
            return True
    return False


bits = []
lat = -90 + step / 2
rows = []
while lat < 90:
    count = max(1, round(per_equator * math.cos(math.radians(lat))))
    row = [land(-180 + 360 * (j + 0.5) / count, lat) for j in range(count)]
    rows.append((lat, row))
    bits += row
    lat += step
by = bytearray((len(bits) + 7) // 8)
for i, b in enumerate(bits):
    if b:
        by[i >> 3] |= 1 << (i & 7)
print(
    json.dumps(
        {
            "step": step,
            "perEquator": per_equator,
            "points": len(bits),
            "land": sum(bits),
            "mask": base64.b64encode(bytes(by)).decode(),
        }
    )
)
if len(sys.argv) > 4:
    for lat, row in reversed(rows):
        pad = (per_equator - len(row)) // 2
        sys.stderr.write(" " * pad + "".join("#" if b else "." for b in row) + "\n")
