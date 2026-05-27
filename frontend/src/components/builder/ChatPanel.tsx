import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2, RotateCcw, SendHorizontal, Square, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { sendChatMessage, streamChatMessage } from '@/api/maps';
import { ApiError } from '@/api/client';
import { cn } from '@/lib/utils';
import { normalizeLayerOpacity } from '@/components/builder/builder-action-contract';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, ChatAction, ChatHistoryMessage, LabelConfig, StyleConfig } from '@/types/api';
import { ChatInput } from './ChatInput';
import { getSmartSuggestions } from './chat-suggestions';

const prefersReducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;

/** Remove chat history entries that reference a removed layer. */
function cleanStaleLayerRefs(mapId: string, removedLayerId: string) {
  const stored = sessionStorage.getItem(`geolens-chat-${mapId}`);
  if (!stored) return;
  try {
    const history = JSON.parse(stored);
    const filtered = history.filter((msg: Record<string, unknown>) => {
      const acts = msg.actions as ChatAction[] | undefined;
      if (!acts) return true;
      return !acts.some((a) => a.layer_id === removedLayerId);
    });
    sessionStorage.setItem(`geolens-chat-${mapId}`, JSON.stringify(filtered));
  } catch { /* ignore parse errors */ }
}

/**
 * AI chat panel for the map builder.
 *
 * Streams responses from the `/ai/chat/` endpoint and applies returned
 * `ChatAction` items live to the parent map (set_filter, set_style,
 * set_data_driven_style, add_layer, remove_layer, etc.) without persisting
 * changes until the user saves the map. Includes smart suggestion chips
 * derived from the current layer state, retry on transient errors, and
 * cancellable in-flight requests via AbortController.
 *
 * Mounted from `pages/MapBuilderPage.tsx` only when AI is enabled in admin
 * settings AND a provider API key is configured.
 */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  actions?: ChatAction[];
  retryMessage?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function getActionLayerId(action: ChatAction): string | null {
  return typeof action.layer_id === 'string' && action.layer_id ? action.layer_id : null;
}

function getActionDatasetId(action: ChatAction): string | null {
  return typeof action.dataset_id === 'string' && action.dataset_id ? action.dataset_id : null;
}

function getActionPaint(action: Pick<ChatAction, 'paint'>): Record<string, unknown> | null {
  return isRecord(action.paint) ? action.paint : null;
}

function getActionClearPaint(action: Pick<ChatAction, 'clear_paint'>): string[] {
  return Array.isArray(action.clear_paint)
    ? action.clear_paint.filter((key): key is string => typeof key === 'string' && key.length > 0)
    : [];
}

function getChatActions(value: unknown): ChatAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ChatAction => isRecord(item) && typeof item.type === 'string');
}

export function buildChatActionPaint(
  currentPaint: Record<string, unknown> | null | undefined,
  action: Pick<ChatAction, 'paint' | 'clear_paint' | 'replace_paint'>,
): Record<string, unknown> {
  const nextPaint: Record<string, unknown> = action.replace_paint ? {} : { ...(currentPaint ?? {}) };
  for (const [key, value] of Object.entries(getActionPaint(action) ?? {})) {
    if (value == null) {
      delete nextPaint[key];
    } else {
      nextPaint[key] = value;
    }
  }
  for (const key of getActionClearPaint(action)) {
    delete nextPaint[key];
  }
  return nextPaint;
}

function hasPaintMutation(action: ChatAction): boolean {
  const paint = getActionPaint(action);
  return Boolean(
    (paint && Object.keys(paint).length > 0) ||
    getActionClearPaint(action).length > 0 ||
    (action.replace_paint === true && paint),
  );
}

function isUndoSafeAction(action: ChatAction): boolean {
  return action.type !== 'add_layer'
    && action.type !== 'remove_layer'
    && action.type !== 'show_query_result';
}

export interface LayerActions {
  onFilterChange: (layerId: string, expression: FilterSpecification | null) => void;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLabelChange: (layerId: string, config: LabelConfig | null) => void;
  onToggleVisibility: (layerId: string, visible?: boolean) => void;
  onAddDataset: (datasetId: string) => void;
  onRemove: (layerId: string) => void;
  onOpacityChange?: (layerId: string, opacity: number) => void;
}

