import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2, RotateCcw, SendHorizontal, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { sendChatMessage, streamChatMessage } from '@/api/maps';
import { ApiError } from '@/api/client';
import { cn } from '@/lib/utils';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, ChatAction, ChatHistoryMessage, LabelConfig, StyleConfig } from '@/types/api';
import { ChatInput } from './ChatInput';
import { getSmartSuggestions } from './chat-suggestions';

const prefersReducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  actions?: ChatAction[];
  retryMessage?: string;
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
}

export function ChatPanel({
  mapId,
  layers,
  layerActions,
  onQueryResult,
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
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Persist chat history to sessionStorage
  useEffect(() => {
    if (messages.length > 0) {
      try { sessionStorage.setItem(`geolens-chat-${mapId}`, JSON.stringify(messages.slice(-50))); } catch (e) { if (import.meta.env.DEV) console.warn('[ChatPanel] sessionStorage error:', e); }
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
      onQueryResult?.(
        geojson as GeoJSON.FeatureCollection,
        action.bbox as [number, number, number, number],
      );
    }
  }

  function handleChatAction(action: ChatAction) {
    switch (action.type) {
      case 'set_filter':
        if (action.layer_id) onFilterChange(action.layer_id, action.expression ?? null);
        break;
      case 'set_style':
        if (action.layer_id && action.paint) onPaintChange(action.layer_id, action.paint);
        break;
      case 'set_data_driven_style':
        if (action.layer_id && action.paint) {
          onStyleConfigChange(action.layer_id, action.style_config ?? null, action.paint);
        }
        break;
      case 'set_label':
        if (action.layer_id) {
          if (action.label_config) {
            onLabelChange(action.layer_id, action.label_config);
          } else {
            onLabelChange(action.layer_id, null);
          }
        }
        break;
      case 'toggle_visibility':
        if (action.layer_id) onToggleVisibility(action.layer_id, action.visible ?? undefined);
        break;
      case 'show_query_result':
        dispatchQueryResult(action);
        break;
      case 'add_layer':
        if (action.dataset_id) onAddDataset(action.dataset_id);
        break;
      case 'remove_layer':
        if (action.layer_id) onRemove(action.layer_id);
        break;
      case 'set_opacity':
        if (action.layer_id && action.opacity !== undefined && action.opacity !== null) {
          onOpacityChange?.(action.layer_id, action.opacity);
        }
        break;
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
    if (!input.trim() || isLoading) return;
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
          case 'actions':
            for (const action of data.actions as ChatAction[]) {
              if (action.type === 'show_query_result') {
                dispatchQueryResult(action);
                continue;
              }
              handleChatAction(action);
              pendingActions.push(action);
            }
            break;
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
          const response = await sendChatMessage(mapId, userMsg, layers, i18n.language, history);
          for (const action of response.actions) handleChatAction(action);
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: response.explanation,
              actions: response.actions,
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
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2" role="log" aria-live="polite">
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
                  className="text-xs px-2.5 py-1 rounded-full border border-border hover:bg-accent hover:border-primary/30 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => {
                    setInput(suggestion);
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
                <p className="whitespace-pre-wrap">{msg.content}</p>
                {msg.actions && msg.actions.length > 0 && (
                  <p className="text-xs mt-1 text-muted-foreground">
                    {t('chat.appliedChanges', { count: msg.actions.length })}
                  </p>
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
      <div className="border-t px-3 py-2 flex items-center gap-2">
        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={handleSend}
          layers={layers}
          disabled={isLoading}
          placeholder={t('chat.placeholder')}
        />
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
      </div>
    </div>
  );
}
