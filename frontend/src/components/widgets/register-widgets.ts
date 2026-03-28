import { LayoutGrid } from 'lucide-react';
import { registerWidget } from './registry';
import { PlaceholderWidget } from './builtin/PlaceholderWidget';

registerWidget({
  id: 'placeholder',
  label: 'Widget Demo',
  icon: LayoutGrid,
  slot: 'top-left',
  component: PlaceholderWidget,
  defaultVisible: true,
});
