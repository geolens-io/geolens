import { Ruler, Layers } from 'lucide-react';
import { registerWidget } from './registry';
import { MeasurementWidget } from './builtin/MeasurementWidget';
import { LegendWidget } from './builtin/LegendWidget';

registerWidget({
  id: 'measurement',
  labelKey: 'widgets.measurement.label',
  icon: Ruler,
  slot: 'top-left',
  component: MeasurementWidget,
  defaultVisible: false,
});

registerWidget({
  id: 'legend',
  labelKey: 'widgets.legend.label',
  icon: Layers,
  slot: 'bottom-left',
  component: LegendWidget,
  defaultVisible: true,
});
