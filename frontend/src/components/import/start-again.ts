/** The server redacts credential query values to this marker. */
const REDACTED_QUERY_VALUE = '<redacted>';

import type { QueryClient } from '@tanstack/react-query';
import { clearServiceImport, peekServiceImport } from '@/api/service-url-session';
import { clearUrlImport, peekUrlImport } from '@/api/url-import-session';
import { queryKeys } from '@/lib/query-keys';

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
 * Releases a retained import session that already ended, so the prefilled form
 * is not replaced by it. Returns false when a session is still active (or its
 * job status is unknown) and must keep the form.
 */
export function releaseTerminalImportSession(
  source: StartAgainSource,
  queryClient: QueryClient,
): boolean {
  const session = source === 'url' ? peekUrlImport() : peekServiceImport();
  if (!session) return true;
  const jobStatus = session.jobId
    ? queryClient.getQueryData<{ status: string }>(queryKeys.ingest.jobStatus(session.jobId))
        ?.status
    : undefined;
  const ended =
    session.status === 'rejected' || (jobStatus !== undefined && !IN_FLIGHT_STATUSES.has(jobStatus));
  if (!ended) return false;
  if (source === 'url') clearUrlImport();
  else clearServiceImport();
  return true;
}
