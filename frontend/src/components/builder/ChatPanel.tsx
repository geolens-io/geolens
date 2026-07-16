import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2, Plus, RotateCcw, SendHorizontal, Square, Trash2, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { sendChatMessage, streamChatMessage } from '@/api/maps';
import { ApiError } from '@/api/client';
import { cn } from '@/lib/utils';
import { truncateGraphemes } from '@/lib/text';
import { assertNever, normalizeLayerOpacity } from '@/components/builder/builder-action-contract';
import { validateRawFilter, FilterValidationError } from '@/lib/maplibre-filter-utils';
import { getLayerType, filterPaintForLayerType, clampPaintBounds } from '@/components/builder/layer-adapters/shared';
import { useChatActionStaging, isDestructiveAction } from '@/builder/ai/chat-action-staging';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse, ChatAction, ChatHistoryMessage, LabelConfig, StyleConfig } from '@/types/api';
import { ChatInput } from './ChatInput';
import { getSmartSuggestions, type ViewportContext } from './chat-suggestions';

const prefersReducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;

/**
 * Sentinel for a model-emitted SSE `error` event (e.g. tool-loop exhausted,
 * deadline). Distinct from a transport/stream-start failure: when the model
 * itself errored mid-stream there is nothing to retry, so the catch block must
 * NOT fall through to the non-streaming `sendChatMessage` path (which would
 * double the LLM call). Transport failures keep throwing plain Error / ApiError
 * and still take the legitimate non-streaming fallback.
 */
class StreamModelError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'StreamModelError';
  }
}

/**
 * builder-audit #338 COMPLEX-01: discriminated classification of a chat-send failure.
 *
 * Pure decision function lifted out of handleSend's catch block so the
 * branch order (aborted → partial → service banner → inline → retry) lives in
 * one auditable place. The caller renders the result. Order is significant:
 * `hasPendingActions` is checked before the StreamModelError/ApiError branches
 * so a stream that applied actions before failing never falls through to the
 * non-streaming retry (which would double the LLM call — see StreamModelError).
 */
type ChatErrorOutcome =
  | { kind: 'aborted' }
  | { kind: 'partial' }
  | { kind: 'banner'; bannerKind: 'forbidden' | 'unavailable' }
  | { kind: 'inline' }
  | { kind: 'retry' };

function classifyChatError(
  err: unknown,
  opts: { aborted: boolean; hasPendingActions: boolean },
): ChatErrorOutcome {
  if (opts.aborted) return { kind: 'aborted' };
  if (opts.hasPendingActions) return { kind: 'partial' };
  if (err instanceof ApiError && (err.status === 403 || err.status === 503)) {
    return { kind: 'banner', bannerKind: err.status === 403 ? 'forbidden' : 'unavailable' };
  }
  // fix(#526 B-047): 429 = daily AI token budget / rate limit — retrying is a
  // guaranteed second 429 (and previously surfaced as the generic "something
  // went wrong" after a wasted duplicate POST). Show the real message inline.
  if (err instanceof ApiError && (err.status === 401 || err.status === 429 || err.status === 500 || err.status === 502)) {
    return { kind: 'inline' };
  }
  // StreamModelError: model errored mid-stream — nothing to retry, show inline.
  if (err instanceof StreamModelError) return { kind: 'inline' };
  return { kind: 'retry' };
}

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

// fix(#392): allowlist of the 9 known ChatAction wire types. getChatActions drops
// any item whose `type` is not in this set (rather than letting an unrecognized
// type string reach handleChatAction's switch), and logs the drop in dev. (audit CH-08)
const KNOWN_CHAT_ACTION_TYPES: ReadonlySet<ChatAction['type']> = new Set([
  'set_filter',
  'set_style',
  'set_data_driven_style',
  'set_label',
  'toggle_visibility',
  'add_layer',
  'remove_layer',
  'show_query_result',
  'set_opacity',
]);

function getChatActions(value: unknown): ChatAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is ChatAction => {
    if (!isRecord(item) || typeof item.type !== 'string') return false;
    if (!KNOWN_CHAT_ACTION_TYPES.has(item.type as ChatAction['type'])) {
      if (import.meta.env.DEV) console.warn('[ChatPanel] dropped unknown action type:', item.type);
      return false;
    }
    return true;
  });
}

export function buildChatActionPaint(
  currentPaint: Record<string, unknown> | null | undefined,
  action: Pick<ChatAction, 'paint' | 'clear_paint' | 'replace_paint'>,
): Record<string, unknown> {
  const paint = getActionPaint(action);
  const clearKeys = getActionClearPaint(action);
  // fix(#392): a replace_paint:true with no effective paint keys and no
  // clear_paint must never wipe existing styling — preserve current paint.
  // Defense-in-depth: handleChatAction's set_style case already gates on
  // hasPaintMutation before reaching here, but this guard holds even if
  // buildChatActionPaint is ever called directly with such an action. (audit B-005/CH-09)
  if (action.replace_paint && (!paint || Object.keys(paint).length === 0) && clearKeys.length === 0) {
    return { ...(currentPaint ?? {}) };
  }
  const nextPaint: Record<string, unknown> = action.replace_paint ? {} : { ...(currentPaint ?? {}) };
  for (const [key, value] of Object.entries(paint ?? {})) {
    if (value == null) {
      delete nextPaint[key];
    } else {
      nextPaint[key] = value;
    }
  }
  for (const key of clearKeys) {
    delete nextPaint[key];
  }
  return nextPaint;
}

