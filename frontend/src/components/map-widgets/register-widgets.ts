import { Ruler, Layers } from 'lucide-react';
import { registerWidget } from './registry';
import { MeasurementWidget } from './builtin/MeasurementWidget';
import { LegendWidget } from './builtin/LegendWidget';

registerWidget({
  id: 'measurement',
  label: 'Measure',
  icon: Ruler,
  slot: 'top-left',
  component: MeasurementWidget,
  defaultVisible: false,
});

registerWidget({
  id: 'legend',
  label: 'Legend',
  icon: Layers,
  slot: 'bottom-left',
  component: LegendWidget,
  defaultVisible: true,
});
