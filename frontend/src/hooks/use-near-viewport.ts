import { useEffect, useState, type RefObject } from 'react';

/**
 * Whether `ref`'s element has come within `rootMargin` of the viewport. Turns
 * true on the first intersection and stays true. Without IntersectionObserver
 * it's true from the start.
 */
export function useNearViewport(ref: RefObject<Element | null>, rootMargin = '400px'): boolean {
  const [near, setNear] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const element = ref.current;
    if (near || !element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      { rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near, ref, rootMargin]);
  return near;
}
