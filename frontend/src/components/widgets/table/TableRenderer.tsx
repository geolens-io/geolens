import type { WidgetRenderProps } from '../contract';
import { StatTable } from './StatTable';
import type { TableConfig } from './definition';

export default function TableRenderer(props: WidgetRenderProps<TableConfig>) {
  return <StatTable {...props} />;
}
