import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { TFunction } from 'i18next';
import type { AggregateRequest } from '@/api/aggregate';

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
  /** The uploaded image a story image block shows. */
  asset_id?: string;
  config: C;
}

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/**
 * What a widget asks the aggregate endpoint for: its request body without the
 * `filter` and `bbox`, which the dashboard host adds from the layer and the
 * map view.
 */
type WidgetDataRequest = DistributiveOmit<AggregateRequest, 'filter' | 'bbox'>;

/** A value of a column; null stands for rows with no value. */
export type SelectionValue = string | number | boolean | null;

/**
 * What a reader picked on a dashboard widget: the rows whose `column` holds
 * one of `values`, or lies in `range`. A range includes its lower bound, and
 * its upper bound only when `includeUpper`, as the last bin of a histogram
 * does. `label` is the pick as the widget shows it, for the filter chip.
 */
export type WidgetSelection = { column: string; label: string } & (
  | { values: readonly SelectionValue[] }
  | { range: { lower: number; upper: number; includeUpper: boolean } }
);

export interface WidgetRenderProps<C> {
  config: C;
  /** The aggregate result for `dataRequest`, once the host has fetched it. */
  data?: unknown;
  /** The reader's current pick on this widget. Its data still covers every value, so the pick shows in context. */
  selection?: WidgetSelection | null;
  /**
   * Set where the host links widgets: a pick filters the widget's layer on
   * the map and the other widgets on it, and null clears it. Without it the
   * widget is read-only.
   */
  onSelect?: (selection: WidgetSelection | null) => void;
  /** The columns of the widget's layer, where the host has them. */
  columns?: readonly WidgetColumn[];
  /** Where the host serves the image the instance names in `asset_id`. */
  assetPath?: string;
}

/** A column of the layer a dashboard widget summarizes. */
export interface WidgetColumn {
  name: string;
  type: string;
  /** Up to ten distinct values, sampled when the dataset was loaded, where the host has them. */
  samples?: readonly unknown[];
}

/** A column a config reads; a `numeric` one must hold numbers. */
interface WidgetColumnUse {
  name: string;
  numeric: boolean;
}

export interface WidgetEditorProps<C> {
  config: C;
  onChange: (config: C) => void;
  /** The layer's columns, for the editor's pickers. */
  columns: readonly WidgetColumn[];
  /** Unique per instance, for the editor's field ids. */
  idPrefix: string;
}

export interface WidgetDefinition<C> {
  /** Stable id stored in each instance's `type`. Never rename a shipped type. */
  type: string;
  /** Newest config version this build writes and reads. */
  v: number;
  surfaces: readonly WidgetSurface[];
  /** Each instance names an image uploaded to its host in `asset_id`. */
  asset?: true;
  /** i18n key in the `widgets` namespace naming the type in editor menus. */
  labelKey: string;
  /** Every other `widgets` key the renderer and fallback use. */
  i18nKeys: readonly string[];
  /** Config for a newly added instance. */
  defaultConfig: C;
  /** Changes to `defaultConfig` for an instance added to a layer with these columns, such as which column to read. */
  initialConfig?: (columns: readonly WidgetColumn[]) => Partial<C>;
  /**
   * Validates a stored or submitted config written at version `v` (1 to this
   * definition's `v`) and returns it at the current version, or null when it's
   * invalid. Must not throw.
   */
  parseConfig: (config: unknown, v: number) => C | null;
  dataRequest?: (config: C) => WidgetDataRequest | null;
  /**
   * What an untitled instance is called, from its config. `columnLabel` gives a
   * column's display label. Display only; a type without it has no derived heading.
   */
  heading?: (config: C, t: TFunction<'widgets'>, columnLabel: (column: string) => string) => string;
  /** The column a reader's pick on this widget filters; a type without it takes no picks. */
  picksColumn?: (config: C) => string;
  /** The columns `config` reads, so an editor can check them against the layer before saving. */
  readsColumns?: (config: C) => readonly WidgetColumnUse[];
  /** Dynamic import of the config editor, for hosts that edit this type. */
  loadEditor?: () => Promise<{ default: ComponentType<WidgetEditorProps<C>> }>;
  /** Dynamic import of the renderer, so its code and dependencies load only when shown. */
  loadRenderer: () => Promise<{ default: ComponentType<WidgetRenderProps<C>> }>;
  /**
   * Accessible text or table alternative. Rendered while the renderer loads,
   * when it fails, and wherever a host offers a text view. Loaded eagerly, so
   * keep it free of heavy dependencies.
   */
  Fallback: ComponentType<WidgetRenderProps<C>>;
}

/** A definition as the registry holds it, with its renderer and editor wrapped in `React.lazy`. */
interface RegisteredWidget<C> extends WidgetDefinition<C> {
  Renderer: LazyExoticComponent<ComponentType<WidgetRenderProps<C>>>;
  Editor?: LazyExoticComponent<ComponentType<WidgetEditorProps<C>>>;
}

export type AnyWidgetDefinition = RegisteredWidget<unknown>;

/**
 * Prepares a definition for the registry. Erasing the config type lets
 * definitions of different types share one list; that's sound because the
 * registry only hands a renderer or fallback a config that the same
 * definition's `parseConfig` produced.
 */
export function defineWidget<C>(definition: WidgetDefinition<C>): AnyWidgetDefinition {
  const registered: RegisteredWidget<C> = {
    ...definition,
    Renderer: lazy(definition.loadRenderer),
    ...(definition.loadEditor ? { Editor: lazy(definition.loadEditor) } : {}),
  };
  return registered as unknown as AnyWidgetDefinition;
}
