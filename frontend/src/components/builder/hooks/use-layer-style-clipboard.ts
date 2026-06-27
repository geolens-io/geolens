import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import {
  extractCopyableStyle,
  isStyleCompatible,
  applyCopiedStyleToLayer,
  type CopiedStyle,
  type GeometryStyleClass,
} from '@/lib/builder/layer-style-clipboard';

type StyleConfigChangeHandler = (
  layerId: string,
  config: StyleConfig | null,
  paint: Record<string, unknown>,
) => void;

// STATE-02: per-row style clipboard (copy / paste) cluster, relocated verbatim
// out of the useBuilderLayers god-hook. PURE RELOCATION — handler bodies are
// unchanged. The hook OWNS the session clipboard ref + geometry-class mirror and
// exposes copiedStyleRef so the bulk apply-style handler can read the same
// snapshot.
interface UseLayerStyleClipboardParams {
  layersRef: React.RefObject<MapLayerResponse[]>;
  handleStyleConfigChange: StyleConfigChangeHandler;
}

export function useLayerStyleClipboard({
  layersRef,
  handleStyleConfigChange,
}: UseLayerStyleClipboardParams) {
  const { t } = useTranslation('builder');

  // ENH-02/ENH-03 (Phase 1201-01): session-local style clipboard. The ref holds
  // the last-copied geometry-compatible style snapshot; the state mirror exposes
  // its geometry class so the kebab "Paste style" item can enable/disable per-row
  // without invalidating the stable copy/paste callbacks on every copy.
  const copiedStyleRef = useRef<CopiedStyle | null>(null);
  const [copiedStyleGeometryClass, setCopiedStyleGeometryClass] = useState<GeometryStyleClass | null>(null);

  // ENH-02 (Phase 1201-01): copy a layer's geometry-compatible style into the
  // session clipboard. Pure extraction via the clipboard helper; the geometry
  // class is mirrored into state so the UI can enable "Paste style" per-row.
  const handleCopyStyle = useCallback((layerId: string) => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;
    const copied = extractCopyableStyle(layer);
    copiedStyleRef.current = copied;
    setCopiedStyleGeometryClass(copied.geometryClass);
    toast.success(t('toasts.styleCopied'));
  }, [layersRef, t]);

  // ENH-02 (Phase 1201-01): paste the clipboard style onto a geometry-compatible
  // target. Routes through handleStyleConfigChange — the SAME atomic
  // single-setLocalLayers write path used for every style mutation — so paint +
  // style_config land in ONE render (never field-by-field, per the
  // applyLayerUpdate-stale-ref-clobber rule) and the live map repaints.
  const handlePasteStyle = useCallback((layerId: string) => {
    const copied = copiedStyleRef.current;
    if (!copied) return;
    const target = layersRef.current.find((l) => l.id === layerId);
    if (!target || !isStyleCompatible(copied, target)) return;
    const merged = applyCopiedStyleToLayer(target, copied);
    handleStyleConfigChange(layerId, merged.style_config ?? null, merged.paint);
    toast.success(t('toasts.stylePasted'));
  }, [layersRef, handleStyleConfigChange, t]);

  return {
    copiedStyleRef,
    copiedStyleGeometryClass,
    handleCopyStyle,
    handlePasteStyle,
  };
}
