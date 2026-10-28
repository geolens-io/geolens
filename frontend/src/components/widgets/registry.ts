import { WIDGET_TITLE_MAX_LENGTH } from './contract';
import type { AnyWidgetDefinition, WidgetInstance, WidgetSurface } from './contract';
import { markdownTextWidget } from './markdown/definition';

/** Every widget type this build knows. Add new types here; see README.md. */
export const widgetDefinitions: readonly AnyWidgetDefinition[] = [markdownTextWidget];

const byType = new Map(widgetDefinitions.map((definition) => [definition.type, definition]));

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const INSTANCE_KEYS = new Set(['id', 'type', 'v', 'title', 'config']);

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Parses one instance with the server's rules: the keys are exactly `id`,
 * `type`, `v`, `title` and `config`, and the config is the registered type's
 * at a version this build reads. Never throws: an instance it can't read comes
 * back as `ok: false` and is shown as a notice. On success the config is
 * upgraded to the definition's `v`.
 */
export function parseStoredWidget(raw: unknown, surface: WidgetSurface): ParsedWidget {
  if (
    !isRecord(raw) ||
    !Object.keys(raw).every((key) => INSTANCE_KEYS.has(key)) ||
    typeof raw.id !== 'string' ||
    !UUID.test(raw.id) ||
    typeof raw.type !== 'string' ||
    !Number.isInteger(raw.v) ||
    (raw.title !== undefined &&
      raw.title !== null &&
      (typeof raw.title !== 'string' || raw.title.length > WIDGET_TITLE_MAX_LENGTH))
  ) {
    return { ok: false, reason: 'malformed' };
  }
  const definition = getWidgetDefinition(raw.type, surface);
  if (!definition) return { ok: false, reason: 'unknown_type' };
  const v = raw.v as number;
  if (v < 1 || v > definition.v) return { ok: false, reason: 'unsupported_version' };
  const config = definition.parseConfig(raw.config, v);
  if (config === null) return { ok: false, reason: 'invalid_config' };
  const instance: WidgetInstance = { id: raw.id, type: raw.type, v: definition.v, config };
  if (typeof raw.title === 'string') instance.title = raw.title;
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
