/** The server redacts credential query values to this marker. */
const REDACTED_QUERY_VALUE = '<redacted>';

export type StartAgainSource = 'url' | 'service';

/**
 * Import-page link that restarts a failed import. The prefilled URL never
 * carries userinfo or a redacted credential parameter; the user supplies
 * credentials again in the form.
 */
export function startAgainPath(source: StartAgainSource, sourceUrl?: string | null): string {
  const params = new URLSearchParams({ tab: source });
  const safeUrl = sourceUrl ? stripCredentials(sourceUrl) : null;
  if (safeUrl) params.set('url', safeUrl);
  return `/import?${params.toString()}`;
}

function stripCredentials(raw: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  parsed.username = '';
  parsed.password = '';
  for (const [name, value] of [...parsed.searchParams]) {
    if (value === REDACTED_QUERY_VALUE) parsed.searchParams.delete(name);
  }
  return parsed.toString();
}
