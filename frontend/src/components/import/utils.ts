import type { FileEntry, FilePreviewResponse } from '@/types/api';
import { isRasterPreview, isTilesetPreview, isPointCloudPreview } from '@/lib/import-preview';
import type { DataKind } from './TypeTag';
import { kindFromExtension } from './TypeTag';

export {
  isRasterPreview,
  isFilePreview,
  isTilesetPreview,
  isPointCloudPreview,
  stripExtension,
  inferImportedKind,
} from '@/lib/import-preview';

// Every upload door checks the deployment's extension list before it requires a tileset archive.
const TILESET_EXTENSIONS = ['.zip', '.3tz'];

/** The tileset archive extensions the deployment's list allows; all of them while the list is unknown. */
export function allowedTilesetExtensions(configExtensions: string[] | undefined): string[] {
  return TILESET_EXTENSIONS.filter((ext) => configExtensions?.includes(ext) ?? true);
}

/** Extract file extension (e.g. ".gpkg") or empty string if none */
export function fileExt(fileName: string): string {
  const dotIdx = fileName.lastIndexOf('.');
  return dotIdx >= 0 ? fileName.slice(dotIdx).toLowerCase() : '';
}

/**
 * The layer name to show for an upload. A single-layer file is named after its
 * staged copy, `{jobId}_{stem}` (with a random segment for presigned uploads),
 * so the job id prefix is dropped in favour of the uploaded file's own name.
 * A name without that verified prefix is a real layer name and is kept. The
 * value sent back at commit stays the source layer name.
 */
export function displayLayerName(
  layerName: string,
  jobId: string,
  sourceFilename: string | null,
): string {
  if (!sourceFilename || !layerName.startsWith(`${jobId}_`)) return layerName;
  const dot = sourceFilename.lastIndexOf('.');
  const stem = dot > 0 ? sourceFilename.slice(0, dot) : sourceFilename;
  return layerName.endsWith(`_${stem}`) ? stem : layerName;
}

/**
 * True for spreadsheet sources (multi-sheet workbooks). The multi-layer picker
 * calls the item a "Sheet" only for these; every other multi-layer container
 * (GeoPackage, zipped File Geodatabase, etc.) uses "Layer" vocabulary instead —
 * an ArcGIS user importing a .gdb does not expect spreadsheet terms.
 */
export function isSpreadsheetExt(ext: string): boolean {
  return ext === '.xlsx' || ext === '.xls';
}

/** Derive display kind from a FileEntry (preview-aware, then the upload kind, then the extension) */
export function kindFromEntry(entry: Pick<FileEntry, 'previewData' | 'fileName' | 'uploadKind'>): DataKind {
  if (entry.previewData) {
    if (isTilesetPreview(entry.previewData)) return 'tiles3d';
    if (isPointCloudPreview(entry.previewData)) return 'pointcloud';
    if (isRasterPreview(entry.previewData)) return 'raster';
    if ((entry.previewData as FilePreviewResponse).geometry_type) return 'vector';
    return 'table';
  }
  return entry.uploadKind ?? kindFromExtension(fileExt(entry.fileName));
}

/**
 * Client-side heuristic mirroring the backend ArcGIS adapter's own layer-URL
 * detection (`adapters/arcgis.py`, matching `/(FeatureServer|MapServer)/`).
 * The import wizard needs to know whether to show the ArcGIS auth method
 * select before the URL is ever probed, since sign-in has to happen before
 * the probe call itself, so there is no server round-trip yet to ask what
 * type of service this is.
 */
export function looksLikeArcGisServiceUrl(url: string): boolean {
  return /\/(FeatureServer|MapServer)\b/i.test(url);
}

const PORTAL_PATH =
  /\/(?:(?:portal\w*|arcgis)\/(?:home|apps)(?:\/|$)|home\/(?:(?:index|item|signin|organization|user|group|gallery|content)|webmap\/viewer)\.html$)/i;

/**
 * An ArcGIS organization or portal homepage (the arcgis.com org site or an
 * Enterprise `/portal/home` or `/portal/apps` page) rather than a layer endpoint.
 * The importer needs a FeatureServer/MapServer layer REST URL, which these
 * pages are not.
 */
export function looksLikeArcGisPortalUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return false;
  }
  // A viewer link can carry a service URL in its query string; only the path says what this page is.
  if (/\/(FeatureServer|MapServer)\b/i.test(parsed.pathname)) return false;
  const host = parsed.hostname.toLowerCase();
  if (
    host === 'arcgis.com' ||
    host === 'www.arcgis.com' ||
    host.endsWith('.maps.arcgis.com')
  ) {
    return true;
  }
  // Enterprise web adaptors can have any name, so the portal's own page names stand in for it.
  return PORTAL_PATH.test(parsed.pathname);
}

/** Origin of a service URL. */
export function originOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return '';
  }
}

// codex review #1757: the backend treats the sign-in portal field as a
// portal ROOT and derives /sharing/rest/info and /sharing/rest/generateToken
// from it (D8's own referer default below matches). The service URL's
// origin is not that for ArcGIS Online: services6.arcgis.com etc. are
// feature-service hosts, not portals, so prefilling the service origin
// presented a host that fails sign-in as though it were a valid default.
const ARCGIS_ONLINE_PORTAL = 'https://www.arcgis.com';

/**
 * The best guess at a sign-in portal for a service URL, in three cases:
 *
 * - A host under arcgis.com that is not *.maps.arcgis.com (services6.
 *   arcgis.com, tiles.arcgis.com, and the other ArcGIS Online tile/feature
 *   hosts) is ArcGIS Online itself, whose portal is www.arcgis.com, not the
 *   service host. This is also the backend's own D8 referer default
 *   (arcgis_signin.py, DEFAULT_SIGNIN_REFERER), so it doubles as the value
 *   generateToken already expects when nothing more specific is known.
 * - A host already shaped like an org's own portal (*.maps.arcgis.com)
 *   prefills its own origin; that IS the portal.
 * - Anything else (an Enterprise deployment's arbitrary hostname) has no
 *   derivable portal from a /server/rest/services URL. Leaving the field
 *   empty, with its placeholder, is the honest default: presenting a wrong
 *   guess as a valid one is worse than presenting none.
 *
 * The field stays editable in every case.
 */
export function defaultPortalFor(serviceUrl: string): string {
  let parsed: URL;
  try {
    parsed = new URL(serviceUrl);
  } catch {
    return '';
  }
  const host = parsed.hostname.toLowerCase();
  if (host.endsWith('.maps.arcgis.com')) {
    return parsed.origin;
  }
  if (host === 'arcgis.com' || host.endsWith('.arcgis.com')) {
    return ARCGIS_ONLINE_PORTAL;
  }
  return '';
}
