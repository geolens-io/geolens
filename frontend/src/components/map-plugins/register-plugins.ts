import { Ruler, Layers } from 'lucide-react';
import { registerPlugin } from './registry';
import { MeasurementPlugin } from './builtin/MeasurementPlugin';
import { LegendPlugin } from './builtin/LegendPlugin';

registerPlugin({
  id: 'measurement',
  labelKey: 'plugins.measurement.label',
  icon: Ruler,
  placement: { mode: 'floating', anchor: 'top-left' },
  component: MeasurementPlugin,
  defaultVisible: false,
});

registerPlugin({
  id: 'legend',
  labelKey: 'plugins.legend.label',
  icon: Layers,
  placement: { mode: 'floating', anchor: 'bottom-left' },
  component: LegendPlugin,
  defaultVisible: true,
});
