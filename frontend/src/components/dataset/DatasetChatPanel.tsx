import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2, Map, RotateCcw, SendHorizontal, Sparkles, Square, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/api/client';
import { streamDatasetChatMessage } from '@/api/maps';
import { useCreateMap } from '@/hooks/use-maps';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { QueryResultTable, type QueryResult } from '@/components/viewer/ViewerChatPanel';
import { stashChatResult, toChatResultHandoff, type ChatResultHandoff } from '@/lib/chat-result-handoff';
import { cn } from '@/lib/utils';
import type { ChatAction, ChatHistoryMessage } from '@/types/api';

const prefersReducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  queryResult?: QueryResult;
  /** Spatial payload of the query result, carried into the builder on open. */
  spatialResult?: ChatResultHandoff;
  retryMessage?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function getChatActions(value: unknown): ChatAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ChatAction => isRecord(item) && typeof item.type === 'string');
}

/** Extract the tabular payload from a show_query_result action (no map here). */
function toQueryResult(action: ChatAction): QueryResult | undefined {
  const rows = Array.isArray(action.rows) ? action.rows : null;
  if (rows === null) return undefined;
  return {
    rows,
    columns: Array.isArray(action.columns) ? action.columns.filter((c): c is string => typeof c === 'string') : [],
    rowCount: typeof action.row_count === 'number' ? action.row_count : rows.length,
    truncated: action.truncated === true,
  };
}

interface DatasetChatPanelProps {
  datasetId: string;
  datasetTitle: string;
  /** fix(#531): non-spatial tables can chat but have no map-layer flow —
   * the rest of the UI (AddToMapButton) hides builder handoffs for them. */
  showOpenInBuilder: boolean;
  /** fix(#583): notifies the page when the panel opens/closes so it can pad
   * its content clear of the fixed panel (which otherwise covers the sticky
   * detail tabs and other controls). */
  onOpenChange?: (open: boolean) => void;
}

/**
 * Dataset-scoped "Ask AI" (dataset-chat v1).
 *
 * Mirrors ViewerChatPanel's read-only chat UX for the dataset detail page:
 * questions go to `/ai/chat/dataset/stream/` (query_data-only tool set, all
 * dataset context resolved server-side), the streamed answer renders inline,
 * and `show_query_result` shows the compact table. There is no map on this
 * page, so instead of a flyover the panel offers "Open in builder" — a new
 * map is created and the builder opens with this dataset staged via the
 * existing `?add_dataset=` flow (AddToMapButton precedent).
 *
 * Self-gates on `useAIAvailability` (token + `use_ai_chat` + AI configured),
 * so anonymous or unpermitted visitors render nothing.
 */
