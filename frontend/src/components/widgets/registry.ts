import { WIDGET_TITLE_MAX_LENGTH } from './contract';
import type { AnyWidgetDefinition, WidgetInstance, WidgetSurface } from './contract';
import { barChartWidget } from './bar-chart/definition';
import { categorySelectorWidget } from './category-selector/definition';
import { histogramWidget } from './histogram/definition';
import { indicatorWidget } from './indicator/definition';
import { buttonWidget } from './button/definition';
import { imageWidget } from './image/definition';
import { markdownTextWidget } from './markdown/definition';
import { separatorWidget } from './separator/definition';

/** Every widget type this build knows. Add new types here; see README.md. */
export const widgetDefinitions: readonly AnyWidgetDefinition[] = [
  markdownTextWidget,
  imageWidget,
  buttonWidget,
  separatorWidget,
  indicatorWidget,
  barChartWidget,
  histogramWidget,
  categorySelectorWidget,
];

const byType = new Map(widgetDefinitions.map((definition) => [definition.type, definition]));

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const INSTANCE_KEYS = new Set(['id', 'type', 'v', 'title', 'config']);
// A dashboard widget summarizes one layer of the dashboard's map, unless its type is layerless.
const DASHBOARD_INSTANCE_KEYS = new Set([...INSTANCE_KEYS, 'layer_id', 'scope']);

type WidgetRejection =
  | 'malformed'
  | 'unknown_type'
  | 'unsupported_version'
  | 'invalid_config';

export type ParsedWidget =
  | { ok: true; definition: AnyWidgetDefinition; instance: WidgetInstance }
  | { ok: false; reason: WidgetRejection };

export type WidgetWriteCheck = { ok: true } | { ok: false; reason: WidgetRejection };

/** A type that exists but isn't allowed on `surface` counts as unknown there. */
export function getWidgetDefinition(
  type: string,
  surface: WidgetSurface,
): AnyWidgetDefinition | undefined {
  const definition = byType.get(type);
  return definition?.surfaces.includes(surface) ? definition : undefined;
}

/** Whether a dashboard widget of this type summarizes a layer; text doesn't. */
export function isLayerBound(type: string): boolean {
  return !byType.get(type)?.layerless;
}

/** The layer a stored or submitted dashboard widget names, if it names one. */
export function widgetLayerId(widget: object): string | undefined {
  return 'layer_id' in widget && typeof widget.layer_id === 'string' ? widget.layer_id : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Parses one instance with the server's rules: the keys are exactly `id`,
 * `type`, `v`, `title` and `config`, plus a required `layer_id` and an
 * optional `scope` on a dashboard (not for a layerless type) and a required
 * `asset_id` for a type that shows an uploaded image, and the config is the registered type's at a
 * version this build reads. Never throws: an instance it can't read comes
 * back as `ok: false` and is shown as a notice. On success the config is
 * upgraded to the definition's `v`.
 */
export function parseStoredWidget(raw: unknown, surface: WidgetSurface): ParsedWidget {
  const rawType = isRecord(raw) && typeof raw.type === 'string' ? byType.get(raw.type) : undefined;
  const bound = surface === 'dashboard' && !rawType?.layerless;
  const allowedKeys = bound ? DASHBOARD_INSTANCE_KEYS : INSTANCE_KEYS;
  const takesAsset = !!rawType?.asset;
  if (
    !isRecord(raw) ||
    !Object.keys(raw).every((key) => allowedKeys.has(key) || (takesAsset && key === 'asset_id')) ||
    typeof raw.id !== 'string' ||
    !UUID.test(raw.id) ||
    typeof raw.type !== 'string' ||
    !Number.isInteger(raw.v) ||
    (raw.title !== undefined &&
      raw.title !== null &&
      (typeof raw.title !== 'string' || [...raw.title].length > WIDGET_TITLE_MAX_LENGTH))
  ) {
    return { ok: false, reason: 'malformed' };
  }
  const definition = getWidgetDefinition(raw.type, surface);
  if (!definition) return { ok: false, reason: 'unknown_type' };
  const v = raw.v as number;
  if (v < 1 || v > definition.v) return { ok: false, reason: 'unsupported_version' };
  if (definition.asset && (typeof raw.asset_id !== 'string' || !UUID.test(raw.asset_id))) {
    return { ok: false, reason: 'malformed' };
  }
  if (
    bound &&
    (typeof raw.layer_id !== 'string' ||
      !UUID.test(raw.layer_id) ||
      (raw.scope !== undefined && raw.scope !== 'layer' && raw.scope !== 'view'))
  ) {
    return { ok: false, reason: 'malformed' };
  }
  const config = definition.parseConfig(raw.config, v);
  if (config === null) return { ok: false, reason: 'invalid_config' };
  const instance: WidgetInstance = { id: raw.id, type: raw.type, v: definition.v, config };
  if (typeof raw.title === 'string') instance.title = raw.title;
  if (definition.asset) instance.asset_id = raw.asset_id as string;
  if (bound) {
    instance.layer_id = raw.layer_id as string;
    instance.scope = raw.scope === 'view' ? 'view' : 'layer';
  }
  return { ok: true, definition, instance };
}

/**
 * The server's rule for a submitted instance, which the client mirrors before
 * saving: it must parse, or the server answers 422. The server keeps stored
 * instances it can't read out of its responses and puts them back on save, so
 * a client never has to send one.
 */
export function checkWidgetWrite(submitted: unknown, surface: WidgetSurface): WidgetWriteCheck {
  const parsed = parseStoredWidget(submitted, surface);
  return parsed.ok ? { ok: true } : { ok: false, reason: parsed.reason };
}
