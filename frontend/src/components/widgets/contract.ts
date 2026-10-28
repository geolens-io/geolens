import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

/** Where a widget type may be placed. Story blocks and dashboard widgets share one registry. */
export type WidgetSurface = 'story' | 'dashboard';

/**
 * A stored widget instance, as story blocks and dashboard widgets persist it.
 * `v` is the version of this type's config shape, starting at 1. Surfaces add
 * their own fields beside these (a dashboard widget's layer id and scope).
 */
export interface WidgetInstance<C = unknown> {
  type: string;
  v: number;
  config: C;
}

/** A stored document holding widget instances: a story or a map's `dashboard_config`. */
export interface WidgetDocument {
  /** Version of the document's own shape, independent of each instance's `v`. */
  version: number;
}

type WidgetStatistic = 'count' | 'sum' | 'mean' | 'min' | 'max';

/**
 * What a widget asks the aggregate endpoint for. The dashboard host adds the
 * dataset, the layer's filter and, for widgets that follow the map view, the
 * bbox. Draft shape: the endpoint doesn't exist yet and may tighten it.
 */
type WidgetDataRequest =
  | { op: 'count' }
  | { op: 'stats'; column: string }
  | { op: 'value_counts'; column: string; limit: number }
  | { op: 'histogram'; column: string; bins: number }
  | {
      op: 'group_by';
      column: string;
      statistic: WidgetStatistic;
      valueColumn?: string;
      limit: number;
    };

export interface WidgetRenderProps<C> {
  config: C;
  /** The aggregate result for `dataRequest`, once the host has fetched it. */
  data?: unknown;
}

export interface WidgetDefinition<C> {
  /** Stable id stored in each instance's `type`. Never rename a shipped type. */
  type: string;
  /** Newest config version this build writes and reads. */
  v: number;
  surfaces: readonly WidgetSurface[];
  /** i18n key in the `widgets` namespace naming the type in editor menus. */
  labelKey: string;
  /** Every other `widgets` key the renderer and fallback use. */
  i18nKeys: readonly string[];
  /** Config for a newly added instance. */
  defaultConfig: C;
  /**
   * Validates a stored or submitted config written at version `v` (1 to this
   * definition's `v`) and returns it at the current version, or null when it's
   * invalid. Must not throw.
   */
  parseConfig: (config: unknown, v: number) => C | null;
  dataRequest?: (config: C) => WidgetDataRequest | null;
  /** Dynamic import of the renderer, so its code and dependencies load only when shown. */
  loadRenderer: () => Promise<{ default: ComponentType<WidgetRenderProps<C>> }>;
  /**
   * Accessible text or table alternative. Rendered while the renderer loads,
   * when it fails, and wherever a host offers a text view. Loaded eagerly, so
   * keep it free of heavy dependencies.
   */
  Fallback: ComponentType<WidgetRenderProps<C>>;
}

/** A definition as the registry holds it, with its renderer wrapped in `React.lazy`. */
interface RegisteredWidget<C> extends WidgetDefinition<C> {
  Renderer: LazyExoticComponent<ComponentType<WidgetRenderProps<C>>>;
}

export type AnyWidgetDefinition = RegisteredWidget<unknown>;

/**
 * Prepares a definition for the registry. Erasing the config type lets
 * definitions of different types share one list; that's sound because the
 * registry only hands a renderer or fallback a config that the same
 * definition's `parseConfig` produced.
 */
export function defineWidget<C>(definition: WidgetDefinition<C>): AnyWidgetDefinition {
  const registered: RegisteredWidget<C> = { ...definition, Renderer: lazy(definition.loadRenderer) };
  return registered as unknown as AnyWidgetDefinition;
}