// fix(#392): a standalone `replace_paint:true` is no longer treated as a
// mutation on its own — an empty (or empty-after-validation) replace with no
// clear_paint is a no-op, not a wipe. Callers must evaluate this against the
// VALIDATED action (post validateChatPaint) so a replace reduced to empty by
// geometry/bounds validation is also caught. (audit B-005/CH-09)
function hasPaintMutation(action: ChatAction): boolean {
  const paint = getActionPaint(action);
  return Boolean(
    (paint && Object.keys(paint).length > 0) ||
    getActionClearPaint(action).length > 0,
  );
}

/**
 * fix(#392): bridge validator for AI-produced set_style / set_data_driven_style
 * paint before it reaches MapLibre or the save payload. Drops paint properties
 * invalid for the layer's geometry type and clamps numeric properties to their
 * Style-Spec bounds — mirroring backend `validate_paint_with_feedback`
 * (backend/app/processing/ai/schemas.py). Render-mode aware: when `renderMode`
 * is 'heatmap' the geometry-type filter is skipped so heatmap-* properties
 * (valid regardless of the layer's point/line/polygon geometry_type) are kept
 * instead of dropped as invalid-for-circle/line/fill. (audit B-002/CH-01)
 */
// fix(#392): builder custom fill-outline keys the backend allowlist accepts
// (schemas.py `_VALID_PAINT_PROPS['fill']`). filterPaintForLayerType drops ALL
// CUSTOM_PAINT_PROPS, so without re-adding these an AI outline-only set_style on a
// polygon would validate to {}, hasPaintMutation returns false, and the turn silently
// applies nothing — even though the backend accepts the outline change.
const CHAT_PRESERVED_FILL_OUTLINE_KEYS = ['_outline-color', '_outline-width'] as const;

function validateChatPaint(
  rawPaint: Record<string, unknown> | null,
  layer: MapLayerResponse,
  renderMode?: string,
): Record<string, unknown> {
  if (!rawPaint) return {};
  if (renderMode === 'heatmap') return clampPaintBounds(rawPaint);
  const layerType = getLayerType(layer.dataset_geometry_type);
  const filtered = filterPaintForLayerType(rawPaint, layerType);
  if (layerType === 'fill') {
    for (const key of CHAT_PRESERVED_FILL_OUTLINE_KEYS) {
      if (rawPaint[key] != null) filtered[key] = rawPaint[key];
    }
    // fix(#394) CH-01: preserve fill-extrusion-* on the fill branch — the
    // extrusion COMPANION layer consumes them from layer.paint, and the
    // backend keeps them for polygons (_VALID_PAINT_PROPS fill ∪
    // fill-extrusion). Dropping them made an extrusion-only set_style a
    // silent no-op. filterPaintForLayerType still excludes them from the
    // actual MapLibre fill layer at apply time.
    for (const [key, value] of Object.entries(rawPaint)) {
      if (key.startsWith('fill-extrusion-') && value != null) {
        filtered[key] = value;
      }
    }
  }
  return clampPaintBounds(filtered);
}

// fix(#394) CH-02 (codex round 2): hex (3/4/6/8 digits), real CSS named
// colors, or numeric-arg functional forms only — the first-pass shape regex
// let "notacolor"/"rgb(foo)" through to MapLibre paint validation, which is
// exactly what this sanitizer exists to prevent. Byte-parity mirror of
// backend app/processing/ai/colors.py; MapLibre stays the final validator.
const CSS_HEX_RE = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const CSS_FUNCTIONAL_RE = /^(?:rgb|rgba|hsl|hsla)\(\s*[0-9deg.,%\s/+-]{1,60}\s*\)$/;
const CSS_NAMED_COLORS = new Set((
  'aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue '
  + 'blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk '
  + 'crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki '
  + 'darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen '
  + 'darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue '
  + 'dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite '
  + 'gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki '
  + 'lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan '
  + 'lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen '
  + 'lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen '
  + 'magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen '
  + 'mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream '
  + 'mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid '
  + 'palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum '
  + 'powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown '
  + 'seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen '
  + 'steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow '
  + 'yellowgreen transparent'
).split(' '));

function isCssColorish(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const candidate = value.trim();
  return CSS_HEX_RE.test(candidate)
    || CSS_FUNCTIONAL_RE.test(candidate)
    || CSS_NAMED_COLORS.has(candidate.toLowerCase());
}

// fix(#392): clamp bounds for AI-produced set_label numeric fields, matching
// the sliders' own bounds in LabelEditor.tsx (fontSize 8-24px, haloWidth 0-4px)
// so an AI label config can't push text off-scale before it reaches the map. (audit B-002/CH-01)
const LABEL_FONT_SIZE_BOUNDS: [number, number] = [8, 24];
const LABEL_HALO_WIDTH_BOUNDS: [number, number] = [0, 4];

