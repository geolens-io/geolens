import type { WidgetRenderProps } from '../contract';
import { StatTable } from './StatTable';
import type { TableConfig } from './definition';

/** The same table, read-only: a fallback takes no picks. */
export function TableFallback(props: WidgetRenderProps<TableConfig>) {
  return <StatTable {...props} onSelect={undefined} coded />;
}
