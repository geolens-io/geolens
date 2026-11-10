import { useEffect, useState } from 'react';

/**
 * Whether the element given to the returned callback ref has come within
 * `rootMargin` of the viewport. Turns true on the first intersection and stays
 * true. An element attached later, after a re-render, is observed then.
 * Without IntersectionObserver it's true from the start.
 */
export function useNearViewport(rootMargin = '400px'): [(element: Element | null) => void, boolean] {
  const [element, setElement] = useState<Element | null>(null);
  const [near, setNear] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    if (near || !element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      { rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near, element, rootMargin]);
  return [setElement, near];
}
