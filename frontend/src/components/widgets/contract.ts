import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { components } from '@/types/api.generated';

/** Where a widget type may be placed. Story blocks and dashboard widgets share one registry. */
export type WidgetSurface = 'story' | 'dashboard';

/** Longest `title` the server accepts. */
export const WIDGET_TITLE_MAX_LENGTH = 120;

/**
 * A widget instance as the server stores and returns it (`widgets/schemas.py`).
 * `id` is made by the client and stays the same across saves. `v` is the
 * version of this type's config shape, starting at 1. Dashboard widgets also
 * name the map layer they summarize, and whether they cover the whole layer
 * or only the map view.
 */
export interface WidgetInstance<C = unknown> {
  id: string;
  type: string;
  v: number;
  title?: string;
  layer_id?: string;
  scope?: 'layer' | 'view';
  config: C;
}

type AggregateRequest =
  | components['schemas']['CountRequest']
  | components['schemas']['StatsRequest']
  | components['schemas']['ValueCountsRequest']
  | components['schemas']['HistogramRequest']
  | components['schemas']['GroupByRequest'];

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/**
 * What a widget asks the aggregate endpoint for: its request body without the
 * `filter` and `bbox`, which the dashboard host adds from the layer and the
 * map view.
 */
type WidgetDataRequest = DistributiveOmit<AggregateRequest, 'filter' | 'bbox'>;

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
