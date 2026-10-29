import { useCallback, useMemo, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, History, Sparkles, ChevronRight, Loader2, BotOff, FlaskConical, LayoutDashboard } from 'lucide-react';
import { Link } from 'react-router';
import { LazyLoadErrorBoundary } from '@/components/error/LazyLoadErrorBoundary';
import { cn } from '@/lib/utils';
import { useAnalysisJobStore } from '@/stores/analysis-job-store';
import { Button } from '@/components/ui/button';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import type { LayerActions } from '@/components/builder/ChatPanel';
import type { EphemeralAnalysisHandoff } from '@/components/builder/hooks/use-ephemeral-layers';
import type { ViewportContext } from '@/components/builder/chat-suggestions';
import { HistoryPanel } from '@/components/builder/HistoryPanel';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useSettingsAdmin } from '@/hooks/use-settings-admin';
import { Textarea } from '@/components/ui/textarea';
import type { DashboardDraft } from '@/components/builder/dashboard-draft';

const ChatPanel = lazy(() => import('@/components/builder/ChatPanel').then(m => ({ default: m.ChatPanel })));
const AnalysisPanel = lazy(() => import('@/components/builder/AnalysisPanel').then(m => ({ default: m.AnalysisPanel })));
const DashboardEditorPanel = lazy(() =>
  import('@/components/builder/DashboardEditorPanel').then((m) => ({ default: m.DashboardEditorPanel })),
);

/**
 * Structured disabled-state for the AI rail panel: per-reason copy, plus a
 * Settings CTA for users the admin-settings route will admit.
 *
 * Reads useAIAvailability() internally; TanStack Query dedupes, so no extra
 * network call versus the parent's derivation.
 */
function AIDisabledState() {
  const { t } = useTranslation('builder');
  const { reason, isLoading } = useAIAvailability();
  // The CTA targets /admin/settings/ai; show it only to users the route admits.
  // The route gate is mode-aware (manage_tenants in multi-tenant), so gate
  // through useSettingsAdmin, not raw manage_settings.
  const canAdminSettings = useSettingsAdmin();

  // One persistent live region whose content toggles: two conditionally mounted
  // role="status" regions would mount pre-populated and never be announced.
  const loading = isLoading || reason === null;

  const titleKey = reason === 'env_disabled' ? ('rail.aiDisabledTitle' as const)
    : reason === 'no_key' ? ('rail.aiNoKeyTitle' as const)
    : ('rail.aiPermissionTitle' as const);
  const titleDefault = reason === 'env_disabled' ? 'AI is disabled'
    : reason === 'no_key' ? 'AI not configured'
    : 'AI unavailable';
  const bodyKey = reason === 'env_disabled' ? ('rail.aiDisabledBody' as const)
    : reason === 'no_key' ? ('rail.aiNoKeyBody' as const)
    : ('rail.aiPermissionBody' as const);
  const bodyDefault = reason === 'env_disabled'
    ? 'An administrator has disabled AI for this instance.'
    : reason === 'no_key'
    ? 'A provider API key is required before AI chat can be used.'
    : "You don't have permission to use AI chat.";
  const ctaKey = reason === 'env_disabled' ? ('rail.aiGoToSettings' as const)
    : reason === 'no_key' ? ('rail.aiConfigureSettings' as const)
    : null;
  const ctaDefault = reason === 'env_disabled' ? 'Go to Settings'
    : reason === 'no_key' ? 'Configure in Settings'
    : '';
  const showCTA = ctaKey !== null && canAdminSettings;

  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 p-6 text-sm"
      role="status"
      aria-live="polite"
      data-ai-reason={loading ? undefined : reason}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : (
        <>
          <BotOff className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium text-foreground">{t(titleKey, { defaultValue: titleDefault })}</p>
          <p className="text-sm text-muted-foreground text-center max-w-[18rem]">{t(bodyKey, { defaultValue: bodyDefault })}</p>
          {showCTA && (
            <Button variant="outline" size="sm" asChild>
              {/* The settings route is /admin/settings/:tab */}
              <Link to="/admin/settings/ai">{t(ctaKey!, { defaultValue: ctaDefault })}</Link>
            </Button>
          )}
        </>
      )}
    </div>
  );
}

