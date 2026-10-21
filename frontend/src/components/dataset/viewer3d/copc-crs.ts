import proj4 from 'proj4';
import { MAX_WKT_LENGTH } from './copc-limits';

/** The WKT node starting with `keyword[`, brackets balanced; null if absent. */
function wktNode(wkt: string, keyword: string): string | null {
  const start = wkt.indexOf(`${keyword}[`);
  if (start < 0) return null;
  let depth = 0;
  for (let i = start + keyword.length; i < wkt.length; i++) {
    if (wkt[i] === '[') depth++;
    else if (wkt[i] === ']' && --depth === 0) return wkt.slice(start, i + 1);
  }
  return null;
}

function unitFactor(node: string): number {
  const factor = Number(/UNIT\["[^"]*",\s*([0-9.eE+-]+)/.exec(node.slice(node.lastIndexOf('UNIT[')))?.[1]);
  return Number.isFinite(factor) && factor > 0 && factor < 1e4 ? factor : 1;
}

export interface CopcCrs {
  /** WKT of the horizontal CRS; proj4 refuses a compound CRS as a whole. */
  horizontalWkt: string;
  /** Multiplier taking the file's vertical units to metres. */
  zToMeters: number;
}

/**
 * The CRS parts the viewer needs from the file's WKT, or null when proj4
 * cannot use it (the dataset page then keeps its footprint view).
 */
export function parseCopcCrs(wkt: string | undefined): CopcCrs | null {
  if (!wkt || wkt.length > MAX_WKT_LENGTH) return null;
  const compound = wkt.startsWith('COMPD_CS');
  const horizontalWkt = compound ? wktNode(wkt, 'PROJCS') ?? wktNode(wkt, 'GEOGCS') : wkt;
  if (!horizontalWkt) return null;
  try {
    proj4(horizontalWkt, 'EPSG:4326').forward([0, 0]);
  } catch {
    return null;
  }
  const vertical = compound ? wktNode(wkt, 'VERT_CS') : null;
  return { horizontalWkt, zToMeters: unitFactor(vertical ?? horizontalWkt) };
}
