import { useEffect, useRef } from 'react';
import { useNavigate, useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useUpdateMap, useDuplicateMap } from '@/hooks/use-maps';
import { uploadThumbnail } from '@/api/maps';
import type { MapLayerResponse } from '@/types/api';

/** Capture a 400x250 JPEG thumbnail from the map canvas and upload it. */
function captureThumbnail(map: MaplibreMap, mapId: string, queryClient: ReturnType<typeof useQueryClient>) {
  map.triggerRepaint();
  map.once('idle', () => {
    try {
      const srcCanvas = map.getCanvas();
      const thumbW = 400;
      const thumbH = 250;
      const targetRatio = thumbW / thumbH;
      const srcW = srcCanvas.width;
      const srcH = srcCanvas.height;
      const srcRatio = srcW / srcH;

      let cropX = 0, cropY = 0, cropW = srcW, cropH = srcH;
      if (srcRatio > targetRatio) {
        cropW = Math.round(srcH * targetRatio);
        cropX = Math.round((srcW - cropW) / 2);
      } else {
        cropH = Math.round(srcW / targetRatio);
        cropY = Math.round((srcH - cropH) / 2);
      }

      const offscreen = document.createElement('canvas');
      offscreen.width = thumbW;
      offscreen.height = thumbH;
      const ctx = offscreen.getContext('2d');
      if (ctx) {
        ctx.drawImage(srcCanvas, cropX, cropY, cropW, cropH, 0, 0, thumbW, thumbH);
        const dataUri = offscreen.toDataURL('image/jpeg', 0.7);
        uploadThumbnail(mapId, dataUri).then(() => {
          queryClient.invalidateQueries({ queryKey: ['maps'] });
        }).catch(() => {
          // Silent failure for thumbnails
        });
      }
    } catch {
      // Silent failure for thumbnails
    }
  });
}

interface SaveState {
  mapId: string | undefined;
  localLayers: MapLayerResponse[];
  localBasemap: string;
  localName: string;
  localDescription: string;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  setHasUnsavedChanges: (v: boolean) => void;
  hasUnsavedChanges: boolean;
  hasThumbnail?: boolean;
}

export function useBuilderSave(state: SaveState) {
  const { t } = useTranslation('builder');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const updateMap = useUpdateMap();
  const duplicateMutation = useDuplicateMap();

  function handleSave() {
    const { mapId: id, mapInstanceRef, localName, localDescription, localBasemap, localLayers } = state;
    if (!id) return;
    const map = mapInstanceRef.current;
    const center = map?.getCenter();
    const zoom = map?.getZoom();
    const bearing = map?.getBearing();
    const pitch = map?.getPitch();

    updateMap.mutate(
      {
        id,
        data: {
          name: localName || undefined,
          description: localDescription.trim() || null,
          basemap_style: localBasemap,
          center_lng: center?.lng ?? null,
          center_lat: center?.lat ?? null,
          zoom: zoom ?? null,
          bearing: bearing ?? 0,
          pitch: pitch ?? 0,
          layers: localLayers.map((l) => ({
            dataset_id: l.dataset_id,
            sort_order: l.sort_order,
            visible: l.visible,
            opacity: l.opacity,
            paint: l.paint,
            layout: l.layout,
            display_name: l.display_name ?? null,
            filter: l.filter ?? null,
            label_config: l.label_config ?? null,
            style_config: l.style_config ?? null,
            layer_type: l.layer_type ?? null,
          })),
        },
      },
      {
        onSuccess: () => {
          toast.success(t('toasts.mapSaved'));
          state.setHasUnsavedChanges(false);

          // Capture thumbnail and upload (fire-and-forget)
          const m = mapInstanceRef.current;
          if (m && id) {
            captureThumbnail(m, id, queryClient);
          }
        },
        onError: () => {
          toast.error(t('toasts.saveFailed'));
        },
      },
    );
  }

  function handleExportPNG() {
    const map = state.mapInstanceRef.current;
    if (!map) return;
    map.triggerRepaint();
    map.once('idle', () => {
      const canvas = map.getCanvas();
      canvas.toBlob((blob) => {
        if (!blob) {
          toast.error(t('toasts.exportFailed'));
          return;
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${state.localName || 'map'}-export.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast.success(t('toasts.exportSuccess'));
      }, 'image/png');
    });
  }

  async function handleFork() {
    if (!state.mapId) return;
    try {
      const result = await duplicateMutation.mutateAsync(state.mapId);
      if (result.excluded_layer_count > 0) {
        toast.warning(
          t('toasts.mapForkedExcluded', { count: result.excluded_layer_count }),
        );
      } else {
        toast.success(t('toasts.mapDuplicated'));
      }
      navigate(`/maps/${result.id}`);
    } catch {
      toast.error(t('toasts.mapDuplicateFailed'));
    }
  }

  // Auto-capture thumbnail on first map load if none exists
  const thumbCaptured = useRef(false);
  useEffect(() => {
    if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;
    const m = state.mapInstanceRef.current;
    if (!m) return;
    const id = state.mapId;
    function onIdle() {
      if (thumbCaptured.current) return;
      thumbCaptured.current = true;
      captureThumbnail(m!, id, queryClient);
    }
    if (m.loaded()) {
      onIdle();
    } else {
      m.once('idle', onIdle);
      return () => { m.off('idle', onIdle); };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.mapId, state.hasThumbnail]);

  // Warn before tab close / refresh with unsaved changes
  useEffect(() => {
    if (!state.hasUnsavedChanges) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [state.hasUnsavedChanges]);

  // Block in-app navigation with unsaved changes
  const blocker = useBlocker(state.hasUnsavedChanges);

  // Keyboard shortcut: Ctrl/Cmd+S
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.mapId, state.localLayers, state.localBasemap, state.localName]);

  return {
    handleSave,
    handleExportPNG,
    handleFork,
    isSaving: updateMap.isPending,
    isForkPending: duplicateMutation.isPending,
    blocker,
  };
}
