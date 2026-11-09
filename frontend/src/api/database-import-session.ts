import { startDatabaseImport } from './ingest';
import { useAuthStore } from '@/stores/auth-store';
import type { DatabaseImportRequest, DatabaseImportResponse, DatabaseTable } from '@/types/api';

/**
 * The in-flight Database-tab import, owned outside React.
 *
 * The Import page mounts one source at a time, so leaving the tab mid-request
 * would unmount the form and drop the job id the server returns. The settlement
 * handler lives here, and a form mounted later adopts the session. Not
 * persisted: it covers a tab switch within one page load.
 */
export interface DatabaseImportSession {
  connection: string;
  table: DatabaseTable;
  status: 'pending' | 'fulfilled' | 'rejected';
  jobId: string | null;
  error: unknown;
  promise: Promise<DatabaseImportResponse>;
  ownerId: string | null;
}

let current: DatabaseImportSession | null = null;

/** Starts the import, or returns the one already in flight. */
export function beginDatabaseImport(
  connection: string,
  table: DatabaseTable,
  request: DatabaseImportRequest,
): DatabaseImportSession {
  if (current && current.status === 'pending') return current;
  const promise = startDatabaseImport(connection, request);
  const session: DatabaseImportSession = {
    connection,
    table,
    status: 'pending',
    jobId: null,
    error: null,
    promise,
    ownerId: useAuthStore.getState().user?.id ?? null,
  };
  current = session;
  promise.then(
    (res) => {
      session.status = 'fulfilled';
      session.jobId = res.job_id;
    },
    (err) => {
      session.status = 'rejected';
      session.error = err;
    },
  );
  return session;
}

/** The session, unless it belongs to another user. */
export function peekDatabaseImport(): DatabaseImportSession | null {
  if (!current) return null;
  if (current.ownerId !== (useAuthStore.getState().user?.id ?? null)) {
    clearDatabaseImport();
    return null;
  }
  return current;
}

export function clearDatabaseImport(): void {
  current = null;
}

useAuthStore.subscribe((s, prev) => {
  if (s.user?.id !== prev.user?.id) clearDatabaseImport();
});