export function DatasetChatPanel({ datasetId, datasetTitle, showOpenInBuilder, onOpenChange }: DatasetChatPanelProps) {
  const { t, i18n } = useTranslation('dataset');
  const navigate = useNavigate();
  const { isAIAvailable } = useAIAvailability();
  const createMap = useCreateMap();

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

  // fix(#583): keep the page informed so it can reflow content clear of the
  // fixed panel. Effect (not inline in the setOpen calls) so unmount while
  // open also reports closed. ANDed with availability — if AI availability
  // flips off while open, the render below bails to null but the component
  // stays mounted, and the page must not keep padding for an invisible panel.
  useEffect(() => {
    onOpenChange?.(open && isAIAvailable);
    return () => onOpenChange?.(false);
  }, [open, isAIAvailable, onOpenChange]);

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
    let spatialResult: ChatResultHandoff | undefined;
    try {
      for await (const { event, data } of streamDatasetChatMessage(datasetId, userMsg, i18n.language, history, controller.signal)) {
        if (event === 'token') {
          streamed += typeof data.text === 'string' ? data.text : '';
          setStreamingText(streamed);
        } else if (event === 'actions') {
          // Read-only surface: only show_query_result is acted on.
          for (const action of getChatActions(data.actions)) {
            if (action.type === 'show_query_result') {
              const qr = toQueryResult(action);
              if (qr) {
                // Keep table and spatial payload PAIRED: both come from the
                // same accepted action, so "Open in builder" never carries
                // geometry from an earlier result than the table shown (#533).
                queryResult = qr;
                spatialResult = toChatResultHandoff(action.geojson, action.bbox) ?? undefined;
              }
            }
          }
        } else if (event === 'done') {
          const finalText = (typeof data.explanation === 'string' ? data.explanation : '') || streamed;
          setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: finalText, queryResult, spatialResult }]);
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
          { id: crypto.randomUUID(), role: 'assistant', content: streamed || t('common:viewer.ai.cancelled') },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: 'error', content: t('common:viewer.ai.error'), retryMessage: userMsg },
        ]);
      }
    } finally {
      abortRef.current = null;
      inflightRef.current = false;
      setStreamingText('');
      setIsLoading(false);
    }
  }, [input, isLoading, messages, datasetId, i18n.language, t]);

  const handleRetry = useCallback((msg: ChatMessage) => {
    if (msg.retryMessage) setInput(msg.retryMessage);
    setMessages((prev) => prev.filter((m) => m.id !== msg.id));
  }, []);

  /** "Open in builder": new map + navigate with this dataset staged (AddToMapButton flow).
   * A spatial query result rides sessionStorage into the builder's ephemeral-layer
   * path; a stash failure (quota/private mode) degrades to opening without it. */
  const handleOpenInBuilder = useCallback(async (spatial?: ChatResultHandoff) => {
    try {
      const name = t('addToMap.newMapName', { title: datasetTitle });
      const newMap = await createMap.mutateAsync({ name });
      const carried = spatial ? stashChatResult(spatial) : false;
      navigate(`/maps/${newMap.id}?add_dataset=${datasetId}${carried ? '&chat_result=1' : ''}`);
    } catch {
      toast.error(t('addToMap.createFailed'));
    }
  }, [createMap, datasetId, datasetTitle, navigate, t]);

  if (!isAIAvailable) return null;

  // bottom-10/end-16 (not bottom-6/end-6) clears the global ReportProblemHost
  // lifebuoy (fixed bottom-10 right-4 z-40, size-10 + count badge): same
  // baseline, 8px gap to its left, so neither the FAB nor the open dialog
  // ever sits under the reporter (no spatial overlap, so the z-tie is moot).
  // fix(#569): z-40 (was z-30) so the sticky z-40 PendingEditsBar can't cover
  // the FAB when pending edits and AI chat coexist; this panel renders later
  // in the DOM, so it wins the tie.
  return (
    <div className="fixed bottom-10 end-16 z-40 flex flex-col items-end gap-2">
      {open && (
        <section
          role="dialog"
          aria-label={t('ai.chat.title')}
          className="flex h-[min(70vh,520px)] w-[min(360px,calc(100vw-4.75rem))] flex-col overflow-hidden rounded-2xl border bg-background/98 shadow-lg backdrop-blur"
        >
          <div className="flex items-center justify-between border-b px-3 py-2">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-foreground">{t('ai.chat.title')}</h2>
            </div>
            <Button size="icon-xs" variant="ghost" onClick={() => setOpen(false)} aria-label={t('common:close')}>
              <X className="size-4" />
            </Button>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2" role="log" aria-live="polite">
            {messages.length === 0 && (
              <div className="space-y-1 py-6 text-center">
                <p className="text-sm text-muted-foreground">{t('ai.chat.emptyHint')}</p>
                <p className="text-xs text-muted-foreground">{t('ai.chat.readOnlyNote')}</p>
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
                        {t('common:viewer.ai.retry')}
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
                    {msg.queryResult && (
                      <>
                        <QueryResultTable result={msg.queryResult} />
                        {showOpenInBuilder && (
                          <div className="mt-2 flex justify-end">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 gap-1 text-xs"
                              onClick={() => void handleOpenInBuilder(msg.spatialResult)}
                              disabled={createMap.isPending}
                            >
                              {createMap.isPending ? (
                                <Loader2 className="size-3 animate-spin" />
                              ) : (
                                <Map className="size-3" />
                              )}
                              {t('ai.chat.openInBuilder')}
                            </Button>
                          </div>
                        )}
                      </>
                    )}
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
                      {t('common:viewer.ai.thinking')}
                    </div>
                  )}
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="flex items-end gap-2 border-t px-3 py-2">
            {/* Raw textarea kept for the auto-growing chat composer (fix(#438) DS-03). */}
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
              placeholder={t('ai.chat.placeholder')}
              disabled={isLoading}
              aria-label={t('ai.chat.placeholder')}
              className="max-h-28 min-h-9 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            />
            {isLoading ? (
              <Button
                size="icon-xs"
                variant="destructive"
                onClick={() => abortRef.current?.abort()}
                aria-label={t('common:viewer.ai.cancel')}
                title={t('common:viewer.ai.cancel')}
              >
                <Square className="size-3" />
              </Button>
            ) : (
              <Button
                size="icon-xs"
                onClick={() => void handleSend()}
                disabled={!input.trim()}
                aria-label={t('common:viewer.ai.send')}
                title={t('common:viewer.ai.send')}
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
          {t('common:viewer.ai.launch')}
        </Button>
      )}
    </div>
  );
}
