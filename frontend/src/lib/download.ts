/**
 * Browser blob download.
 *
 * fix(#435): extracted during UX-01. Four call sites had hand-rolled copies of
 * this same anchor dance, and a fifth (admin CSV export) skipped it entirely in
 * favor of `window.open()` — which sends no Authorization header, so the export
 * came back 401 against our Bearer-JWT API. Having one helper makes the
 * authenticated-blob path the obvious one to reach for.
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
