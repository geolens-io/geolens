import { useEffect, useRef, useState } from 'react';

interface LiveAnnouncementProps {
  text: string;
  /** Delay before `text` is written; later changes restart it, which debounces. */
  delayMs?: number;
  /** When this changes the region is cleared and refilled, so an unchanged
   *  `text` is announced again (for example, two searches with equal counts). */
  trigger?: string;
}

/**
 * Screen-reader-only polite status. It mounts empty and writes `text` after
 * mount, because a live region inserted already populated is often not
 * announced.
 */
export function LiveAnnouncement({ text, delayMs = 0, trigger }: LiveAnnouncementProps) {
  const [announced, setAnnounced] = useState('');
  const lastTrigger = useRef(trigger);
  useEffect(() => {
    if (lastTrigger.current !== trigger) {
      lastTrigger.current = trigger;
      setAnnounced('');
    }
    const timer = setTimeout(() => setAnnounced(text), delayMs);
    return () => clearTimeout(timer);
  }, [text, delayMs, trigger]);
  return (
    <p role="status" aria-live="polite" className="sr-only">
      {announced}
    </p>
  );
}
