import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

/** MapLibre `locale` option: control tooltips and labels in the UI language. */
export function useMapLocale(): Record<string, string> {
  const { t } = useTranslation('common');
  return useMemo(
    () => ({
      'AttributionControl.ToggleAttribution': t('mapControls.attributionToggle'),
      'AttributionControl.MapFeedback': t('mapControls.attributionFeedback'),
      'FullscreenControl.Enter': t('mapControls.fullscreenEnter'),
      'FullscreenControl.Exit': t('mapControls.fullscreenExit'),
      'NavigationControl.ResetBearing': t('mapControls.resetBearing'),
      'NavigationControl.ZoomIn': t('mapControls.zoomIn'),
      'NavigationControl.ZoomOut': t('mapControls.zoomOut'),
      'TerrainControl.Enable': t('mapControls.terrainEnable'),
      'TerrainControl.Disable': t('mapControls.terrainDisable'),
      'Map.Title': t('mapControls.title'),
    }),
    [t],
  );
}
