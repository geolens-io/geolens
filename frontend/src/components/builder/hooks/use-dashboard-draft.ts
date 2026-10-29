import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DashboardConfig, MapLayerResponse } from '@/types/api';
import { dashboardChanged, toDashboardDraft, widgetLayerGone, type DashboardDraft } from '../dashboard-draft';

// How many sent drafts are remembered; a few saves in quick succession are the most in flight at once.
const SENT_DRAFTS_KEPT = 5;

/**
 * The Builder's working copy of the map's dashboard: unsaved edits over the
 * saved dashboard.
 *
 * When the saved dashboard changes, an edit it already contains is done and
 * clears; any other edit stays and is now measured against the new saved
 * dashboard. That keeps an edit made while a save was in flight, and the
 * whole edit when a save stores only the layers. A change that came from
 * neither this session's saves nor its layer edits calls `onConflict`.
 */
export function useDashboardDraft(
  saved: DashboardConfig | null | undefined,
  mapId: string | undefined,
  layers: readonly MapLayerResponse[] | undefined,
  onConflict: () => void,
) {
  const savedDraft = useMemo(() => toDashboardDraft(saved), [saved]);
  const [edit, setEdit] = useState<{ mapId?: string; draft: DashboardDraft } | null>(null);
  const edited = edit && edit.mapId === mapId ? edit.draft : null;

  // What this session sent, so the save coming back isn't taken for someone
  // else's change, even when another session's write lands during our save.
  const sentRef = useRef<DashboardDraft[]>([]);
  const markSent = useCallback((draft: DashboardDraft) => {
    sentRef.current = [...sentRef.current.slice(1 - SENT_DRAFTS_KEPT), draft];
  }, []);

  const previous = useRef({ mapId, savedDraft });
  const latestEdited = useRef(edited);
  latestEdited.current = edited;
  const onConflictRef = useRef(onConflict);
  onConflictRef.current = onConflict;
  useEffect(() => {
    const before = previous.current;
    previous.current = { mapId, savedDraft };
    if (before.mapId !== mapId) {
      sentRef.current = [];
      setEdit(null);
      return;
    }
    if (!dashboardChanged(before.savedDraft, savedDraft)) return;
    const draft = latestEdited.current;
    if (!draft) return;
    if (!dashboardChanged(draft, savedDraft)) {
      setEdit(null);
      return;
    }
    // As the server shows it: without the widgets on layers the map no longer has.
    const onLayers = (known: DashboardDraft): DashboardDraft => ({
      ...known,
      widgets: known.widgets.filter((widget) => !widgetLayerGone(widget, layers ?? [])),
    });
    const expected = [before.savedDraft, ...sentRef.current].some(
      (known) => !dashboardChanged(onLayers(known), savedDraft),
    );
    if (!expected) onConflictRef.current();
  }, [mapId, savedDraft, layers]);

  const setDashboard = useCallback(
    (draft: DashboardDraft) => setEdit({ mapId, draft }),
    [mapId],
  );
  const dashboardEdited = useMemo(
    () => edited !== null && dashboardChanged(edited, savedDraft),
    [edited, savedDraft],
  );

  return {
    dashboard: edited ?? savedDraft,
    savedDashboard: savedDraft,
    setDashboard,
    markSent,
    dashboardEdited,
  };
}
