import { useState, useEffect } from 'react';
import { useDrawingStore } from '@/stores/drawing-store';

/**
 * Manages the effective feature GID for the dataset page.
 *
 * Combines the drawing store's selected feature (from editing) with a
 * read-only selection state (from map clicks outside edit mode). The
 * editing selection always takes precedence; when it activates, the
 * read-only selection is cleared automatically.
 *
 * @returns `{ effectiveGid, setReadOnlyFeatureGid }` where `effectiveGid`
 * is the GID to display in the related-records panel, and
 * `setReadOnlyFeatureGid` is the callback to pass to `DatasetMap.onFeatureClick`.
 */
export function useFeatureGid() {
  const selectedFeatureGid = useDrawingStore((s) => s.selectedFeature?.gid ?? null);
  const [readOnlyFeatureGid, setReadOnlyFeatureGid] = useState<number | null>(null);

  // Clear read-only selection when editing mode activates
  useEffect(() => {
    if (selectedFeatureGid != null) {
      setReadOnlyFeatureGid(null);
    }
  }, [selectedFeatureGid]);

  const effectiveGid = selectedFeatureGid ?? readOnlyFeatureGid;

  return { effectiveGid, setReadOnlyFeatureGid };
}
