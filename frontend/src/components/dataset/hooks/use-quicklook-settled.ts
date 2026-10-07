import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getJobStatus } from '@/api/ingest';
import { queryKeys } from '@/lib/query-keys';

const POLL_INTERVAL_MS = 2000;
// A redraw that has not landed after this long keeps retrying on the server;
// the page stops watching it.
const MAX_POLLS = 30;

/**
 * Refreshes cached search results once a replacement's new quicklook is in
 * place. The job reports complete before the thumbnail's pointer moves, so a
 * search refetched on completion can still return the old image.
 */
export function useRefreshSearchWhenQuicklookLands(jobId: string | null) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async (attempt: number) => {
      try {
        const job = await getJobStatus(jobId);
        if (cancelled) return;
        if (!job.quicklook_pending) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.search.all });
          return;
        }
      } catch {
        // A failed read ends the watch; the thumbnail then refreshes on remount.
        return;
      }
      if (attempt + 1 < MAX_POLLS) {
        timer = setTimeout(() => void poll(attempt + 1), POLL_INTERVAL_MS);
      }
    };

    timer = setTimeout(() => void poll(0), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, queryClient]);
}
