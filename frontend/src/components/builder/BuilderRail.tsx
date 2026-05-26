import { useCallback, useMemo, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, History, Sparkles, ChevronRight, Loader2 } from 'lucide-react';
import { LazyLoadErrorBoundary } from '@/components/error/LazyLoadErrorBoundary';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { experimentalBadgeColor } from '@/lib/status-colors';
import type { MapLayerResponse } from '@/types/api';
import type { LayerActions } from '@/components/builder/ChatPanel';
import { HistoryPanel } from '@/components/builder/HistoryPanel';

const ChatPanel = lazy(() => import('@/components/builder/ChatPanel').then(m => ({ default: m.ChatPanel })));

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
                'flex items-center justify-center h-8 w-8 rounded-md transition-colors',
                btn.disabled
                  ? 'text-muted-foreground/40 cursor-not-allowed'
                  : activePanel === btn.id
                    ? 'cursor-pointer bg-accent text-primary'
                    : 'cursor-pointer text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <btn.icon className="h-4 w-4" />
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

            {activePanel === 'ai' && !aiAvailable && (
              <div className="flex h-full flex-col justify-center gap-2 p-4 text-sm" role="status" aria-live="polite">
                <p className="font-medium text-foreground">
                  {t('rail.aiUnavailableTitle', { defaultValue: 'AI is unavailable' })}
                </p>
                <p className="text-muted-foreground">
                  {t('rail.aiUnavailableDescription', {
                    defaultValue: 'An administrator needs to enable an AI provider before Ask AI can be used in this builder.',
                  })}
                </p>
              </div>
            )}

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