export type RailPanel = 'notes' | 'dashboard' | 'history' | 'analysis' | 'ai' | null;

interface BuilderRailProps {
  activePanel: RailPanel;
  onPanelChange: (panel: RailPanel) => void;
  aiAvailable: boolean;
  showRail?: boolean;
  // Notes
  notes: string;
  onNotesChange: (value: string) => void;
  // Dashboard
  dashboard?: DashboardDraft;
  onDashboardChange?: (draft: DashboardDraft) => void;
  /** The Builder's map once loaded; the dashboard preview reads its view. */
  map?: MaplibreMap | null;
  // AI Chat
  mapId?: string;
  layers?: MapLayerResponse[];
  layerActions?: LayerActions;
  onQueryResult?: (
    geojson: GeoJSON.FeatureCollection,
    bbox: [number, number, number, number],
    meta?: {
      truncated?: boolean;
      totalCount?: number;
      source?: 'analysis-panel';
    },
  ) => void;
  // Analysis tools
  mapInstanceRef?: React.RefObject<MaplibreMap | null>;
  /** The layer selected in the builder's stack; the Analysis panel prefers it
   *  (when analysable) over the remembered form's layer and the first-eligible
   *  default. */
  selectedLayerId?: string | null;
  onClearPreview?: () => void;
  hasPreview?: boolean;
  /** Who drew the current ephemeral overlay; the panel's stale-restore cleanup
   *  clears only its own. */
  previewSource?: 'analysis-panel';
  /** Which map `layers` currently belongs to; the Analysis panel mounts only
   *  once this matches mapId. */
  layersMapId?: string | null;
  /** Chat-preview handoff: keys a remount of AnalysisPanel so the form
   *  initializes from it. The nonce distinguishes successive handoffs. */
  analysisPrefill?: (EphemeralAnalysisHandoff & { nonce: number }) | null;
  /** Page-level materialize-job tracking (toast survives panel close). */
  onAnalysisJobChange?: (jobId: string | null) => void;
  /** Optional viewport context passed through to ChatPanel for viewport-aware
   *  suggestion chips. */
  viewport?: ViewportContext;
  // Dirty tracking
  onMarkDirty?: () => void;
}

