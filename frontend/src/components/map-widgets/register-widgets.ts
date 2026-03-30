import { Ruler, Layers, Map } from 'lucide-react';
import { registerWidget } from './registry';
import { MeasurementWidget } from './builtin/MeasurementWidget';
import { LegendWidget } from './builtin/LegendWidget';
import { BasemapWidget } from './builtin/BasemapWidget';

registerWidget({
  id: 'measurement',
  labelKey: 'widgets.measurement.label',
  icon: Ruler,
  placement: { mode: 'floating', anchor: 'top-left' },
  component: MeasurementWidget,
  defaultVisible: false,
});

registerWidget({
  id: 'legend',
  labelKey: 'widgets.legend.label',
  icon: Layers,
  placement: { mode: 'floating', anchor: 'bottom-left' },
  component: LegendWidget,
  defaultVisible: true,
});

registerWidget({
  id: 'basemap',
  labelKey: 'widgets.basemap.label',
  icon: Map,
  placement: { mode: 'sidebar' },
  component: BasemapWidget,
  defaultVisible: true,
});
