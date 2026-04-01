import i18n from '@/i18n/i18n';

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

export function formatNumber(n: number | null): string {
  if (n === null || n === undefined) return i18n.t('common:notAvailable');
  return n.toLocaleString(i18n.language);
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
  if (!dateString) return i18n.t('common:notAvailable');
  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return i18n.t('common:notAvailable');
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' });
    const seconds = Math.abs(diffMs) / 1000;
    const dir = diffMs >= 0 ? -1 : 1;
    if (seconds < 60) return rtf.format(0, 'second');
    if (seconds < 3600) return rtf.format(dir * Math.round(seconds / 60), 'minute');
    if (seconds < 86400) return rtf.format(dir * Math.round(seconds / 3600), 'hour');
    if (seconds < 2592000) return rtf.format(dir * Math.round(seconds / 86400), 'day');
    if (seconds < 31536000) return rtf.format(dir * Math.round(seconds / 2592000), 'month');
    return rtf.format(dir * Math.round(seconds / 31536000), 'year');
  } catch {
    return i18n.t('common:notAvailable');
  }
}
