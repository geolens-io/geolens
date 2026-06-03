import { useCallback, useMemo, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, History, Sparkles, ChevronRight, Loader2, BotOff } from 'lucide-react';
import { Link } from 'react-router';
import { LazyLoadErrorBoundary } from '@/components/error/LazyLoadErrorBoundary';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { experimentalBadgeColor } from '@/lib/status-colors';
import type { MapLayerResponse } from '@/types/api';
import type { LayerActions } from '@/components/builder/ChatPanel';
import type { ViewportContext } from '@/components/builder/chat-suggestions';
import { HistoryPanel } from '@/components/builder/HistoryPanel';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useAuthStore } from '@/stores/auth-store';

const ChatPanel = lazy(() => import('@/components/builder/ChatPanel').then(m => ({ default: m.ChatPanel })));

/**
 * Structured disabled-state for the AI rail panel.
 * Renders per-reason copy + admin-only Settings CTA per UI-SPEC Surface 3 (Phase 1135 AI-02).
 *
 * Consumes useAIAvailability() internally — TanStack Query deduplicates so there is no
 * extra network call vs. the parent's derivation; the hook just reads the cached result.
 */
function AIDisabledState() {
  const { t } = useTranslation('builder');
  const { reason, isLoading } = useAIAvailability();
  const isAdmin = useAuthStore((s) => s.isAdmin());

  // Loading or indeterminate — render spinner only
  if (isLoading || reason === null) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6" role="status" aria-live="polite">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

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
  const showCTA = ctaKey !== null && isAdmin;

  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 p-6 text-sm"
      role="status"
      aria-live="polite"
      data-ai-reason={reason}
    >
      <BotOff className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">{t(titleKey, { defaultValue: titleDefault })}</p>
      <p className="text-sm text-muted-foreground text-center max-w-[18rem]">{t(bodyKey, { defaultValue: bodyDefault })}</p>
      {showCTA && (
        <Button variant="outline" size="sm" asChild>
          <Link to="/admin/settings?tab=ai">{t(ctaKey!, { defaultValue: ctaDefault })}</Link>
        </Button>
      )}
    </div>
  );
}

export type RailPanel = 'notes' | 'history' | 'ai' | null;

interface BuilderRailProps {
  activePanel: RailPanel;
  onPanelChange: (panel: RailPanel) => void;
  aiAvailable: boolean;
  showRail?: boolean;
  // Notes
  notes: string;
  onNotesChange: (value: string) => void;
  // AI Chat
  mapId?: string;
  layers?: MapLayerResponse[];
  layerActions?: LayerActions;
  onQueryResult?: (geojson: GeoJSON.FeatureCollection, bbox: [number, number, number, number]) => void;
  /** Phase 1135 AI-05: optional viewport context passed through to ChatPanel for
   *  viewport-aware suggestion chips. Purely additive — omitting this prop has no effect. */
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
  mapId,
  layers,
  layerActions,
  onQueryResult,
  viewport,
  onMarkDirty,
  showRail = true,
}: BuilderRailProps) {
  const { t } = useTranslation('builder');

  const togglePanel = useCallback((panel: RailPanel) => {
    onPanelChange(activePanel === panel ? null : panel);
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
      id: 'history' as const,
      icon: History,
      label: t('dock.history', { defaultValue: 'History' }),
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
        <aside className="w-11 bg-background border-s flex flex-col items-center pt-2.5 gap-1 shrink-0">
          {railButtons.map(btn => (
            <button
              key={btn.id}
              onClick={btn.disabled ? undefined : () => togglePanel(btn.id)}
              disabled={btn.disabled}
              data-unavailable={btn.unavailable || undefined}
              title={btn.label}
              aria-label={btn.label}
              aria-pressed={activePanel === btn.id}
              className={cn(
                'relative flex items-center justify-center h-8 w-8 rounded-md transition-colors',
                btn.disabled
                  ? 'text-muted-foreground/40 cursor-not-allowed'
                  : activePanel === btn.id
                    ? 'cursor-pointer bg-accent text-primary'
                    : 'cursor-pointer text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <btn.icon className="h-4 w-4" />
              {/* MAP-22: presence dot — non-whitespace notes render a 6px primary-color dot
                  at the button's top-right corner. aria-label keeps the dot accessible.
                  No animation (static state indicator per UI-SPEC). */}
              {btn.id === 'notes' && notes.trim().length > 0 && (
                <span
                  aria-label={t('rail.notesPresent', { defaultValue: 'Map has notes' })}
                  className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-primary"
                />
              )}
            </button>
          ))}
        </aside>
      )}

      {/* Expanded panel */}
      {activePanel && (
        <aside
          className={cn(
            'bg-background border-s flex h-full min-h-0 flex-col shrink-0 overflow-hidden',
            showRail ? 'w-80' : 'w-full border-s-0',
          )}
        >
          {/* Panel header */}
          <div className="flex items-center justify-between px-3.5 py-2.5 border-b shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {activePanel === 'notes' && t('dock.notes', { defaultValue: 'Notes' })}
                {activePanel === 'history' && t('dock.history', { defaultValue: 'History' })}
                {activePanel === 'ai' && (aiAvailable
                  ? t('dock.askAi', { defaultValue: 'Ask AI' })
                  : t('rail.aiUnavailable', { defaultValue: 'AI unavailable' }))}
              </span>
              {activePanel === 'ai' && aiAvailable && (
                <Badge variant="outline" className={`text-2xs px-1.5 py-0 ${experimentalBadgeColor}`}>
                  {t('chat.experimental', { defaultValue: 'Experimental' })}
                </Badge>
              )}
            </div>
            <button
              onClick={() => onPanelChange(null)}
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
                <textarea
                  className="min-h-[18rem] w-full flex-1 resize-none rounded-md border border-input bg-transparent p-3 text-sm placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  placeholder={t('dock.notesPlaceholder', { defaultValue: 'Add notes about this map\u2026' })}
                  value={notes}
                  onChange={(e) => {
                    onNotesChange(e.target.value);
                    onMarkDirty?.();
                  }}
                />
              </div>
            )}

            {activePanel === 'history' && (
              <HistoryPanel mapId={mapId} />
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
