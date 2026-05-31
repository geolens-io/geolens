import { registerPlugin } from './registry';
import { MeasurementPlugin } from './builtin/MeasurementPlugin';
import { LegendPlugin } from './builtin/LegendPlugin';

/**
 * Register built-in plugins. Side-effect module imported once by index.ts.
 */
registerPlugin({
  id: 'measurement',
  anchor: 'top-left',
  placement: 'panel',
  component: MeasurementPlugin,
});

registerPlugin({
  id: 'legend',
  anchor: 'top-right',
  placement: 'inline',
  component: LegendPlugin,
});
