import { useEffect, useState } from 'react';
import { apiFetchBlob } from '@/api/client';

export function useMapThumbnail(thumbnailUrl: string | null | undefined): string | null {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!thumbnailUrl) {
      setSrc(null);
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;

    apiFetchBlob(thumbnailUrl)
      .then((blob) => {
        if (!cancelled) {
          objectUrl = URL.createObjectURL(blob);
          setSrc(objectUrl);
        } else {
          // Component unmounted before fetch resolved — revoke immediately
          const url = URL.createObjectURL(blob);
          URL.revokeObjectURL(url);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSrc(null);
        }
      });

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    };
  }, [thumbnailUrl]);

  return src;
}
