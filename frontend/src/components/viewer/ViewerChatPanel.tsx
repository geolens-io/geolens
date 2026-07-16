import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2, RotateCcw, SendHorizontal, Sparkles, Square, X } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/api/client';
import { streamChatMessage } from '@/api/maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useEphemeralLayers } from '@/components/builder/hooks/use-ephemeral-layers';
import { cn } from '@/lib/utils';
import type { ChatAction, ChatHistoryMessage, MapLayerResponse } from '@/types/api';

const prefersReducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;

interface QueryResult {
  rows: unknown[];
  columns: string[];
  rowCount: number;
  truncated: boolean;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  queryResult?: QueryResult;
  retryMessage?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function getChatActions(value: unknown): ChatAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ChatAction => isRecord(item) && typeof item.type === 'string');
}

/** Compact, read-only render of a `show_query_result` table (cols capped at 5). */
function QueryResultTable({ result }: { result: QueryResult }) {
  const { t } = useTranslation('common');
  const { rows, columns, rowCount, truncated } = result;
  if (rows.length === 0 || columns.length === 0) {
    return (
      <div className="mt-2 rounded-md border px-3 py-2">
        <p className="text-sm text-muted-foreground">{t('viewer.ai.queryResult.empty')}</p>
      </div>
    );
  }
  const visibleColumns = columns.slice(0, 5);
  const hasMore = columns.length > 5;
  const cellAt = (row: unknown, index: number): string => {
    const raw = Array.isArray(row) ? row[index] : undefined;
    return raw == null ? '' : String(raw);
  };
  return (
    <div className="mt-2 overflow-hidden rounded-md border">
      <div className="max-h-48 overflow-y-auto" role="region" aria-label={t('viewer.ai.queryResult.tableLabel')}>
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="bg-muted/50">
              {visibleColumns.map((col) => (
                <th key={col} scope="col" className="px-2 py-1 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {col}
                </th>
              ))}
              {hasMore && <th scope="col" aria-label={t('viewer.ai.queryResult.moreColumns')} className="px-2 py-1 text-xs text-muted-foreground">…</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={idx} className="border-b border-border last:border-0">
                {visibleColumns.map((col, colIdx) => {
                  const display = cellAt(row, colIdx);
                  return (
                    <td key={col} className="max-w-[8rem] truncate px-2 py-1 text-foreground" title={display}>
                      {display}
                    </td>
                  );
                })}
                {hasMore && <td className="px-2 py-1 text-muted-foreground">…</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-2 py-1 text-xs text-muted-foreground">
        {t('viewer.ai.queryResult.rowCount', { count: rowCount })}
        {truncated && <span className="ms-1 text-muted-foreground">{t('viewer.ai.queryResult.truncated')}</span>}
      </p>
    </div>
  );
}

interface ViewerChatPanelProps {
  mapId: string;
  layers: MapLayerResponse[];
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
}

/**
 * Read-only "Ask AI" for the public map viewer.
 *
 * The builder's full ChatPanel is reachable only to `can_edit` users; signed-in
 * viewers land on PublicMapViewerPage with no AI affordance. PR #339 made the
 * backend chat path serve view-only callers a read-only toolbox (`query_data`
 * only), so this surfaces that path: a question goes to `/ai/chat/stream/`, the
 * streamed answer renders inline, and a `show_query_result` flies the map to the
 * matched features (shared `useEphemeralLayers` overlay) + shows a compact table.
 *
 * Self-gates on `useAIAvailability` (token + `use_ai_chat` + AI configured), so
 * anonymous or unpermitted viewers render nothing. No edit actions are applied —
 * non-query actions are ignored defensively.
 */
export function ViewerChatPanel({ mapId, layers, mapInstanceRef }: ViewerChatPanelProps) {
  const { t, i18n } = useTranslation('common');
  const { isAIAvailable } = useAIAvailability();
  const { handleQueryResult } = useEphemeralLayers(mapInstanceRef);

  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingText, setStreamingText] = useState('');

  const abortRef = useRef<AbortController | null>(null);
  const inflightRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth' });
  }, [messages, isLoading, streamingText]);

  // Abort any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  /** Flyover + highlight (WGS84-bounded bbox guard) and extract the table payload. */
  const applyQueryResult = useCallback((action: ChatAction): QueryResult | undefined => {
    const geojson = action.geojson;
    if (
      geojson &&
      typeof geojson === 'object' &&
      'type' in geojson &&
      geojson.type === 'FeatureCollection' &&
      Array.isArray(action.bbox) &&
      action.bbox.length === 4 &&
      // fix(#527 B-054/C-06): Number.isFinite + non-inverted — NaN/inverted
      // bounds pass the range comparisons and throw in fitBounds.
      action.bbox.every((n: unknown) => Number.isFinite(n))
    ) {
      const [minX, minY, maxX, maxY] = action.bbox as [number, number, number, number];
      if (!(minX < -180 || minY < -90 || maxX > 180 || maxY > 90 || minX > maxX || minY > maxY)) {
        handleQueryResult(geojson as GeoJSON.FeatureCollection, [minX, minY, maxX, maxY]);
      }
    }
    const rows = Array.isArray(action.rows) ? action.rows : null;
    if (rows === null) return undefined;
    return {
      rows,
      columns: Array.isArray(action.columns) ? action.columns.filter((c): c is string => typeof c === 'string') : [],
      rowCount: typeof action.row_count === 'number' ? action.row_count : rows.length,
      truncated: action.truncated === true,
    };
  }, [handleQueryResult]);

  const handleSend = useCallback(async () => {
    const userMsg = input.trim();
    if (!userMsg || isLoading || inflightRef.current) return;
    inflightRef.current = true;
    setInput('');
    const history: ChatHistoryMessage[] = messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-20)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }));
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content: userMsg }]);
    setIsLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let streamed = '';
    let queryResult: QueryResult | undefined;
    try {
      for await (const { event, data } of streamChatMessage(mapId, userMsg, layers, i18n.language, history, controller.signal)) {
        if (event === 'token') {
          streamed += typeof data.text === 'string' ? data.text : '';
          setStreamingText(streamed);
        } else if (event === 'actions') {
          // Read-only: only show_query_result is acted on; any edit action is ignored.
          for (const action of getChatActions(data.actions)) {
            if (action.type === 'show_query_result') {
              const qr = applyQueryResult(action);
              if (qr) queryResult = qr;
            }
          }
        } else if (event === 'done') {
          const finalText = (typeof data.explanation === 'string' ? data.explanation : '') || streamed;
          setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: finalText, queryResult }]);
        } else if (event === 'error') {
          // A pre-flight HTTP status (403/503) rides the SSE error event; surface it
          // as ApiError so it classifies honestly rather than as a generic failure.
          if (typeof data.status === 'number') {
            throw new ApiError(typeof data.message === 'string' ? data.message : '', data.status);
          }
          throw new Error(typeof data.message === 'string' ? data.message : '');
        }
      }
    } catch {
      if (controller.signal.aborted) {
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: 'assistant', content: streamed || t('viewer.ai.cancelled') },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: 'error', content: t('viewer.ai.error'), retryMessage: userMsg },
        ]);
      }
    } finally {
      abortRef.current = null;
      inflightRef.current = false;
      setStreamingText('');
      setIsLoading(false);
    }
  }, [input, isLoading, messages, mapId, layers, i18n.language, applyQueryResult, t]);

  const handleRetry = useCallback((msg: ChatMessage) => {
    if (msg.retryMessage) setInput(msg.retryMessage);
    setMessages((prev) => prev.filter((m) => m.id !== msg.id));
  }, []);

  if (!isAIAvailable) return null;

  return (
    <div className="absolute bottom-8 right-3 z-10 flex flex-col items-end gap-2">
      {open && (
        <section
          role="dialog"
          aria-label={t('viewer.ai.title')}
          className="flex h-[min(70vh,520px)] w-[min(360px,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border bg-background/98 shadow-lg backdrop-blur"
        >
          <div className="flex items-center justify-between border-b px-3 py-2">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">{t('viewer.ai.title')}</h2>
            </div>
            <Button size="icon-xs" variant="ghost" onClick={() => setOpen(false)} aria-label={t('close')}>
              <X className="size-4" />
            </Button>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2" role="log" aria-live="polite">
            {messages.length === 0 && (
              <div className="space-y-1 py-6 text-center">
                <p className="text-sm text-muted-foreground">{t('viewer.ai.emptyHint')}</p>
                <p className="text-xs text-muted-foreground">{t('viewer.ai.readOnlyNote')}</p>
              </div>
            )}
            {messages.map((msg) =>
              msg.role === 'error' ? (
                <div key={msg.id} className="flex justify-start">
                  <div className="max-w-[85%] rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
                      <p className="text-sm text-foreground">{msg.content}</p>
                    </div>
                    <div className="mt-2 flex justify-end">
                      <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={() => handleRetry(msg)}>
                        <RotateCcw className="size-3" />
                        {t('viewer.ai.retry')}
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <div key={msg.id} className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div
                    className={cn(
                      'max-w-[85%] rounded-lg px-3 py-1.5 text-sm',
                      msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground',
                    )}
                  >
                    <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                    {msg.queryResult && <QueryResultTable result={msg.queryResult} />}
                  </div>
                </div>
              ),
            )}
            {isLoading && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-lg bg-muted px-3 py-1.5 text-sm text-foreground">
                  {streamingText ? (
                    <p className="whitespace-pre-wrap">{streamingText}</p>
                  ) : (
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Loader2 className="size-3 animate-spin" />
                      {t('viewer.ai.thinking')}
                    </div>
                  )}
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="flex items-end gap-2 border-t px-3 py-2">
            {/* fix(#438): DS-03 — raw textarea kept for the auto-growing
                chat composer; the ui/textarea primitive covers static fields. */}
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              rows={1}
              placeholder={t('viewer.ai.placeholder')}
              disabled={isLoading}
              aria-label={t('viewer.ai.placeholder')}
              className="max-h-28 min-h-9 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            />
            {isLoading ? (
              <Button
                size="icon-xs"
                variant="destructive"
                onClick={() => abortRef.current?.abort()}
                aria-label={t('viewer.ai.cancel')}
                title={t('viewer.ai.cancel')}
              >
                <Square className="size-3" />
              </Button>
            ) : (
              <Button
                size="icon-xs"
                onClick={() => void handleSend()}
                disabled={!input.trim()}
                aria-label={t('viewer.ai.send')}
                title={t('viewer.ai.send')}
              >
                <SendHorizontal className="size-3" />
              </Button>
            )}
          </div>
        </section>
      )}
      {!open && (
        <Button onClick={() => setOpen(true)} aria-haspopup="dialog" className="gap-2 rounded-full shadow-lg">
          <Sparkles className="size-4" aria-hidden="true" />
          {t('viewer.ai.launch')}
        </Button>
      )}
    </div>
  );
}
