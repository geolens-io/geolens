import { createContext, useContext } from 'react';
import type { SelectionValue } from './contract';

/** The colours a layer's map style gives the values of one column. */
interface LayerCategoryColors {
  column: string;
  /** The colour for a value, or undefined where the style gives it none. */
  colorOf: (key: SelectionValue) => string | undefined;
}

const LayerColorsContext = createContext<LayerCategoryColors | null>(null);

/** Gives the widgets inside it their layer's category colours. */
export const LayerColorsProvider = LayerColorsContext.Provider;

/**
 * The layer's colour for each value of `column`, or null where the chart
 * draws in theme colours: no column asked for layer colours, or the layer
 * isn't coloured by categories of this column.
 */
export function useLayerColors(column: string | null): ((key: SelectionValue) => string | undefined) | null {
  const colors = useContext(LayerColorsContext);
  return column !== null && colors?.column === column ? colors.colorOf : null;
}
