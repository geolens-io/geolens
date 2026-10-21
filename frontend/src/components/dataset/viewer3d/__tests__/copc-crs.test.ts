import { describe, expect, it } from 'vitest';
import { MAX_WKT_LENGTH } from '../copc-limits';
import { normalizeWkt, parseCopcCrs } from '../copc-crs';

const UTM =
  'PROJCS["WGS 84 / UTM zone 10N",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-123],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]]';

const UTM2 =
  'PROJCRS["WGS 84 / UTM zone 10N",BASEGEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]]],CONVERSION["UTM zone 10N",METHOD["Transverse Mercator",ID["EPSG",9807]],PARAMETER["Latitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433]],PARAMETER["Longitude of natural origin",-123,ANGLEUNIT["degree",0.0174532925199433]],PARAMETER["Scale factor at natural origin",0.9996,SCALEUNIT["unity",1]],PARAMETER["False easting",500000,LENGTHUNIT["metre",1]],PARAMETER["False northing",0,LENGTHUNIT["metre",1]]],CS[Cartesian,2],AXIS["(E)",east,ORDER[1],LENGTHUNIT["metre",1]],AXIS["(N)",north,ORDER[2],LENGTHUNIT["metre",1]]]';

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

  it('splits a WKT2 compound CRS and reads the vertical LENGTHUNIT', () => {
    const compound = `COMPOUNDCRS["NAD83 + NAVD88 (ftUS)",${UTM2},VERTCRS["NAVD88 height (ftUS)",VDATUM["NAVD88"],CS[vertical,1],AXIS["gravity-related height (H)",up,LENGTHUNIT["US survey foot",0.304800609601219]]]]`;
    const crs = parseCopcCrs(compound);
    expect(crs?.horizontalWkt).toBe(UTM2);
    expect(crs?.zToMeters).toBeCloseTo(0.3048006, 6);
  });

  it('reads the long-form WKT2 keywords the catalog accepts', () => {
    const long = UTM2.replace('PROJCRS[', 'PROJECTEDCRS[');
    const compound = `COMPOUNDCRS["x",${long},VERTICALCRS["h",VDATUM["d"],CS[vertical,1],AXIS["H",up,LENGTHUNIT["foot",0.3048]]]]`;
    const crs = parseCopcCrs(compound);
    expect(crs?.horizontalWkt).toBe(UTM2);
    expect(crs?.zToMeters).toBeCloseTo(0.3048, 6);
  });

  it('does not take the angular unit of a geographic CRS as a vertical scale', () => {
    const geographic = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]';
    expect(parseCopcCrs(geographic)).toEqual({ horizontalWkt: geographic, zToMeters: 1 });
    const geographic2 = 'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],CS[ellipsoidal,2],AXIS["lat",north],AXIS["lon",east],ANGLEUNIT["degree",0.0174532925199433]]';
    expect(parseCopcCrs(geographic2)?.zToMeters).toBe(1);
  });

  it('reads WKT with parentheses, padding and lowercase keywords as ingestion does', () => {
    const alt = ` compoundcrs ("x" , ${UTM2.replace(/\[/g, ' (').replace(/\]/g, ')')} , vertcrs ("h", vdatum ("d"), cs (vertical, 1), axis ("H", up, lengthunit ("foot", 0.3048))) )`;
    const crs = parseCopcCrs(alt);
    expect(crs?.horizontalWkt).toBe(UTM2);
    expect(crs?.zToMeters).toBeCloseTo(0.3048, 6);
  });

  it('normalizes brackets and keeps quoted text as written', () => {
    expect(normalizeWkt('proj (  "a (b)" , up east )')).toBe('PROJ["a (b)",up east]');
    expect(normalizeWkt('PROJ["unterminated')).toBeNull();
  });

  it('ignores node keywords and brackets inside quoted names', () => {
    const named = UTM2.replace('"WGS 84 / UTM zone 10N"', '"see PROJCRS[ and ] in remarks"');
    const compound = `COMPOUNDCRS["has PROJCRS[ and VERTCRS[ text",${named},VERTCRS["h",VDATUM["d"],CS[vertical,1],AXIS["H",up,LENGTHUNIT["foot",0.3048]]]]`;
    const crs = parseCopcCrs(compound);
    expect(crs?.horizontalWkt).toBe(named);
    expect(crs?.zToMeters).toBeCloseTo(0.3048, 6);
  });

  it('reads a plain WKT2 projected CRS', () => {
    expect(parseCopcCrs(UTM2)).toEqual({ horizontalWkt: UTM2, zToMeters: 1 });
  });

  it.each([
    ['nothing', undefined],
    ['an empty string', ''],
    ['a geocentric CRS', 'GEOCCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["metre",1],AXIS["Geocentric X",OTHER],AXIS["Geocentric Y",OTHER],AXIS["Geocentric Z",NORTH]]'],
    ['text proj4 cannot read', 'not a CRS'],
    ['a compound CRS without a horizontal part', 'COMPD_CS["x",VERT_CS["h",UNIT["metre",1]]]'],
  ])('refuses %s', (_label, wkt) => {
    expect(parseCopcCrs(wkt)).toBeNull();
  });

  it('refuses a valid WKT padded past the size cap', () => {
    const padded = UTM.replace('"WGS 84 / UTM zone 10N"', `"${'x'.repeat(MAX_WKT_LENGTH)}"`);
    expect(parseCopcCrs(UTM)).not.toBeNull();
    expect(parseCopcCrs(padded)).toBeNull();
  });

  it('ignores an absurd vertical unit factor', () => {
    const compound = `COMPD_CS["x",${UTM},VERT_CS["h",VERT_DATUM["d",2005],UNIT["huge",1e30]]]`;
    expect(parseCopcCrs(compound)?.zToMeters).toBe(1);
  });
});
