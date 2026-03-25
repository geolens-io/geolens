import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/auth-store';

interface UseQuicklookResult {
  src: string | null;
  isLoading: boolean;
  isError: boolean;
}

/**
 * Fetches a quicklook thumbnail for a dataset and manages blob URL lifecycle.
 * Returns null immediately for null datasetId (e.g., collections).
 */
export function useQuicklook(datasetId: string | null): UseQuicklookResult {
  const [src, setSrc] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isError, setIsError] = useState(false);
  const blobUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (!datasetId) {
      setSrc(null);
      setIsLoading(false);
      setIsError(false);
      return;
    }
    let revoked = false;
    const controller = new AbortController();
    setIsLoading(true);
    setIsError(false);
    setSrc(null);

    const token = useAuthStore.getState().token;
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    fetch(`/api/datasets/${datasetId}/quicklook?size=256`, { headers, signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.blob();
      })
      .then((blob) => {
        if (revoked) return;
        if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = URL.createObjectURL(blob);
        setSrc(blobUrlRef.current);
        setIsLoading(false);
      })
      .catch(() => {
        if (!revoked) {
          setIsError(true);
          setIsLoading(false);
        }
      });

    return () => {
      revoked = true;
      controller.abort();
      setIsLoading(false);
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [datasetId]);

  if (!datasetId) {
    return { src: null, isLoading: false, isError: false };
  }

  return { src, isLoading, isError };
}