function clampLabelConfig(config: LabelConfig): LabelConfig {
  const next = { ...config };
  if (typeof next.fontSize === 'number') {
    next.fontSize = Math.min(LABEL_FONT_SIZE_BOUNDS[1], Math.max(LABEL_FONT_SIZE_BOUNDS[0], next.fontSize));
  }
  if (typeof next.haloWidth === 'number') {
    next.haloWidth = Math.min(LABEL_HALO_WIDTH_BOUNDS[1], Math.max(LABEL_HALO_WIDTH_BOUNDS[0], next.haloWidth));
  }
  return next;
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
  /**
   * Atomically restore the full state of each supplied layer (matched by id).
   * Used by undo to revert all fields in a single update — restoring field-by-field
   * through the individual handlers clobbers earlier reverts (see handleUndo).
   */
  onRestoreLayers: (layers: MapLayerResponse[]) => void;
}

interface ChatPanelProps {
  mapId: string;
  layers: MapLayerResponse[];
  layerActions: LayerActions;
  onQueryResult?: (geojson: GeoJSON.FeatureCollection, bbox: [number, number, number, number]) => void;
  /** Use side-by-side layout: messages left, compose right. */
  horizontal?: boolean;
  /** Phase 1135 AI-05: optional viewport context — zoom, bounds, selected layer name.
   *  Passed to getSmartSuggestions to produce viewport-aware suggestion chips.
   *  Only affects the empty-state chip list; undefined → unchanged geometry-only behavior. */
  viewport?: ViewportContext;
}

