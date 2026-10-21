import proj4 from 'proj4';
import { MAX_WKT_LENGTH } from './copc-limits';

/** The WKT node starting with `keyword[`, brackets balanced; null if absent. Quoted text is skipped. */
function wktNode(wkt: string, keyword: string): string | null {
  let quoted = false;
  let start = -1;
  let depth = 0;
  for (let i = 0; i < wkt.length; i++) {
    const ch = wkt[i];
    if (ch === '"') {
      // A doubled quote inside a string toggles twice and nets out.
      quoted = !quoted;
    } else if (quoted) {
      continue;
    } else if (start < 0) {
      if (ch === '[' && wkt.startsWith(keyword, i - keyword.length) && !/[A-Za-z_]/.test(wkt[i - keyword.length - 1] ?? '')) {
        start = i - keyword.length;
        depth = 1;
      }
    } else if (ch === '[') {
      depth++;
    } else if (ch === ']' && --depth === 0) {
      return wkt.slice(start, i + 1);
    }
  }
  return null;
}

// WKT1 spells the unit UNIT[...]; WKT2 LENGTHUNIT[...] (or UNIT[...]).
// ANGLEUNIT and SCALEUNIT are not lengths.
const UNIT = /(?<![A-Za-z])(?:LENGTH)?UNIT\["[^"]*",\s*([0-9.eE+-]+)/g;

// The keywords the catalog's ingestion reads (backend/app/processing/ingest/pointcloud.py).
const COMPOUND = ['COMPD_CS', 'COMPOUNDCRS'];
const PROJECTED = ['PROJCS', 'PROJCRS', 'PROJECTEDCRS'];
const GEOGRAPHIC = ['GEOGCS', 'GEODCRS', 'GEODETICCRS', 'GEOGCRS', 'GEOGRAPHICCRS'];
const VERTICAL = ['VERT_CS', 'VERTCRS', 'VERTICALCRS'];

function firstNode(wkt: string, keywords: string[]): string | null {
  for (const keyword of keywords) {
    const node = wktNode(wkt, keyword);
    if (node) return node;
  }
  return null;
}

function unitFactor(node: string): number {
  const factor = Number([...node.matchAll(UNIT)].at(-1)?.[1]);
  return Number.isFinite(factor) && factor > 0 && factor < 1e4 ? factor : 1;
}

// proj4's parser knows the short WKT2 spellings only.
const SHORT_KEYWORDS: [string, string][] = [
  ['PROJECTEDCRS[', 'PROJCRS['],
  ['GEODETICCRS[', 'GEODCRS['],
  ['GEOGRAPHICCRS[', 'GEOGCRS['],
];

function shortKeyword(wkt: string): string {
  const match = SHORT_KEYWORDS.find(([long]) => wkt.startsWith(long));
  return match ? match[1] + wkt.slice(match[0].length) : wkt;
}

// The tokens the catalog's ingestion reads: quoted strings, either bracket
// form, commas and bare words, with optional whitespace between them.
const WKT_TOKEN = /\s*(?:("(?:[^"]|"")*")|([[(])|([\])])|(,)|([^\s[\](),"]+))/y;

/** The WKT with square brackets, no padding, and uppercase node keywords, so the rest of the parser sees one form. */
export function normalizeWkt(wkt: string): string | null {
  const text = wkt.trim();
  const tokens: { text: string; opens?: boolean; bare?: boolean }[] = [];
  WKT_TOKEN.lastIndex = 0;
  while (WKT_TOKEN.lastIndex < text.length) {
    const match = WKT_TOKEN.exec(text);
    if (!match) return null;
    const [, quoted, opening, closing, comma, bare] = match;
    if (quoted !== undefined) tokens.push({ text: quoted });
    else if (opening !== undefined) tokens.push({ text: '[', opens: true });
    else if (closing !== undefined) tokens.push({ text: ']' });
    else if (comma !== undefined) tokens.push({ text: ',' });
    else tokens.push({ text: bare, bare: true });
  }
  return tokens
    .map((token, i) => {
      const keyword = token.bare && tokens[i + 1]?.opens;
      const pad = token.bare && tokens[i - 1]?.bare ? ' ' : '';
      return pad + (keyword ? token.text.toUpperCase() : token.text);
    })
    .join('');
}

// Geocentric (Earth-centred Cartesian) coordinates need a three-dimensional
// transform; the viewer reprojects X and Y only, so these keep the footprint.
const QUOTED = /"(?:[^"]|"")*"/g;
const GEOCENTRIC = /GEOCCS\[|geocentric|CS\[Cartesian,\s*3\]/i;

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
export function parseCopcCrs(rawWkt: string | undefined): CopcCrs | null {
  if (!rawWkt || rawWkt.length > MAX_WKT_LENGTH) return null;
  const wkt = normalizeWkt(rawWkt);
  if (!wkt || GEOCENTRIC.test(wkt.replace(QUOTED, '""'))) return null;
  const compound = COMPOUND.some((keyword) => wkt.startsWith(keyword));
  const projected = compound ? firstNode(wkt, PROJECTED) : null;
  const found = compound ? projected ?? firstNode(wkt, GEOGRAPHIC) : wkt;
  if (!found) return null;
  const horizontalWkt = shortKeyword(found);
  try {
    proj4(horizontalWkt, 'EPSG:4326').forward([0, 0]);
  } catch {
    return null;
  }
  const vertical = compound ? firstNode(wkt, VERTICAL) : null;
  // A geographic CRS carries an angular unit, which says nothing about Z.
  const horizontalIsProjected = compound ? projected !== null : PROJECTED.some((keyword) => wkt.startsWith(keyword));
  const unitSource = vertical ?? (horizontalIsProjected ? horizontalWkt : null);
  return { horizontalWkt, zToMeters: unitSource ? unitFactor(unitSource) : 1 };
}