export function BuilderRail({
  activePanel,
  onPanelChange,
  aiAvailable,
  notes,
  onNotesChange,
  dashboard,
  onDashboardChange,
  map,
  mapId,
  layers,
  layerActions,
  onQueryResult,
  mapInstanceRef,
  selectedLayerId,
  onClearPreview,
  hasPreview,
  previewSource,
  layersMapId,
  analysisPrefill,
  onAnalysisJobChange,
  viewport,
  onMarkDirty,
  showRail = true,
}: BuilderRailProps) {
  const { t } = useTranslation('builder');
  // AnalysisJobWatcher clears the tracked job on any terminal status, so a
  // tracked job is still in flight.
  const analysisJobRunning = useAnalysisJobStore((s) => !!s.job);

  const togglePanel = useCallback((panel: RailPanel) => {
    const next = activePanel === panel ? null : panel;
    onPanelChange(next);
    // Opening counterpart to closePanel's focus restore: move keyboard focus
    // into the freshly mounted panel (rAF, since it doesn't exist yet this tick)
    // so rail-button activation doesn't strand focus on the rail.
    if (next) {
      requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('[data-rail-panel]')?.focus();
      });
    }
  }, [activePanel, onPanelChange]);

  // Closing the panel unmounts the aside containing the focused element,
  // dropping focus to <body>. Mirror handleCloseEditor (MapBuilderPage): return
  // focus to the rail button that opened the panel. In sheet mode
  // (showRail=false) there is no button and Radix's close-time focus restore
  // applies.
  const closePanel = useCallback(() => {
    const panel = activePanel;
    onPanelChange(null);
    if (panel) {
      requestAnimationFrame(() => {
        document
          .querySelector<HTMLElement>(`[data-rail-button="${panel}"]`)
          ?.focus();
      });
    }
  }, [activePanel, onPanelChange]);

  const railButtons = useMemo(() => [
    {
      id: 'notes' as const,
      icon: FileText,
      label: t('dock.notes', { defaultValue: 'Notes' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'dashboard' as const,
      icon: LayoutDashboard,
      label: t('dock.dashboard'),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'history' as const,
      icon: History,
      label: t('dock.history', { defaultValue: 'History' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'analysis' as const,
      icon: FlaskConical,
      label: t('analysisTools.title', { defaultValue: 'Analysis' }),
      disabled: false,
      unavailable: false,
    },
    {
      id: 'ai' as const,
      icon: Sparkles,
      label: aiAvailable
        ? t('dock.askAi', { defaultValue: 'Ask AI' })
        : t('rail.aiUnavailable', { defaultValue: 'AI unavailable' }),
      disabled: false,
      unavailable: !aiAvailable,
    },
  ], [aiAvailable, t]);

  return (
    <>
      {/* Icon rail */}
      {showRail && (
        // Named landmark, so rail and panel asides aren't both announced as bare
        // "complementary".
        <aside
          aria-label={t('rail.toolsLabel', { defaultValue: 'Builder tools' })}
          className="w-11 bg-background border-s flex flex-col items-center pt-2.5 gap-1 shrink-0"
        >
          {railButtons.map(btn => (
            <button
              key={btn.id}
              data-rail-button={btn.id}
              onClick={btn.disabled ? undefined : () => togglePanel(btn.id)}
              disabled={btn.disabled}
              data-unavailable={btn.unavailable || undefined}
              title={btn.label}
              // The notes-presence state lives in the button's accessible name:
              // aria-label replaces the subtree, so a label on the dot span would
              // never be exposed (and is invalid ARIA on a role-less span).
              aria-label={
                btn.id === 'notes' && notes.trim().length > 0
                  ? t('rail.notesButtonWithNotes', { defaultValue: 'Notes (map has notes)' })
                  : btn.label
              }
              aria-pressed={activePanel === btn.id}
              // The only ambient signal that a materialize job is still running
              // once the panel is closed; the completion toast fires at the end,
              // up to five minutes later.
              aria-busy={btn.id === 'analysis' && analysisJobRunning}
              className={cn(
                'relative flex items-center justify-center h-8 w-8 rounded-md transition-colors',
                btn.disabled
                  ? 'text-muted-foreground/40 cursor-not-allowed'
                  : activePanel === btn.id
                    ? 'cursor-pointer bg-accent text-primary'
                    : 'cursor-pointer text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              {btn.id === 'analysis' && analysisJobRunning ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <btn.icon className="h-4 w-4" />
              )}
              {/* Presence dot: non-whitespace notes render a 6px primary-color
                  dot at the button's top-right. Decorative and static; the state
                  is announced via the button's conditional aria-label above. */}
              {btn.id === 'notes' && notes.trim().length > 0 && (
                <span
                  aria-hidden="true"
                  className="absolute -top-0.5 -end-0.5 size-1.5 rounded-full bg-primary"
                />
              )}
            </button>
          ))}
        </aside>
      )}

      {/* Expanded panel */}
      {activePanel && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- container-level Escape shortcut for keystrokes bubbling from the panel's own interactive children; the aside itself stays non-interactive
        <aside
          // Named landmark: the panel takes its accessible name from its own
          // title, distinguishing it from the icon rail.
          aria-labelledby="builder-rail-panel-title"
          // togglePanel focuses the panel on open (see above).
          data-rail-panel=""
          tabIndex={-1}
          className={cn(
            'bg-background border-s flex h-full min-h-0 flex-col shrink-0 overflow-hidden focus:outline-none',
            showRail ? 'w-80' : 'w-full border-s-0',
          )}
          onKeyDown={(e) => {
            // Escape closes the expanded rail panel, in parity with the editor
            // flyout (non-modal; fires only when focus is inside the panel).
            if (e.key === 'Escape' && !e.defaultPrevented) {
              e.stopPropagation();
              closePanel();
            }
          }}
        >
          {/* Panel header */}
          <div className="flex items-center justify-between px-3.5 py-2.5 border-b shrink-0">
            <div className="flex items-center gap-2">
              <span id="builder-rail-panel-title" className="text-sm font-medium">
                {activePanel === 'notes' && t('dock.notes', { defaultValue: 'Notes' })}
                {activePanel === 'dashboard' && t('dock.dashboard')}
                {activePanel === 'history' && t('dock.history', { defaultValue: 'History' })}
                {activePanel === 'analysis' && t('analysisTools.title', { defaultValue: 'Analysis' })}
                {activePanel === 'ai' && (aiAvailable
                  ? t('dock.askAi', { defaultValue: 'Ask AI' })
                  : t('rail.aiUnavailable', { defaultValue: 'AI unavailable' }))}
              </span>
            </div>
            <button
              onClick={closePanel}
              title={t('rail.closePanel', { defaultValue: 'Close panel' })}
              aria-label={t('rail.closePanel', { defaultValue: 'Close panel' })}
              className="flex cursor-pointer items-center justify-center h-6 w-6 rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            >
              <ChevronRight className="h-3.5 w-3.5 rtl-mirror" />
            </button>
          </div>

          {/* Panel body */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {activePanel === 'notes' && (
              <div className="flex h-full min-h-0 p-3">
                <Textarea
                  className="min-h-[18rem] flex-1 resize-none p-3 placeholder:text-muted-foreground/50"
                  placeholder={t('dock.notesPlaceholder', { defaultValue: 'Add notes about this map\u2026' })}
                  value={notes}
                  onChange={(e) => {
                    onNotesChange(e.target.value);
                    onMarkDirty?.();
                  }}
                />
              </div>
            )}

            {activePanel === 'dashboard' && dashboard && onDashboardChange && layers && (
              <LazyLoadErrorBoundary>
                <Suspense fallback={
                  <div className="flex-1 flex items-center justify-center p-4">
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  </div>
                }>
                  <DashboardEditorPanel
                    draft={dashboard}
                    onChange={onDashboardChange}
                    layers={layers}
                    map={map ?? null}
                  />
                </Suspense>
              </LazyLoadErrorBoundary>
            )}

            {activePanel === 'history' && (
              <HistoryPanel mapId={mapId} />
            )}

            {/* The panel's initializers judge the remembered form against
                `layers` at mount, but on direct /maps/:id navigation the page
                keeps the previous map's layers until its sync effect runs;
                mounting then would discard and overwrite the new map's
                remembered form against the wrong rows. Hold the mount until the
                layers are known to belong to this map. */}
            {activePanel === 'analysis' &&
              layers &&
              mapId != null &&
              layersMapId !== mapId && (
                <div className="flex-1 flex items-center justify-center p-4">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              )}
            {activePanel === 'analysis' && layers && (mapId == null || layersMapId === mapId) && (
              <LazyLoadErrorBoundary>
                <Suspense fallback={
                  <div className="flex-1 flex items-center justify-center p-4">
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  </div>
                }>
                  <AnalysisPanel
                    // Keyed by map as well: direct navigation between /maps/:id
                    // routes (fork, "open new map") reuses this mounted tree and
                    // the panel's initializers run on mount only, so without the
                    // remount the new map would inherit the previous map's form,
                    // mask and job state. The map id is in both variants because
                    // an active prefill's nonce doesn't change on a map switch.
                    key={
                      analysisPrefill
                        ? `prefill-${mapId ?? 'none'}-${analysisPrefill.nonce}`
                        : `map-${mapId ?? 'none'}`
                    }
                    layers={layers}
                    mapId={mapId}
                    selectedLayerId={selectedLayerId}
                    mapInstanceRef={mapInstanceRef}
                    onPreviewResult={onQueryResult}
                    onClearPreview={onClearPreview}
                    hasPreview={hasPreview}
                    previewSource={previewSource}
                    layerActions={layerActions}
                    prefill={analysisPrefill ?? undefined}
                    onAnalysisJobChange={onAnalysisJobChange}
                  />
                </Suspense>
              </LazyLoadErrorBoundary>
            )}

            {activePanel === 'ai' && !aiAvailable && <AIDisabledState />}

            {activePanel === 'ai' && aiAvailable && mapId && layers && layerActions && (
              <LazyLoadErrorBoundary>
                <Suspense fallback={
                  <div className="flex-1 flex items-center justify-center p-4">
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  </div>
                }>
                  <ChatPanel
                    mapId={mapId}
                    layers={layers}
                    layerActions={layerActions}
                    onQueryResult={onQueryResult}
                    onClearPreview={onClearPreview}
                    viewport={viewport}
                  />
                </Suspense>
              </LazyLoadErrorBoundary>
            )}
          </div>
        </aside>
      )}
    </>
  );
}
