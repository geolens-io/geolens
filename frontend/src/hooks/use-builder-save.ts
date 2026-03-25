import { useEffect, useRef } from 'react';
import { useNavigate, useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useUpdateMap, useDuplicateMap } from '@/hooks/use-maps';
import { uploadThumbnail } from '@/api/maps';
import type { MapLayerResponse } from '@/types/api';

/** Crop and resize the map canvas to a 400x250 JPEG, then upload it. */
function doCapture(map: MaplibreMap, mapId: string, queryClient: ReturnType<typeof useQueryClient>) {
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
  } catch (err) {
    console.warn('[thumbnail] capture failed:', err);
  }
}

/** Capture a 400x250 JPEG thumbnail from the map canvas and upload it.
 *  If the map is already idle/loaded, captures immediately (preserveDrawingBuffer
 *  guarantees canvas contents persist). Otherwise waits for the idle event with a
 *  3-second safety timeout to prevent silent drops. */
function captureThumbnail(map: MaplibreMap, mapId: string, queryClient: ReturnType<typeof useQueryClient>) {
  if (map.loaded()) {
    doCapture(map, mapId, queryClient);
  } else {
    let captured = false;
    const onIdle = () => {
      if (captured) return;
      captured = true;
      clearTimeout(timer);
      doCapture(map, mapId, queryClient);
    };
    map.once('idle', onIdle);
    const timer = setTimeout(() => {
      if (!captured) {
        captured = true;
        map.off('idle', onIdle);
        doCapture(map, mapId, queryClient);
      }
    }, 3000);
  }
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
            show_in_legend: l.show_in_legend ?? true,
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

    const doExport = () => {
      try {
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
      } catch {
        toast.error(t('toasts.exportFailed'));
      }
    };

    if (map.loaded()) {
      doExport();
    } else {
      let exported = false;
      const onIdle = () => {
        if (exported) return;
        exported = true;
        clearTimeout(timer);
        doExport();
      };
      map.once('idle', onIdle);
      const timer = setTimeout(() => {
        if (!exported) {
          exported = true;
          map.off('idle', onIdle);
          doExport();
        }
      }, 3000);
    }
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

  // Auto-capture thumbnail on first map load if none exists.
  // Called from handleMapRef when the map instance becomes available.
  const thumbCaptured = useRef(false);
  function maybeAutoCaptureThumbnail(map: MaplibreMap) {
    if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;
    thumbCaptured.current = true;
    captureThumbnail(map, state.mapId, queryClient);
  }

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
    maybeAutoCaptureThumbnail,
    isSaving: updateMap.isPending,
    isForkPending: duplicateMutation.isPending,
    blocker,
  };
}