interface ChatPanelProps {
  mapId: string;
  layers: MapLayerResponse[];
  layerActions: LayerActions;
  onQueryResult?: (geojson: GeoJSON.FeatureCollection, bbox: [number, number, number, number]) => void;
  /** Use side-by-side layout: messages left, compose right. */
  horizontal?: boolean;
}

export function ChatPanel({
  mapId,
  layers,
  layerActions,
  onQueryResult,
  horizontal,
}: ChatPanelProps) {
  const {
    onFilterChange,
    onPaintChange,
    onStyleConfigChange,
    onLabelChange,
    onToggleVisibility,
    onAddDataset,
    onRemove,
    onOpacityChange,
  } = layerActions;
  const { t, i18n } = useTranslation('builder');
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const stored = sessionStorage.getItem(`geolens-chat-${mapId}`);
      return stored ? JSON.parse(stored) : [];
    } catch (e) { if (import.meta.env.DEV) console.warn('[ChatPanel] sessionStorage error:', e); return []; }
  });
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [toolProgress, setToolProgress] = useState<string | null>(null);
  const [timeoutMessage, setTimeoutMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Synchronous inflight lock — setIsLoading is async-batched, so two same-
  // tick handleSend calls would both see isLoading=false and both fetch.
  const inflightRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Keep a ref to the latest layers so snapshots capture fresh state
  const layersRef = useRef(layers);
  layersRef.current = layers;
  // Phase 20260526-builder-audit BLD-20260526-04: single-level undo for chat-initiated map mutations.
  const lastSnapshotRef = useRef<{ layers: MapLayerResponse[]; messageIndex: number; supportsUndo: boolean } | null>(null);

  // Persist chat history to sessionStorage
  useEffect(() => {
    if (messages.length > 0) {
      try { sessionStorage.setItem(`geolens-chat-${mapId}`, JSON.stringify(messages.slice(-50))); } catch (e) { if (import.meta.env.DEV) console.warn('[ChatPanel] sessionStorage error:', e); }
    } else {
      try { sessionStorage.removeItem(`geolens-chat-${mapId}`); } catch { /* ignore */ }
    }
  }, [messages, mapId]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth' });
  }, [messages, isLoading, streamingText]);

  // Progressive timeout with targeted setTimeouts
  useEffect(() => {
    if (!isLoading) { setTimeoutMessage(null); return; }
    const timers = [
      setTimeout(() => setTimeoutMessage(t('chat.stillWorking')), 5000),
      setTimeout(() => setTimeoutMessage(t('chat.takingLonger')), 15000),
      setTimeout(() => setTimeoutMessage(t('chat.almostThere')), 30000),
    ];
    return () => timers.forEach(clearTimeout);
  }, [isLoading, t]);

  function mapApiErrorToMessage(err: unknown): string {
    if (err instanceof ApiError) {
      if (err.status === 401) return t('chat.errorSessionExpired');
      if (err.status === 403) return t('chat.errorForbidden');
      if (err.status === 502 || err.status === 503) return t('chat.errorAiUnavailable');
    }
    return t('chat.errorFriendly');
  }

  function dispatchQueryResult(action: ChatAction) {
    const geojson = action.geojson;
    if (
      geojson &&
      typeof geojson === 'object' &&
      'type' in geojson &&
      geojson.type === 'FeatureCollection' &&
      Array.isArray(action.bbox) &&
      action.bbox.length === 4 &&
      action.bbox.every((n: unknown) => typeof n === 'number')
    ) {
      const [minX, minY, maxX, maxY] = action.bbox as [number, number, number, number];
      // Phase 20260526-builder-audit BLD-20260526-11: reject bbox values outside WGS84 bounds.
      if (minX < -180 || minY < -90 || maxX > 180 || maxY > 90) return;
      onQueryResult?.(
        geojson as GeoJSON.FeatureCollection,
        [minX, minY, maxX, maxY],
      );
    }
  }

  // Phase 20260526-builder-audit BLD-20260526-04: restore layers from the last snapshot.
  const handleUndo = useCallback(() => {
    const snapshot = lastSnapshotRef.current;
    if (!snapshot?.supportsUndo) return;
    const snapshotIds = new Set(snapshot.layers.map((l) => l.id));
    const currentIds = new Set(layersRef.current.map((l) => l.id));

    // Phase 20260526-builder-audit BLD-20260526-04: remove layers that were added after the snapshot.
    for (const id of currentIds) {
      if (!snapshotIds.has(id)) onRemove(id);
    }
    // Phase 20260526-builder-audit BLD-20260526-04: re-add layers that were removed after the snapshot.
    for (const layer of snapshot.layers) {
      if (!currentIds.has(layer.id)) {
        onAddDataset(layer.dataset_id);
      }
    }

    for (const layer of snapshot.layers) {
      // Restore paint
      if (layer.paint) onPaintChange(layer.id, layer.paint);
      // Restore filter
      onFilterChange(layer.id, layer.filter ?? null);
      // Restore label config
      onLabelChange(layer.id, layer.label_config ?? null);
      // Restore visibility
      onToggleVisibility(layer.id, layer.visible);
      // Restore style config
      if (layer.style_config) {
        onStyleConfigChange(layer.id, layer.style_config, layer.paint);
      }
      // Restore opacity
      if (onOpacityChange) onOpacityChange(layer.id, layer.opacity);
    }
    lastSnapshotRef.current = null;
    toast.success(t('chat.undoApplied'));
  }, [onPaintChange, onFilterChange, onLabelChange, onToggleVisibility, onStyleConfigChange, onOpacityChange, onRemove, onAddDataset, t]);

  function handleChatAction(action: ChatAction) {
    const layerId = getActionLayerId(action);
    switch (action.type) {
      case 'set_filter':
        if (layerId) onFilterChange(layerId, Array.isArray(action.expression) ? action.expression : null);
        break;
      case 'set_style':
        if (layerId && hasPaintMutation(action)) {
          const layer = layersRef.current.find((candidate) => candidate.id === layerId);
          if (layer) onPaintChange(layerId, buildChatActionPaint(layer.paint, action));
        }
        break;
      case 'set_data_driven_style':
        if (layerId && getActionPaint(action)) {
          const layer = layersRef.current.find((candidate) => candidate.id === layerId);
          const nextPaint = buildChatActionPaint(layer?.paint, action);
          onStyleConfigChange(
            layerId,
            isRecord(action.style_config) ? action.style_config as StyleConfig : null,
            nextPaint,
          );
        }
        break;
      case 'set_label':
        if (layerId) {
          if (isRecord(action.label_config)) {
            onLabelChange(layerId, action.label_config as LabelConfig);
          } else {
            onLabelChange(layerId, null);
          }
        }
        break;
      case 'toggle_visibility':
        if (layerId) onToggleVisibility(layerId, typeof action.visible === 'boolean' ? action.visible : undefined);
        break;
      case 'show_query_result':
        dispatchQueryResult(action);
        break;
      case 'add_layer': {
        const datasetId = getActionDatasetId(action);
        if (datasetId) onAddDataset(datasetId);
        break;
      }
      case 'remove_layer':
        if (layerId) onRemove(layerId);
        break;
      case 'set_opacity': {
        const opacity = normalizeLayerOpacity(action.opacity);
        if (layerId && opacity !== null) {
          onOpacityChange?.(layerId, opacity);
        }
        break;
      }
    }
  }

  function buildHistory(): ChatHistoryMessage[] {
    // Send last 20 messages as conversation history (capped server-side too)
    return messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-20)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }));
  }

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // Abort on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  async function handleSend() {
    if (!input.trim() || isLoading || inflightRef.current) return;
    inflightRef.current = true;
    const userMsg = input.trim();
    setInput('');
    const history = buildHistory();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', content: userMsg },
    ]);
    setIsLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let text = '';
    const pendingActions: ChatAction[] = [];
    try {

      for await (const { event, data } of streamChatMessage(mapId, userMsg, layers, i18n.language, history, controller.signal)) {
        switch (event) {
          case 'token':
            text += data.text;
            setStreamingText(text);
            break;
          case 'tool_start':
            setToolProgress(typeof data.label === 'string' ? data.label : '');
            break;
          case 'tool_result':
            setToolProgress(null);
            break;
          case 'actions': {
            const actions = getChatActions(data.actions);
            if (actions.length === 0) break;
            // Phase 20260526-builder-audit BLD-20260526-04: snapshot only for actions undo can safely replay.
            const mutatingActions = actions.filter((action) => action.type !== 'show_query_result');
            if (pendingActions.length === 0 && mutatingActions.length > 0) {
              lastSnapshotRef.current = {
                layers: [...layersRef.current],
                messageIndex: messages.length,
                supportsUndo: mutatingActions.every(isUndoSafeAction),
              };
            }
            for (const action of actions) {
              if (action.type === 'show_query_result') {
                dispatchQueryResult(action);
                continue;
              }
              handleChatAction(action);
              pendingActions.push(action);
              if (!isUndoSafeAction(action) && lastSnapshotRef.current) {
                lastSnapshotRef.current.supportsUndo = false;
              }
              // Phase 20260526-builder-audit BLD-20260526-11: clean stale layer refs from session history after remove_layer.
              const layerId = getActionLayerId(action);
              if (action.type === 'remove_layer' && layerId) {
                cleanStaleLayerRefs(mapId, layerId);
              }
            }
            break;
          }
          case 'done': {
            const finalText = (typeof data.explanation === 'string' ? data.explanation : '') || text;
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: 'assistant',
                content: finalText,
                actions: pendingActions.length > 0 ? pendingActions : undefined,
              },
            ]);
            break;
          }
          case 'error':
            throw new Error(data.message as string);
        }
      }
    } catch (err) {
      // If aborted, show cancellation message and don't retry
      if (controller.signal.aborted) {
        if (pendingActions.length > 0) {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: text || t('chat.cancelled'),
              actions: pendingActions,
            },
          ]);
        } else {
          setMessages((prev) => [
            ...prev,
            { id: crypto.randomUUID(), role: 'assistant', content: t('chat.cancelled') },
          ]);
        }
        return;
      }

      // Only fall back to non-streaming if no actions were already applied
      if (pendingActions.length > 0) {
        // Streaming already applied some actions before failing
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: text || t('chat.streamInterrupted'),
            actions: pendingActions,
          },
        ]);
      } else if (err instanceof ApiError && (err.status === 401 || err.status === 403 || err.status === 502 || err.status === 503)) {
        // Known auth/permission/service error — don't retry, show directly
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'error',
            content: mapApiErrorToMessage(err),
            retryMessage: userMsg,
          },
        ]);
      } else {
        // No actions applied yet — safe to retry via non-streaming
        try {
          const response = await sendChatMessage(mapId, userMsg, layers, i18n.language, [...history, { role: 'user', content: userMsg }]);
          // Phase 20260526-builder-audit BLD-20260526-04: snapshot layers before non-streaming fallback mutations.
          const responseActions = getChatActions(response.actions);
          if (responseActions.length > 0) {
            lastSnapshotRef.current = {
              layers: [...layersRef.current],
              messageIndex: messages.length,
              supportsUndo: responseActions.every(isUndoSafeAction),
            };
          }
          for (const action of responseActions) {
            handleChatAction(action);
            if (!isUndoSafeAction(action) && lastSnapshotRef.current) {
              lastSnapshotRef.current.supportsUndo = false;
            }
            // Phase 20260526-builder-audit BLD-20260526-11: clean stale layer refs after remove_layer.
            const layerId = getActionLayerId(action);
            if (action.type === 'remove_layer' && layerId) {
              cleanStaleLayerRefs(mapId, layerId);
            }
          }
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: response.explanation,
              actions: responseActions.length > 0 ? responseActions : undefined,
            },
          ]);
        } catch (fallbackErr) {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'error',
              content: mapApiErrorToMessage(fallbackErr),
              retryMessage: userMsg,
            },
          ]);
        }
      }
    } finally {
      abortRef.current = null;
      inflightRef.current = false;
      setStreamingText('');
      setToolProgress(null);
      setIsLoading(false);
    }
  }

  function handleRetry(msg: ChatMessage) {
    if (msg.retryMessage) setInput(msg.retryMessage);
    setMessages((prev) => prev.filter((m) => m.id !== msg.id));
  }

  return (
    <div ref={containerRef} className={cn("flex h-full", horizontal ? "flex-row" : "flex-col")}>
      {/* Message list */}
      <div className={cn("flex-1 overflow-y-auto px-3 py-2 space-y-2", horizontal && "border-e")} role="log" aria-live="polite">
        {messages.length === 0 && (
          <div className="py-4 space-y-3">
            <p className="text-xs text-muted-foreground text-center">
              {t('chat.emptyState')}
            </p>
            <div className="flex flex-wrap gap-1.5 px-1 justify-center">
              {(layers.length === 0
                ? [t('chat.suggestions.searchDatasets')]
                : getSmartSuggestions(layers, t)
              ).map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="cursor-pointer text-xs px-2.5 py-1 rounded-full border border-border hover:bg-accent hover:border-primary/30 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => {
                    setInput(suggestion);
                    requestAnimationFrame(() => {
                      containerRef.current?.querySelector('textarea')?.focus();
                    });
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg) =>
          msg.role === 'error' ? (
            <div key={msg.id} className="flex justify-start">
              <div className="max-w-[85%] bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
                <div className="flex items-start gap-2">
                  <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                  <p className="text-sm text-foreground">{msg.content}</p>
                </div>
                <div className="mt-2 flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1"
                    onClick={() => handleRetry(msg)}
                  >
                    <RotateCcw className="h-3 w-3" />
                    {t('chat.retry')}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div
              key={msg.id}
              className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}
            >
              <div
                className={cn(
                  'max-w-[85%] rounded-lg px-3 py-1.5 text-sm',
                  msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground',
                )}
              >
                <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                {msg.actions && msg.actions.length > 0 && (
                  <div className="flex items-center gap-2 mt-1">
                    <p className="text-xs text-muted-foreground">
                      {t('chat.appliedChanges', { count: msg.actions.length })}
                    </p>
                    {/* Phase 20260526-builder-audit BLD-20260526-04: undo only for replay-safe style/filter edits. */}
                    {lastSnapshotRef.current?.supportsUndo &&
                      lastSnapshotRef.current?.messageIndex !== undefined &&
                      messages.indexOf(msg) === messages.length - 1 &&
                      msg.role === 'assistant' && (
                      <button
                        type="button"
                        className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        onClick={handleUndo}
                      >
                        <Undo2 className="h-3 w-3" />
                        {t('chat.undo')}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ),
        )}
        {isLoading && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg px-3 py-1.5 text-sm bg-muted text-foreground">
              {streamingText ? (
                <p className="whitespace-pre-wrap">{streamingText}</p>
              ) : toolProgress ? (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {toolProgress}
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {t('chat.thinking')}
                </div>
              )}
              {streamingText && toolProgress && (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {toolProgress}
                </div>
              )}
              {isLoading && timeoutMessage && (
                <p className="text-xs text-muted-foreground mt-1">{timeoutMessage}</p>
              )}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className={cn(
        horizontal
          ? "w-80 border-s p-3 flex flex-col gap-2 bg-muted/20 shrink-0"
          : "border-t px-3 py-2 flex items-center gap-2"
      )}>
        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={handleSend}
          layers={layers}
          disabled={isLoading}
          placeholder={t('chat.placeholder')}
          grow={horizontal}
        />
        {horizontal ? (
          <div className="flex items-center gap-2 shrink-0">
            <span className="font-mono text-2xs text-muted-foreground tracking-wider">↵ {t('chat.sendTitle')}</span>
            <div className="flex-1" />
            {isLoading ? (
              <Button size="sm" variant="destructive" onClick={handleCancel} className="h-7 text-xs">
                <Square className="h-3 w-3 me-1" />
                {t('chat.cancelTitle')}
              </Button>
            ) : (
              <Button size="sm" onClick={handleSend} disabled={!input.trim()} className="h-7 text-xs">
                {t('chat.sendTitle')}
              </Button>
            )}
          </div>
        ) : (
          <>
            {isLoading ? (
              <Button
                size="icon-xs"
                variant="destructive"
                onClick={handleCancel}
                aria-label={t('chat.cancelTitle')}
                title={t('chat.cancelTitle')}
              >
                <Square className="h-3 w-3" />
              </Button>
            ) : (
              <Button
                size="icon-xs"
                onClick={handleSend}
                disabled={!input.trim()}
                aria-label={t('chat.sendTitle')}
                title={t('chat.sendTitle')}
              >
                <SendHorizontal className="h-3 w-3" />
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
