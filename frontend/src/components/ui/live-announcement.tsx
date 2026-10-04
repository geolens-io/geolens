import { useEffect, useState } from 'react';

interface LiveAnnouncementProps {
  text: string;
  /** Delay before `text` is written; later changes restart it, which debounces. */
  delayMs?: number;
}

/**
 * Screen-reader-only polite status. It mounts empty and writes `text` after
 * mount, because a live region inserted already populated is often not
 * announced.
 */
export function LiveAnnouncement({ text, delayMs = 0 }: LiveAnnouncementProps) {
  const [announced, setAnnounced] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setAnnounced(text), delayMs);
    return () => clearTimeout(timer);
  }, [text, delayMs]);
  return (
    <p role="status" aria-live="polite" className="sr-only">
      {announced}
    </p>
  );
}
