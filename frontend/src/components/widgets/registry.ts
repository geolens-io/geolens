import type { AnyWidgetDefinition, WidgetInstance, WidgetSurface } from './contract';
import { markdownTextWidget } from './markdown/definition';

/** Every widget type this build knows. Add new types here; see README.md. */
export const widgetDefinitions: readonly AnyWidgetDefinition[] = [markdownTextWidget];

const byType = new Map(widgetDefinitions.map((definition) => [definition.type, definition]));

type WidgetRejection =
  | 'malformed'
  | 'unknown_type'
  | 'unsupported_version'
  | 'invalid_config';

export type ParsedWidget =
  | { ok: true; definition: AnyWidgetDefinition; instance: WidgetInstance }
  | { ok: false; reason: WidgetRejection; raw: unknown };

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
 * Parses one stored instance. Never throws: an instance this build can't read
 * (a newer type or `v`, a broken config) comes back as `ok: false` with `raw`
 * untouched, so the document keeps it. On success the config is upgraded to
 * the definition's `v`, and fields other than `type`, `v` and `config` pass
 * through.
 */
export function parseStoredWidget(raw: unknown, surface: WidgetSurface): ParsedWidget {
  if (!isRecord(raw) || typeof raw.type !== 'string' || !Number.isInteger(raw.v)) {
    return { ok: false, reason: 'malformed', raw };
  }
  const definition = getWidgetDefinition(raw.type, surface);
  if (!definition) return { ok: false, reason: 'unknown_type', raw };
  const v = raw.v as number;
  if (v < 1 || v > definition.v) return { ok: false, reason: 'unsupported_version', raw };
  const config = definition.parseConfig(raw.config, v);
  if (config === null) return { ok: false, reason: 'invalid_config', raw };
  return { ok: true, definition, instance: { ...raw, type: raw.type, v: definition.v, config } };
}

/** The value to write back for a parsed instance: the upgraded instance, or the untouched original. */
export function serializeWidget(parsed: ParsedWidget): unknown {
  return parsed.ok ? parsed.instance : parsed.raw;
}

function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((item, i) => sameJson(item, b[i]))
    );
  }
  if (!isRecord(a) || !isRecord(b)) return false;
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every((key) => Object.hasOwn(b, key) && sameJson(a[key], b[key]))
  );
}

/**
 * The server's rule for a submitted instance, which the client mirrors before
 * saving: it must parse, unless it's identical to one already in the stored
 * document (`stored`). That exception lets a whole-document save carry back
 * instances this build can't read, while a client can't introduce one. The
 * server answers 422 for a refused instance.
 */
export function checkWidgetWrite(
  submitted: unknown,
  surface: WidgetSurface,
  stored: readonly unknown[] = [],
): WidgetWriteCheck {
  const parsed = parseStoredWidget(submitted, surface);
  if (parsed.ok || stored.some((instance) => sameJson(instance, submitted))) return { ok: true };
  return { ok: false, reason: parsed.reason };
}
