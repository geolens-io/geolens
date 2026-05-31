import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { usePluginStore } from '@/stores/map-plugin-store';
import type { PluginContext } from '../types';

const MEASURE_LINE_LAYER = 'measure-line';
const MEASURE_POINTS_LAYER = 'measure-points';

export function MeasurementPlugin({ context }: { context: PluginContext }) {
  const { t } = useTranslation('builder');
  // close the measurement plugin via the store
  const close = () => usePluginStore.getState().close('measurement');
  useEffect(() => {
    // layer ids: MEASURE_LINE_LAYER / MEASURE_POINTS_LAYER
    return () => {
      void MEASURE_LINE_LAYER;
      void MEASURE_POINTS_LAYER;
    };
  }, []);
  return (
    <div data-testid="measurement-plugin">
      <button onClick={close}>{t('widgets.measurement.label')}</button>
      <span>{MEASURE_LINE_LAYER}</span>
      <span>{MEASURE_POINTS_LAYER}</span>
    </div>
  );
}
