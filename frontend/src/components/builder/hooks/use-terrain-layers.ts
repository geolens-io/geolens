import { useCallback } from 'react';
import { normalizeTerrainExaggeration } from '@/components/builder/map-sync';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';

// STATE-02: terrain bind/unbind/exaggeration cluster, relocated verbatim out of
// the useBuilderLayers god-hook. PURE RELOCATION — handler bodies are unchanged;
// shared state (layersRef + terrain config setters) is threaded in as params.
interface UseTerrainLayersParams {
  layersRef: React.RefObject<MapLayerResponse[]>;
  localTerrainConfig: MapTerrainConfig | null;
  setLocalTerrainConfig: React.Dispatch<React.SetStateAction<MapTerrainConfig | null>>;
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>;
}

export function useTerrainLayers({
  layersRef,
  localTerrainConfig,
  setLocalTerrainConfig,
  setHasUnsavedChanges,
}: UseTerrainLayersParams) {
  const handleDEMTerrainBind = useCallback((layerId: string) => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;
    setLocalTerrainConfig((prev) => ({
      enabled: true,
      source_dataset_id: layer.dataset_id,
      exaggeration: normalizeTerrainExaggeration(prev?.exaggeration),
    }));
    setHasUnsavedChanges(true);
  }, [layersRef, setLocalTerrainConfig, setHasUnsavedChanges]);

  const handleDEMTerrainUnbind = useCallback((layerId: string) => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;
    if (!localTerrainConfig || localTerrainConfig.source_dataset_id !== layer.dataset_id) return;
    setLocalTerrainConfig({
      enabled: false,
      source_dataset_id: null,
      exaggeration: normalizeTerrainExaggeration(localTerrainConfig.exaggeration),
    });
    setHasUnsavedChanges(true);
  }, [layersRef, localTerrainConfig, setLocalTerrainConfig, setHasUnsavedChanges]);

  const handleDEMTerrainExaggerationChange = useCallback((layerId: string, value: number) => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;
    setLocalTerrainConfig(() => ({
      enabled: true,
      source_dataset_id: layer.dataset_id,
      exaggeration: normalizeTerrainExaggeration(value),
    }));
    setHasUnsavedChanges(true);
  }, [layersRef, setLocalTerrainConfig, setHasUnsavedChanges]);

  return {
    handleDEMTerrainBind,
    handleDEMTerrainUnbind,
    handleDEMTerrainExaggerationChange,
  };
}
