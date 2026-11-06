import { useMemo } from 'react';
import { ApiError } from '@/api/client';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';

type FeatureRowState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'missing' }
  | { status: 'refused' }
  | { status: 'error' }
  | { status: 'ready'; row: Record<string, unknown> };

/**
 * The feature's full row, read from the rows endpoint by gid. A lean tile
 * carries only the columns the map draws with, so a popup or list item fetches
 * the rest. `gid` is dropped: the tile never carried it as a property.
 */
export function useFeatureRow(
  datasetId: string | undefined,
  gid: number | undefined,
  enabled: boolean,
  embedToken?: string,
): FeatureRowState {
  const active = enabled && !!datasetId && gid !== undefined;
  const { data, error, isError, isPlaceholderData } = useDatasetRows(
    active ? datasetId : '',
    1,
    0,
    undefined,
    undefined,
    undefined,
    gid,
    { embedToken },
  );
  const result = useMemo((): FeatureRowState => {
    if (!active) return { status: 'idle' };
    // A refusal means the reader may see nothing beyond the tile, which is not a fault.
    if (isError) {
      return error instanceof ApiError && [401, 403, 404].includes(error.status)
        ? { status: 'refused' }
        : { status: 'error' };
    }
    // The previous feature's row stays as placeholder data while the next loads.
    if (!data || isPlaceholderData) return { status: 'loading' };
    // The feature was removed after the tile loaded.
    if (data.rows.length === 0) return { status: 'missing' };
    const { gid: _gid, ...row } = data.rows[0];
    return { status: 'ready', row };
  }, [active, data, error, isError, isPlaceholderData]);
  return result;
}
