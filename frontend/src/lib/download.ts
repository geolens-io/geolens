/**
 * Browser blob download.
 *
 * One helper for the anchor dance, so the authenticated-blob path is the
 * obvious one: `window.open()` sends no Authorization header and would 401
 * against the Bearer-JWT API.
 */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** `prefix-2026-07-09.csv` — the date stamp every export in the app already used. */
export function datedFilename(prefix: string, extension: string): string {
  const date = new Date().toISOString().slice(0, 10);
  return `${prefix}-${date}.${extension}`;
}
