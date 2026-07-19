import i18n from '@/i18n/i18n';
import { formatProvenanceTime } from '@/lib/provenance-attribution';

export function formatDate(dateString: string | null): string {
  if (!dateString) return i18n.t('common:notAvailable');
  try {
    return new Date(dateString).toLocaleDateString(i18n.language, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return i18n.t('common:notAvailable');
  }
}

export function formatDateTimeSmart(dateString: string | null): string {
  if (!dateString) return i18n.t('common:notAvailable');
  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return i18n.t('common:notAvailable');
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const isYesterday = date.toDateString() === yesterday.toDateString();
    const isSameYear = date.getFullYear() === now.getFullYear();

    const timeStr = date.toLocaleTimeString(i18n.language, {
      hour: 'numeric',
      minute: '2-digit',
    });

    if (isToday) return timeStr;
    if (isYesterday) return i18n.t('common:yesterday', { time: timeStr });
    if (isSameYear) {
      const dateStr = date.toLocaleDateString(i18n.language, {
        month: 'short',
        day: 'numeric',
      });
      return `${dateStr}, ${timeStr}`;
    }
    return formatDate(dateString);
  } catch {
    return i18n.t('common:notAvailable');
  }
}

export function formatNumber(n: number | null | undefined, options?: Intl.NumberFormatOptions): string {
  if (n === null || n === undefined) return i18n.t('common:notAvailable');
  return new Intl.NumberFormat(i18n.language, options).format(n);
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return i18n.t('common:notAvailable');
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const idx = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, idx);
  return `${value.toLocaleString(i18n.language, { maximumFractionDigits: idx === 0 ? 0 : 1 })} ${units[idx]}`;
}

export function formatRelativeDate(dateString: string | null): string {
  // i18next's ``.t()`` returns ``unknown`` under the new generic signature
  // (the default ``returnNull`` / ``returnEmptyString`` options can both
  // yield non-string results). Narrow to ``string`` at the boundary so
  // downstream callers receive the expected type.
  const fallback = i18n.t('common:notAvailable') as string;
  if (!dateString) return fallback;
  const result = formatProvenanceTime(dateString, {
    fallbackRelative: fallback,
    fallbackAbsolute: fallback,
    locale: i18n.language,
  });
  return result.relative;
}

/** Approx meters per degree of latitude (equatorial) — for the "≈" ground
 *  distance shown next to arc-unit resolutions. */
const METERS_PER_DEGREE = 111_320;

function formatMetersGsd(meters: number, locale: string): string {
  if (meters < 1) return `${(meters * 100).toLocaleString(locale, { maximumFractionDigits: 0 })} cm`;
  if (meters < 1000) return `${Math.round(meters).toLocaleString(locale)} m`;
  return `${(meters / 1000).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
}

/**
 * Format a raster ground-sample distance given in CRS units.
 *
 * fix(#569): geographic CRSs deliver `gsd` in DEGREES — formatting them as
 * meters showed "2 cm" for a 60-arc-second global DEM. When the payload says
 * the CRS is geographic (or, for older payloads without the flag, the CRS is
 * EPSG:4326), render arc units with an approximate equatorial ground
 * distance, e.g. `60″ (≈1.9 km)`.
 */
export function formatGsd(
  gsd: number,
  opts: { isGeographic?: boolean | null; crs?: string | null },
  locale: string,
): string {
  const geographic = opts.isGeographic ?? (opts.crs != null && /^EPSG:4326$/i.test(opts.crs));
  if (!geographic) return formatMetersGsd(gsd, locale);
  const arcSeconds = gsd * 3600;
  let arc: string;
  if (gsd >= 1) {
    arc = `${gsd.toLocaleString(locale, { maximumFractionDigits: 2 })}°`;
  } else if (arcSeconds >= 120) {
    // Arc-minutes only from 2′ up: global DEMs are conventionally named in
    // arc-seconds ("30 arc-second", "60 arc-second"), so 60″ stays 60″.
    arc = `${(arcSeconds / 60).toLocaleString(locale, { maximumFractionDigits: 1 })}′`;
  } else {
    arc = `${arcSeconds.toLocaleString(locale, { maximumFractionDigits: 1 })}″`;
  }
  return `${arc} (≈${formatMetersGsd(gsd * METERS_PER_DEGREE, locale)})`;
}

/** Format raster resolution: 2 decimals for values >= 0.01, otherwise 6. */
export function formatResolution(value: number | null | undefined): string {
  if (value == null) return '—';
  const abs = Math.abs(value);
  const digits = abs >= 0.01 ? 2 : 6;
  return value.toLocaleString(i18n.language, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Format nodata values: truncate long floats to exponential notation. */
export function formatNodata(value: number | string | null | undefined): string {
  if (value == null) return i18n.t('common:none');
  const str = String(value);
  if (str.length > 12) {
    const num = Number(value);
    if (!isNaN(num)) return num.toExponential(4);
  }
  return str;
}