export function ChatPanel({
  mapId,
  layers,
  layerActions,
  onQueryResult,
  horizontal,
  viewport,
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
    onRestoreLayers,
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
  // Phase 1135 AI-03: service-level error banner for 403 (permission revoked) and 503 (AI down).
  // Distinct from the inline per-message error bubble used for 401 + network errors.
  const [errorBanner, setErrorBanner] = useState<{ kind: 'forbidden' | 'unavailable'; retryMessage: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Synchronous inflight lock — setIsLoading is async-batched, so two same-
  // tick handleSend calls would both see isLoading=false and both fetch.
  const inflightRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Keep a ref to the latest layers so snapshots capture fresh state
  const layersRef = useRef(layers);
  layersRef.current = layers;
  // Phase 20260526-builder-audit #338 BLD-20260526-04: single-level undo for chat-initiated map mutations.
  // builder-audit #338 DEAD-01: messageIndex dropped — it was only ever read as `!== undefined`
  // (vacuously true); the real ordering gate is messages.indexOf(msg) === length - 1.
  const lastSnapshotRef = useRef<{ layers: MapLayerResponse[]; supportsUndo: boolean } | null>(null);

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

  /**
   * Build the chip text for a staging action per UI-SPEC Surface 1 chip-text-format table.
   * Returns `{ text, fullText }` where `text` is truncated to 60 chars and
   * `fullText` is the complete string for the `title` attribute.
   *
   * Phase 1135 AI-09 — Shape B: additive only, no BuilderActionSource widening.
   */
  function buildChipText(
    action: ChatAction,
    layers: MapLayerResponse[],
    // Use the narrowed `t` from useTranslation('builder') — no generic import needed.
    translator: typeof t,
  ): { text: string; fullText: string } {
    let fullText = '';
    if (action.type === 'add_layer') {
      // Name: use dataset_name from action if backend supplies it; fallback to dataset_id
      const name = action.dataset_name ?? action.dataset_id ?? '';
      // Reference layer: the layer with the lowest sort_order (topmost in stack = renders last).
      // For an add action the new layer lands at the top; the reference is the current topmost.
      const sorted = layers.slice().sort((a, b) => a.sort_order - b.sort_order);
      const topLayer = sorted[0];
      const ref = topLayer ? (topLayer.display_name ?? topLayer.dataset_name) : null;
      if (ref) {
        fullText = translator('chat.staging.chipAddBelow', { name, ref });
      } else {
        fullText = translator('chat.staging.chipAdd', { name });
      }
    } else if (action.type === 'remove_layer') {
      const matched = layers.find((l) => l.id === action.layer_id);
      const name = matched ? (matched.display_name ?? matched.dataset_name) : (action.layer_id ?? '');
      const count = matched?.dataset_feature_count ?? null;
      if (count !== null) {
        fullText = translator('chat.staging.chipRemoveFeatures', { name, count });
      } else {
        fullText = translator('chat.staging.chipRemove', { name });
      }
    }
    const text = truncateGraphemes(fullText, 60, '…');
    return { text, fullText };
  }

  function mapApiErrorToMessage(err: unknown): string {
    if (err instanceof ApiError) {
      if (err.status === 401) return t('chat.errorSessionExpired');
      if (err.status === 403) return t('chat.errorForbidden');
      // fix(#526 B-047): surface the over-budget/rate-limit reason instead of
      // the generic fallback.
      if (err.status === 429) return t('chat.errorRateLimited');
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
      // fix(#527 B-054/C-06): Number.isFinite — NaN passes typeof and every
      // range comparison below, then throws in fitBounds.
      action.bbox.every((n: unknown) => Number.isFinite(n))
    ) {
      const [minX, minY, maxX, maxY] = action.bbox as [number, number, number, number];
      // Phase 20260526-builder-audit #338 BLD-20260526-11: reject bbox values outside WGS84 bounds.
      if (minX < -180 || minY < -90 || maxX > 180 || maxY > 90) return;
      // fix(#527 B-054/C-06): inverted bounds also throw in fitBounds.
      if (minX > maxX || minY > maxY) return;
      onQueryResult?.(
        geojson as GeoJSON.FeatureCollection,
        [minX, minY, maxX, maxY],
      );
    }
  }

  // Phase 20260526-builder-audit #338 BLD-20260526-04: restore layers from the last snapshot.
  const handleUndo = useCallback(() => {
    const snapshot = lastSnapshotRef.current;
    if (!snapshot?.supportsUndo) return;
    const snapshotIds = new Set(snapshot.layers.map((l) => l.id));
    const currentIds = new Set(layersRef.current.map((l) => l.id));

    // Phase 20260526-builder-audit #338 BLD-20260526-04: remove layers that were added after the snapshot.
    for (const id of currentIds) {
      if (!snapshotIds.has(id)) onRemove(id);
    }
    // Phase 20260526-builder-audit #338 BLD-20260526-04: re-add layers that were removed after the snapshot.
    for (const layer of snapshot.layers) {
      if (!currentIds.has(layer.id)) {
        onAddDataset(layer.dataset_id);
      }
    }

    // Restore every snapshotted layer's full state in ONE atomic update.
    // Restoring field-by-field via the individual handlers clobbered earlier
    // reverts: each handler rebuilds the layer from a ref that only refreshes
    // between renders, so a later partial spread (e.g. the unconditional
    // style_config restore on a data-driven layer) re-stamped the stale
    // label_config / paint and silently dropped those reverts — the map showed
    // the change still applied even though undo reported success.
    onRestoreLayers(snapshot.layers);
    lastSnapshotRef.current = null;
    toast.success(t('chat.undoApplied'));
  }, [onRestoreLayers, onRemove, onAddDataset, t]);

  /**
   * Dispatches a single ChatAction and returns whether it produced a real layer
   * mutation. fix(#392): "Applied N changes" must count effect, not intent —
   * a no-op set_style or a rejected set_filter returns false so applyActions
   * never records it in pendingActions (the array the render counts). (audit B-009/CH-07)
   */
  function handleChatAction(action: ChatAction): boolean {
    const layerId = getActionLayerId(action);
    switch (action.type) {
      case 'set_filter':
        if (layerId) {
          // builder-audit #338 P1-13: validate AI-produced filters through the shared
          // filter contract (validateRawFilter mirrors backend filter_grammar)
          // BEFORE applying. null/undefined/[] clear the filter; a malformed array
          // is REJECTED (not applied) rather than handed to MapLibre where it would
          // fail at runtime or round-trip into invalid saved map state.
          try {
            const validated = action.expression == null ? null : validateRawFilter(action.expression);
            onFilterChange(layerId, validated);
            return true;
          } catch (err) {
            if (err instanceof FilterValidationError) {
              if (import.meta.env.DEV) console.warn('[ChatPanel] rejected invalid AI filter:', err.message);
              return false;
            } else {
              throw err;
            }
          }
        }
        return false;
      case 'set_style':
        if (layerId) {
          const layer = layersRef.current.find((candidate) => candidate.id === layerId);
          if (layer) {
            // fix(#392): validate/clamp before checking for a mutation — an
            // action whose paint is reduced to empty by validation must not
            // apply, and must not be treated as a mutation via a bare
            // replace_paint:true either. (audit B-002/CH-01, B-005/CH-09)
            // fix(#392): pass the layer's own render_mode through, same as
            // set_data_driven_style below — set_style is the only AI tool that can tune
            // heatmap-radius/heatmap-opacity/heatmap-intensity, and without render-mode
            // awareness those keys are silently stripped by geometry-type filtering. (audit WR-01)
            const validatedPaint = validateChatPaint(getActionPaint(action), layer, layer.style_config?.render_mode);
            const validatedAction: ChatAction = { ...action, paint: validatedPaint };
            if (hasPaintMutation(validatedAction)) {
              onPaintChange(layerId, buildChatActionPaint(layer.paint, validatedAction));
              return true;
            }
          }
        }
        return false;
      case 'set_data_driven_style': {
        const rawPaint = getActionPaint(action);
        if (layerId && rawPaint) {
          const layer = layersRef.current.find((candidate) => candidate.id === layerId);
          // fix(#394) CH-03: require the target layer — when it isn't found
          // client-side the RAW paint used to be applied unvalidated AND the
          // turn still reported "applied". Mirrors set_style's layer gate.
          if (!layer) return false;
          const styleConfig = isRecord(action.style_config) ? (action.style_config as StyleConfig) : null;
          // fix(#392): render-mode aware — heatmap data-driven paint keeps its heatmap-*
          // properties instead of being dropped as invalid-for-circle. Fall back to the
          // layer's own render_mode when the action omits it (style_config.render_mode is
          // optional), so a data-driven heatmap update on a heatmap layer keeps its
          // heatmap-* paint instead of validating to a no-op. (audit B-002/CH-01)
          const effectiveRenderMode = styleConfig?.render_mode ?? layer.style_config?.render_mode;
          const validatedPaint = validateChatPaint(rawPaint, layer, effectiveRenderMode);
          const validatedAction: ChatAction = { ...action, paint: validatedPaint };
          const nextPaint = buildChatActionPaint(layer.paint, validatedAction);
          // fix(#392): carry the fallback render_mode into the persisted style_config too —
          // onStyleConfigChange REPLACES style_config, so a heatmap layer whose action
          // omitted render_mode would otherwise lose heatmap mode and (adapter resolution
          // prefers geometry) revert to a circle on save/reload.
          const nextConfig = styleConfig && effectiveRenderMode && !styleConfig.render_mode
            ? ({ ...styleConfig, render_mode: effectiveRenderMode } as StyleConfig)
            : styleConfig;
          // fix(#394) CH-03: mutation gate (match set_style) — a paint that
          // validated to empty with no style_config change is a no-op, not an
          // "applied" change.
          if (!hasPaintMutation(validatedAction) && !nextConfig) return false;
          onStyleConfigChange(layerId, nextConfig, nextPaint);
          return true;
        }
        return false;
      }
      case 'set_label':
        if (layerId) {
          if (isRecord(action.label_config)) {
            const lc = action.label_config as LabelConfig;
            // fix(#394) CH-02: validate the column against the layer schema —
            // a hallucinated column produced a label layer whose text-field
            // renders empty everywhere. Backend chat_actions mirrors this and
            // feeds the model an error, so this is the client-side backstop.
            const layer = layersRef.current.find((candidate) => candidate.id === layerId);
            if (
              lc.column &&
              layer?.dataset_column_info &&
              layer.dataset_column_info.length > 0 &&
              !layer.dataset_column_info.some((col) => col.name === lc.column)
            ) {
              return false;
            }
            // fix(#394) CH-02: drop an unparseable textColor (objects, junk
            // strings) instead of handing it to map.setPaintProperty — the
            // adapter then falls back to its default label color.
            const safeConfig = { ...lc };
            if (safeConfig.textColor != null && !isCssColorish(safeConfig.textColor)) {
              delete safeConfig.textColor;
            }
            onLabelChange(layerId, clampLabelConfig(safeConfig));
          } else {
            onLabelChange(layerId, null);
          }
          return true;
        }
        return false;
      case 'toggle_visibility':
        if (layerId) {
          onToggleVisibility(layerId, typeof action.visible === 'boolean' ? action.visible : undefined);
          return true;
        }
        return false;
      case 'show_query_result':
        dispatchQueryResult(action);
        return false;
      case 'add_layer': {
        const datasetId = getActionDatasetId(action);
        if (datasetId) onAddDataset(datasetId);
        // B-012: a layer-list mutation makes this turn non-replay-safe. The undo
        // snapshot keys restores on the OLD layer.id, but re-adding via
        // onAddDataset mints a NEW id, so paint/filter/label restores would
        // no-op. Suppress undo for the turn (matches the "undo only for
        // replay-safe style/filter edits" design intent). This also covers the
        // staging-accept path, which dispatches through handleChatAction.
        if (lastSnapshotRef.current) lastSnapshotRef.current.supportsUndo = false;
        return true;
      }
      case 'remove_layer':
        if (layerId) {
          onRemove(layerId);
          cleanStaleLayerRefs(mapId, layerId);
          // B-012: see add_layer above — re-adding a removed layer on undo mints
          // a new id, so the keyed restores no-op. Suppress undo for the turn.
          if (lastSnapshotRef.current) lastSnapshotRef.current.supportsUndo = false;
          return true;
        }
        return false;
      case 'set_opacity': {
        const opacity = normalizeLayerOpacity(action.opacity);
        if (layerId && opacity !== null) {
          onOpacityChange?.(layerId, opacity);
          return true;
        }
        return false;
      }
      default:
        assertNever(action.type);
    }
  }

  // Phase 1135 AI-01 / AI-09: staging buffer for destructive actions (add_layer / remove_layer).
  // `staging.push(action)` defers the action until the user accepts or rejects it.
  // NOTE: accepts route through `handleChatAction` only for the map mutation itself.
  // cleanStaleLayerRefs is called inside handleChatAction's remove_layer case (CR-02 fix).
  // The undo snapshot is captured in handleSend before push() — acceptAll/acceptOne do NOT
  // retake a snapshot; the pre-streaming snapshot serves as the undo target for the whole turn.
  // BuilderActionSource is NOT widened — Shape B invariant preserved.
  const staging = useChatActionStaging((action) => handleChatAction(action));

  /**
   * builder-audit #338 DUP-01 / COMPLEX-01: single owner of the snapshot + destructive-
   * routing + undo-downgrade loop, shared by both the streaming and non-streaming
   * fallback paths (which had drifted — the root cause of STALE-01).
   *
   * Appends each handled action to `pendingActions` (for the message bubble), routes
   * destructive add/remove into the staging buffer, dispatches everything else
   * through handleChatAction, and maintains the per-turn undo snapshot.
   *
   * builder-audit #338 STALE-01: the snapshot is (re)captured at most once per turn —
   * only when no snapshot yet exists for the turn AND there is at least one
   * undo-relevant mutating action. handleSend resets lastSnapshotRef to null at the
   * start of every turn, so a query-only turn leaves it null and the undo affordance
   * can never outlive the turn that created it.
   */
  function applyActions(actions: ChatAction[], pendingActions: ChatAction[]) {
    if (actions.length === 0) return;
    const mutatingActions = actions.filter(
      (action) => action.type !== 'show_query_result' && !isDestructiveAction(action),
    );
    if (lastSnapshotRef.current === null && mutatingActions.length > 0) {
      lastSnapshotRef.current = {
        layers: [...layersRef.current],
        supportsUndo: mutatingActions.every(isUndoSafeAction),
      };
    }
    for (const action of actions) {
      if (action.type === 'show_query_result') {
        // show_query_result: dispatch flyover path AND record in pendingActions for
        // the inline data card render (rows field handled in the message bubble).
        dispatchQueryResult(action);
        pendingActions.push(action);
        continue;
      }
      // Phase 1135 AI-01: destructive actions (add_layer / remove_layer) go into the
      // staging buffer — they do NOT dispatch immediately. The user must accept them.
      if (isDestructiveAction(action)) {
        staging.push(action);
        // Record in pendingActions so the message's actions[] captures the intent.
        pendingActions.push(action);
        // fix(#394) CH-11: do NOT downgrade undo here — a merely-STAGED action
        // hasn't touched the map, so a mixed turn's style edits stay undoable
        // and a rejected staging leaves undo intact. The downgrade happens in
        // handleChatAction's add_layer/remove_layer cases, which is exactly
        // the staging-ACCEPT dispatch path.
        continue;
      }
      // fix(#392): "Applied N changes" counts effect, not intent — only record the
      // action in pendingActions when handleChatAction reports a real mutation. (audit CH-07)
      const applied = handleChatAction(action);
      if (applied) {
        pendingActions.push(action);
        if (!isUndoSafeAction(action) && lastSnapshotRef.current) {
          lastSnapshotRef.current.supportsUndo = false;
        }
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

  /**
   * builder-audit #338 COMPLEX-01: the streaming consumer, extracted from handleSend.
   * Owns the SSE for-await loop only — token/tool progress, action application
   * (delegated to the shared applyActions), the success `done` message, and the
   * StreamModelError sentinel. Partial streamed text is exposed via the mutable
   * `streamState` holder so the caller's catch can render cancelled/interrupted
   * messages without re-deriving it.
   */
  async function consumeStream(opts: {
    userMsg: string;
    history: ChatHistoryMessage[];
    signal: AbortSignal;
    pendingActions: ChatAction[];
    streamState: { text: string };
  }) {
    const { userMsg, history, signal, pendingActions, streamState } = opts;
    for await (const { event, data } of streamChatMessage(mapId, userMsg, layers, i18n.language, history, signal)) {
      switch (event) {
        case 'token':
          streamState.text += data.text;
          setStreamingText(streamState.text);
          break;
        case 'tool_start':
          setToolProgress(typeof data.label === 'string' ? data.label : '');
          break;
        case 'tool_result':
          setToolProgress(null);
          break;
        case 'actions':
          applyActions(getChatActions(data.actions), pendingActions);
          break;
        case 'done': {
          const finalText = (typeof data.explanation === 'string' ? data.explanation : '') || streamState.text;
          // Phase 1135 AI-03: clear any existing error banner on successful response.
          setErrorBanner(null);
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
          // A pre-flight HTTPException from the SSE endpoint carries a numeric
          // `status` (e.g. 403 forbidden, 503 unavailable) — the SSE body is
          // always a 200 stream, so the status would otherwise be lost. Surface
          // it as an ApiError so the catch classifies it like the non-streaming
          // path (banner / inline, no blind retry) rather than a generic
          // retryable failure. A model-emitted error mid-stream (tool-loop
          // exhausted, deadline) has no status → StreamModelError, which shows
          // inline without re-calling the LLM via the non-streaming path.
          if (typeof data.status === 'number') {
            throw new ApiError(typeof data.message === 'string' ? data.message : '', data.status);
          }
          throw new StreamModelError(typeof data.message === 'string' ? data.message : '');
      }
    }
  }

  /**
   * builder-audit #338 COMPLEX-01: non-streaming retry path, extracted from handleSend.
   * Only reached when streaming failed before applying any actions (classifyChatError
   * → 'retry'), so re-issuing the call cannot double an already-applied LLM turn.
   */
  async function sendNonStreamingFallback(opts: {
    userMsg: string;
    history: ChatHistoryMessage[];
    pendingActions: ChatAction[];
  }) {
    const { userMsg, history, pendingActions } = opts;
    try {
      const response = await sendChatMessage(mapId, userMsg, layers, i18n.language, [...history, { role: 'user', content: userMsg }]);
      const responseActions = getChatActions(response.actions);
      applyActions(responseActions, pendingActions);
      // Phase 1135 AI-03: clear any existing error banner on non-streaming success.
      setErrorBanner(null);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.explanation,
          // fix(#392): attach the filtered pendingActions (what actually applied), not the
          // raw responseActions, so a rejected/empty fallback action can't render
          // "Applied N changes"/Undo — mirrors the streaming `done` path.
          actions: pendingActions.length > 0 ? pendingActions : undefined,
        },
      ]);
    } catch (fallbackErr) {
      // Phase 1135 AI-03: mirror streaming error classification — 403/503 → sticky banner.
      if (fallbackErr instanceof ApiError && (fallbackErr.status === 403 || fallbackErr.status === 503)) {
        setErrorBanner({
          kind: fallbackErr.status === 403 ? 'forbidden' : 'unavailable',
          retryMessage: opts.userMsg,
        });
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'error',
            content: mapApiErrorToMessage(fallbackErr),
            retryMessage: opts.userMsg,
          },
        ]);
      }
    }
  }

  async function handleSend() {
    if (!input.trim() || isLoading || inflightRef.current) return;
    // Phase 1135 AI-01: auto-reject any unflushed staging when the user sends a new message.
    if (staging.pendingActions.length > 0) staging.rejectAll();
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
    // builder-audit #338 STALE-01: clear the undo snapshot at the START of every turn so a
    // stale snapshot from a previous turn can never outlive it. A query-only turn (or
    // any turn with no undo-relevant mutating actions) leaves this null, so the Undo
    // affordance never appears under an answer that reverts an earlier, unrelated edit.
    lastSnapshotRef.current = null;
    const streamState = { text: '' };
    const pendingActions: ChatAction[] = [];
    try {
      await consumeStream({ userMsg, history, signal: controller.signal, pendingActions, streamState });
    } catch (err) {
      const outcome = classifyChatError(err, {
        aborted: controller.signal.aborted,
        hasPendingActions: pendingActions.length > 0,
      });
      switch (outcome.kind) {
        case 'aborted':
          // Aborted — show cancellation message and don't retry.
          setMessages((prev) => [
            ...prev,
            pendingActions.length > 0
              ? {
                  id: crypto.randomUUID(),
                  role: 'assistant',
                  content: streamState.text || t('chat.cancelled'),
                  actions: pendingActions,
                }
              : { id: crypto.randomUUID(), role: 'assistant', content: t('chat.cancelled') },
          ]);
          return;
        case 'partial':
          // Streaming already applied some actions before failing — keep them, no retry.
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: streamState.text || t('chat.streamInterrupted'),
              actions: pendingActions,
            },
          ]);
          break;
        case 'banner':
          // Service-level error (permission revoked / AI down) → sticky banner, no retry.
          setErrorBanner({ kind: outcome.bannerKind, retryMessage: userMsg });
          break;
        case 'inline':
          // Known auth/service error or model-emitted StreamModelError — inline bubble, no retry.
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'error',
              content: mapApiErrorToMessage(err),
              retryMessage: userMsg,
            },
          ]);
          break;
        case 'retry':
          // No actions applied yet — safe to retry via the non-streaming path.
          await sendNonStreamingFallback({ userMsg, history, pendingActions });
          break;
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
        {/* Phase 1135 AI-03: sticky service-level error banner (403 = forbidden, 503 = unavailable).
            Rendered before the message list so it stays at the top of the scroll area.
            Uses role="alert" aria-live="assertive" distinct from the message log's role="log". */}
        {errorBanner !== null && (
          <div
            role="alert"
            aria-live="assertive"
            className="flex items-start gap-2 rounded-md border border-destructive/20 bg-destructive/8 px-3 py-2 mb-2 sticky top-0 z-10"
          >
            <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground">
                {t(errorBanner.kind === 'forbidden' ? 'chat.bannerForbiddenTitle' : 'chat.bannerUnavailableTitle', {
                  defaultValue: errorBanner.kind === 'forbidden' ? 'AI access lost' : 'AI is unavailable',
                })}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {t(errorBanner.kind === 'forbidden' ? 'chat.bannerForbiddenBody' : 'chat.bannerUnavailableBody', {
                  defaultValue: errorBanner.kind === 'forbidden'
                    ? 'You no longer have permission to use AI chat. Contact your administrator to restore access.'
                    : 'The AI service is temporarily unavailable. Try again in a moment.',
                })}
              </p>
            </div>
            {errorBanner.kind === 'unavailable' ? (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs gap-1 shrink-0"
                onClick={() => {
                  const retry = errorBanner.retryMessage;
                  setErrorBanner(null);
                  setInput(retry);
                }}
              >
                <RotateCcw className="h-3 w-3" />
                {t('chat.bannerRetry', { defaultValue: 'Retry' })}
              </Button>
            ) : (
              <Button
                size="icon-xs"
                variant="ghost"
                className="shrink-0"
                onClick={() => setErrorBanner(null)}
                aria-label={t('chat.bannerDismiss', { defaultValue: 'Dismiss' })}
              >
                ×
              </Button>
            )}
          </div>
        )}
        {messages.length === 0 && (
          <div className="py-4 space-y-3">
            <p className="text-xs text-muted-foreground text-center">
              {t('chat.emptyState')}
            </p>
            <div className="flex flex-wrap gap-1.5 px-1 justify-center">
              {(layers.length === 0
                ? [t('chat.suggestions.searchDatasets')]
                : getSmartSuggestions(layers, t, viewport)
              ).map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="cursor-pointer text-xs px-2.5 py-1 rounded-md border border-border hover:bg-accent hover:border-primary/30 text-muted-foreground hover:text-foreground transition-colors"
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
                {/* Phase 1135 AI-08: inline data-analysis card for show_query_result rows */}
                {(() => {
                  // feat(#534): render the LAST query result — the sanity-check
                  // retry instruction means an earlier action in the same
                  // response may be a superseded (empty/implausible) result.
                  const queryResults = msg.actions?.filter((a) => a.type === 'show_query_result');
                  const queryResultAction = queryResults?.[queryResults.length - 1];
                  if (!queryResultAction) return null;
                  // Rows are arrays of cell values (list[list]) paired with a
                  // separate `columns` array — NOT objects keyed by name. The
                  // backend (chat_actions / chat_geojson) emits both together.
                  const rows = Array.isArray(queryResultAction.rows) ? queryResultAction.rows : null;
                  if (rows === null) return null;
                  if (rows.length === 0) {
                    return (
                      <div className="mt-2 rounded-md border border-border px-3 py-2">
                        <p className="text-sm text-muted-foreground">{t('chat.queryResult.empty')}</p>
                        <p className="text-xs text-muted-foreground mt-1">{t('chat.queryResult.emptyHint')}</p>
                      </div>
                    );
                  }
                  const allColumns = Array.isArray(queryResultAction.columns)
                    ? queryResultAction.columns
                    : [];
                  if (allColumns.length === 0) return null;
                  const visibleCount = Math.min(allColumns.length, 5);
                  const visibleColumns = allColumns.slice(0, visibleCount);
                  const hasMore = allColumns.length > 5;
                  const cellAt = (row: unknown, colIdx: number): string => {
                    const raw = Array.isArray(row) ? row[colIdx] : undefined;
                    return raw == null ? '' : String(raw);
                  };
                  return (
                    <div className="mt-2 rounded-md border border-border overflow-hidden">
                      <div className="max-h-48 overflow-y-auto" role="region" aria-label={t('chat.queryResult.tableLabel')}>
                        <table className="w-full text-sm table-fixed">
                          <thead>
                            <tr className="bg-muted/50">
                              {visibleColumns.map((col) => (
                                <th key={col} scope="col" className="px-2 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wide text-left">
                                  {col}
                                </th>
                              ))}
                              {hasMore && <th scope="col" aria-label={t('common:viewer.ai.queryResult.moreColumns')} className="px-2 py-1 text-xs font-medium text-muted-foreground">…</th>}
                            </tr>
                          </thead>
                          <tbody>
                            {rows.map((row, idx) => (
                              <tr key={idx} className="border-b border-border last:border-0 hover:bg-muted/40">
                                {visibleColumns.map((col, colIdx) => {
                                  const display = cellAt(row, colIdx);
                                  return (
                                    <td key={col} className="px-2 py-1 text-foreground max-w-[8rem] truncate" title={display}>
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
                      <p className="mt-1 mb-1 px-2 text-xs text-muted-foreground">
                        {t('chat.queryResult.rowCount', { count: queryResultAction.row_count ?? rows.length })}
                        {/* builder-audit #338 DEAD-01: surface the wire `truncated` flag so the card
                            cannot show a capped table as if it were the complete result set. */}
                        {queryResultAction.truncated && (
                          <span className="ms-1 text-muted-foreground">
                            {t('chat.queryResult.truncated', { defaultValue: '(showing a sample)' })}
                          </span>
                        )}
                      </p>
                    </div>
                  );
                })()}
                {/* builder-audit #338 Applied-N nit: a pure query-result turn mutates nothing, so it
                    must not render "Applied N changes". Count only non-query actions.
                    fix(#392): add_layer/remove_layer are staged, not yet applied, until
                    the user accepts them in the tray — exclude them too so "Applied N changes"
                    doesn't double-count intent alongside the staging tray's own pending count. (audit WR-02) */}
                {(() => {
                  const appliedActions = msg.actions?.filter(
                    (a) => a.type !== 'show_query_result' && !isDestructiveAction(a),
                  ) ?? [];
                  if (appliedActions.length === 0) return null;
                  return (
                  <div className="flex items-center gap-2 mt-1">
                    <p className="text-xs text-muted-foreground">
                      {t('chat.appliedChanges', { count: appliedActions.length })}
                    </p>
                    {/* Phase 20260526-builder-audit #338 BLD-20260526-04: undo only for replay-safe style/filter edits. */}
                    {/* Phase 1135 AI-01: undo button is suppressed while staging tray is visible (mutual exclusion). */}
                    {lastSnapshotRef.current?.supportsUndo &&
                      messages.indexOf(msg) === messages.length - 1 &&
                      msg.role === 'assistant' &&
                      staging.pendingActions.length === 0 && (
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
                  );
                })()}
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
        {/* Phase 1135 AI-01 / AI-09: staging tray — renders between last message and compose area. */}
        {staging.pendingActions.length > 0 && (
          <div
            role="region"
            aria-label={t('chat.staging.regionLabel', { defaultValue: 'Pending AI actions' })}
            className="border border-border rounded-lg bg-muted/30 p-2 space-y-1"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-muted-foreground">
                {t('chat.staging.header', { count: staging.pendingActions.length })}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="default"
                  className="h-7 text-xs"
                  onClick={() => void staging.acceptAll()}
                >
                  {t('chat.staging.acceptAll')}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs border-destructive/50 text-destructive hover:bg-destructive/10"
                  onClick={() => staging.rejectAll()}
                >
                  {t('chat.staging.rejectAll')}
                </Button>
              </div>
            </div>
            <ul
              className={cn('space-y-1', staging.pendingActions.length > 4 && 'max-h-40 overflow-y-auto')}
            >
              {staging.pendingActions.map((action, idx) => {
                const { text, fullText } = buildChipText(action, layersRef.current, t);
                const VerbIcon = action.type === 'add_layer' ? Plus : Trash2;
                return (
                  <li key={idx} className="flex items-center gap-2 rounded-md bg-background px-2 py-1">
                    <VerbIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="text-sm text-foreground truncate flex-1" title={fullText}>{text}</span>
                    <Button
                      size="sm"
                      variant="default"
                      className="h-7 text-xs"
                      onClick={() => void staging.acceptOne(idx)}
                      aria-label={`${t('chat.staging.accept')} ${fullText}`}
                    >
                      {t('chat.staging.accept')}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs border-destructive/50 text-destructive hover:bg-destructive/10"
                      onClick={() => staging.rejectOne(idx)}
                      aria-label={`${t('chat.staging.reject')} ${fullText}`}
                    >
                      {t('chat.staging.reject')}
                    </Button>
                  </li>
                );
              })}
            </ul>
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
