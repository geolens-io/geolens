import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DashboardConfig, MapLayerResponse } from '@/types/api';
import { dashboardChanged, toDashboardDraft, widgetLayerGone, type DashboardDraft } from '../dashboard-draft';

/**
 * The Builder's working copy of the map's dashboard: unsaved edits over the
 * saved dashboard.
 *
 * When the saved dashboard changes, an edit it already contains is done and
 * clears; any other edit stays and is now measured against the new saved
 * dashboard. That keeps an edit made while a save was in flight, and the
 * whole edit when a save stores only the layers. An edit that had been put
 * back to the old saved dashboard gives way to the new one. A change that
 * came from neither this session's saves nor its layer edits, under a real
 * edit, calls `onConflict`.
 */
export function useDashboardDraft(
  saved: DashboardConfig | null | undefined,
  mapId: string | undefined,
  /** The layers the saved map has, which the saved dashboard was shown against. */
  savedLayers: readonly MapLayerResponse[] | undefined,
  /** The Builder's layers, which a save of the draft is stored against. */
  editorLayers: readonly MapLayerResponse[],
  onConflict: () => void,
) {
  const savedDraft = useMemo(() => toDashboardDraft(saved), [saved]);
  const [edit, setEdit] = useState<{ mapId?: string; draft: DashboardDraft } | null>(null);
  const edited = edit && edit.mapId === mapId ? edit.draft : null;

  // This session's saves still in flight, and the last one that landed and
  // whose refetch hasn't come back yet: only those can explain a change to
  // the saved dashboard as our own. An older draft can't, since another
  // editor could have put its values back.
  const inFlightRef = useRef<DashboardDraft[]>([]);
  const landedRef = useRef<DashboardDraft | null>(null);
  /**
   * Records a save of `draft`, in the canonical form it was sent in; call the
   * result with whether the server stored it.
   */
  const beginSave = useCallback((draft: DashboardDraft) => {
    inFlightRef.current = [...inFlightRef.current, draft];
    return (stored: boolean) => {
      inFlightRef.current = inFlightRef.current.filter((sent) => sent !== draft);
      if (stored) landedRef.current = draft;
    };
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
      inFlightRef.current = [];
      landedRef.current = null;
      setEdit(null);
      return;
    }
    // Both are server responses, so compared as they stand.
    if (!dashboardChanged(before.savedDraft, savedDraft)) return;
    const ours = landedRef.current ? [...inFlightRef.current, landedRef.current] : inFlightRef.current;
    landedRef.current = null;
    const draft = latestEdited.current;
    if (!draft) return;
    if (!dashboardChanged(draft, savedDraft, editorLayers)) {
      setEdit(null);
      return;
    }
    // The server shows a sent draft without the widgets on layers it no longer has.
    const ourSave = ours.some((sent) => !dashboardChanged(sent, savedDraft, savedLayers ?? []));
    // An edit put back to the old saved dashboard is no edit: take the new
    // one, unless it is our own save and the edit was put back after sending.
    if (!ourSave && !dashboardChanged(draft, before.savedDraft, editorLayers)) {
      setEdit(null);
      return;
    }
    if (!ourSave && dashboardChanged(before.savedDraft, savedDraft, savedLayers ?? [])) {
      onConflictRef.current();
    }
    // The edit stays, without the widgets a save drops, so none is shown stale.
    const kept = draft.widgets.filter((widget) => !widgetLayerGone(widget, editorLayers));
    if (kept.length < draft.widgets.length) setEdit({ mapId, draft: { ...draft, widgets: kept } });
  }, [mapId, savedDraft, savedLayers, editorLayers]);

  const setDashboard = useCallback(
    (draft: DashboardDraft) => setEdit({ mapId, draft }),
    [mapId],
  );
  const dashboardEdited = useMemo(
    () => edited !== null && dashboardChanged(edited, savedDraft, editorLayers),
    [edited, savedDraft, editorLayers],
  );

  return {
    dashboard: edited ?? savedDraft,
    savedDashboard: savedDraft,
    setDashboard,
    beginSave,
    dashboardEdited,
  };
}
