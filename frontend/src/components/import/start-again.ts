/** The server redacts credential query values to this marker. */
const REDACTED_QUERY_VALUE = '<redacted>';

import { getJobStatus } from '@/api/ingest';
import { clearServiceImport, peekServiceImport } from '@/api/service-url-session';
import { clearUrlImport, peekUrlImport } from '@/api/url-import-session';

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

const IN_FLIGHT_STATUSES = new Set(['pending', 'running']);

/**
 * Releases a retained import session whose job has ended, so the prefilled form
 * is not replaced by it. The job's status is read fresh: the cache may still
 * say "running" for a job that failed while the user was elsewhere. Returns
 * false when the session is active or the lookup fails, and must keep the form.
 */
export async function releaseTerminalImportSession(source: StartAgainSource): Promise<boolean> {
  const peek = source === 'url' ? peekUrlImport : peekServiceImport;
  const session = peek();
  if (!session) return true;
  let ended = session.status === 'rejected';
  if (!ended && session.jobId) {
    try {
      const { status } = await getJobStatus(session.jobId);
      ended = !IN_FLIGHT_STATUSES.has(status);
    } catch {
      return false;
    }
  }
  if (!ended) return false;
  // Already released (a concurrent lookup, as under StrictMode) counts as
  // released; a different session means another import started mid-lookup.
  const current = peek();
  if (current === null) return true;
  if (current !== session) return false;
  if (source === 'url') clearUrlImport();
  else clearServiceImport();
  return true;
}
