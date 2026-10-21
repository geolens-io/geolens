import { describe, expect, it } from 'vitest';
import { MAX_WKT_LENGTH } from '../copc-limits';
import { parseCopcCrs } from '../copc-crs';

const UTM =
  'PROJCS["WGS 84 / UTM zone 10N",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-123],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]]';

describe('parseCopcCrs', () => {
  it('reads a projected CRS, with metres for Z', () => {
    expect(parseCopcCrs(UTM)).toEqual({ horizontalWkt: UTM, zToMeters: 1 });
  });

  it('splits a compound CRS and takes the vertical unit from VERT_CS', () => {
    const compound = `COMPD_CS["NAD83 + NAVD88 (ftUS)",${UTM},VERT_CS["NAVD88 height (ftUS)",VERT_DATUM["NAVD88",2005],UNIT["US survey foot",0.304800609601219],AXIS["Up",UP]]]`;
    const crs = parseCopcCrs(compound);
    expect(crs?.horizontalWkt).toBe(UTM);
    expect(crs?.zToMeters).toBeCloseTo(0.3048006, 6);
  });

  it.each([
    ['nothing', undefined],
    ['an empty string', ''],
    ['text proj4 cannot read', 'not a CRS'],
    ['an oversized WKT', `PROJCS["${'x'.repeat(MAX_WKT_LENGTH)}"]`],
    ['a compound CRS without a horizontal part', 'COMPD_CS["x",VERT_CS["h",UNIT["metre",1]]]'],
  ])('refuses %s', (_label, wkt) => {
    expect(parseCopcCrs(wkt)).toBeNull();
  });

  it('ignores an absurd vertical unit factor', () => {
    const compound = `COMPD_CS["x",${UTM},VERT_CS["h",VERT_DATUM["d",2005],UNIT["huge",1e30]]]`;
    expect(parseCopcCrs(compound)?.zToMeters).toBe(1);
  });
});
