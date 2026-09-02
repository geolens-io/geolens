import type { CommitImportRequest, FileEntry, FilePreviewResponse, RasterPreviewResponse } from '@/types/api';
import type { DataKind } from './TypeTag';
import { kindFromExtension } from './TypeTag';

export function isRasterPreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is RasterPreviewResponse {
  return 'band_count' in data;
}

export function isFilePreview(
  data: FilePreviewResponse | RasterPreviewResponse,
): data is FilePreviewResponse {
  return 'layers' in data || 'layer_name' in data;
}

export function stripExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? filename.slice(0, dot) : filename;
}

export function inferImportedKind(
  entry: Pick<FileEntry, 'previewData'>,
  request?: Pick<CommitImportRequest, 'x_column' | 'y_column' | 'geom_column'>,
): NonNullable<FileEntry['submittedKind']> {
  if (!entry.previewData) return 'table';
  if (isRasterPreview(entry.previewData)) return 'raster';

  if (request?.x_column || request?.y_column || request?.geom_column) {
    return 'vector';
  }

  if (entry.previewData.geometry_type || entry.previewData.detected_geometry_columns) {
    return 'vector';
  }

  return 'table';
}

/** Extract file extension (e.g. ".gpkg") or empty string if none */
export function fileExt(fileName: string): string {
  const dotIdx = fileName.lastIndexOf('.');
  return dotIdx >= 0 ? fileName.slice(dotIdx).toLowerCase() : '';
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

/** Derive display kind from a FileEntry (preview-aware, falls back to extension) */
export function kindFromEntry(entry: Pick<FileEntry, 'previewData' | 'fileName'>): DataKind {
  if (entry.previewData) {
    if (isRasterPreview(entry.previewData)) return 'raster';
    if ((entry.previewData as FilePreviewResponse).geometry_type) return 'vector';
    return 'table';
  }
  return kindFromExtension(fileExt(entry.fileName));
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
