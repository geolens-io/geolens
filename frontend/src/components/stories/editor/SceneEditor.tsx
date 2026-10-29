import { memo, useEffect, useId, useRef, useState } from 'react';
import { Crosshair, ExternalLink } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { savedMapCamera } from '@/components/builder/builder-camera';
import { mapDetailQuery, useMap } from '@/hooks/use-maps';
import { formatMutationError } from '@/lib/error-map';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import { queryKeys } from '@/lib/query-keys';
import type { StoryCamera, StoryScene } from '@/types/api';
import { toStoryCamera } from '../story-scenes';
import { MapPicker } from './MapPicker';
import type { DraftEdit } from './story-draft';

const WORLD_VIEW: StoryCamera = { center: [0, 0], zoom: 2, bearing: 0, pitch: 0 };

interface SceneEditorProps {
  chapterId: string;
  scene: StoryScene | null;
  /** The chapter has a scene on a map the editor can't open. */
  sceneHidden: boolean;
  edit: (change: DraftEdit) => void;
  /** The map pane's current view, or null while no map is ready. */
  readView: () => StoryCamera | null;
  /** The scene's map wasn't found when the draft was last saved. */
  mapMissing: boolean;
}

/**
 * Picks the chapter's map, captures its camera from the map pane, and sets
 * which layers it shows. Memoized on the scene, so typing chapter text
 * doesn't re-render the layer list or the map picker.
 */
export const SceneEditor = memo(function SceneEditor({
  chapterId,
  scene,
  sceneHidden,
  edit,
  readView,
  mapMissing,
}: SceneEditorProps) {
  const { t } = useTranslation('stories');
  const qc = useQueryClient();
  const layerIdPrefix = useId();
  const [loadingMap, setLoadingMap] = useState(false);
  const { data: sceneMap } = useMap(scene?.map_id);
  const latestChoice = useRef(0);
  // A choice still loading when this editor goes away (another chapter, a
  // deleted one, a replaced draft) has nowhere to land.
  useEffect(() => () => void (latestChoice.current += 1), []);

  // The Builder opens in another tab; reload the scene's map once on return,
  // so layers added there show up here.
  const builderTripMapId = useRef<string | null>(null);
  useEffect(() => {
    function onVisible() {
      const mapId = builderTripMapId.current;
      if (document.visibilityState !== 'visible' || !mapId) return;
      builderTripMapId.current = null;
      void qc.invalidateQueries({ queryKey: queryKeys.maps.detail(mapId) });
    }
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [qc]);

  async function chooseMap(mapId: string | null) {
    const choice = ++latestChoice.current;
    if (mapId === null) {
      edit({ type: 'clearScene', chapterId });
      return;
    }
    setLoadingMap(true);
    try {
      const map = await qc.fetchQuery(mapDetailQuery(mapId));
      if (choice !== latestChoice.current) return;
      edit({
        type: 'setMap',
        chapterId,
        mapId,
        // Rounded like a captured view, so both store the same precision.
        camera: toStoryCamera(savedMapCamera(map)) ?? WORLD_VIEW,
      });
    } catch (err) {
      if (choice === latestChoice.current) {
        toast.error(formatMutationError('stories:editor.scene.mapLoadFailed', err));
      }
    } finally {
      if (choice === latestChoice.current) setLoadingMap(false);
    }
  }

  function captureView() {
    const camera = readView();
    if (!camera) {
      toast.error(t('editor.scene.mapNotReady'));
      return;
    }
    edit({ type: 'setCamera', chapterId, camera });
    toast.success(t('editor.scene.viewCaptured'));
  }

  const removeScene = (
    <Button type="button" variant="outline" size="sm" onClick={() => edit({ type: 'clearScene', chapterId })}>
      {t('editor.scene.remove')}
    </Button>
  );

  if (sceneHidden) {
    return (
      <div className="space-y-2 rounded-md border border-dashed p-3">
        <p className="text-sm text-muted-foreground">{t('editor.scene.hidden')}</p>
        {removeScene}
      </div>
    );
  }

  // Folder rows group layers in the Builder; each member layer has its own toggle.
  const layers = (sceneMap?.layers ?? []).filter((layer) => !isFolderGroupLayer(layer));

  return (
    <div className="space-y-3">
      {mapMissing && (
        <div role="alert" className="space-y-2 rounded-md border border-destructive/40 p-3">
          <p className="text-sm">{t('editor.scene.mapMissing')}</p>
          {removeScene}
        </div>
      )}
      <MapPicker
        currentName={scene ? (sceneMap?.name ?? t('editor.scene.currentMap')) : null}
        disabled={loadingMap}
        onChoose={(mapId) => void chooseMap(mapId)}
      />

      {scene && (
        <>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={captureView}>
              <Crosshair className="h-4 w-4" aria-hidden="true" />
              {t('editor.scene.useCurrentView')}
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link
                to={`/maps/${scene.map_id}`}
                target="_blank"
                rel="noopener"
                onClick={() => {
                  builderTripMapId.current = scene.map_id;
                }}
              >
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                {t('editor.scene.editInBuilder')}
                <span className="sr-only">{t('editor.scene.opensInNewTab')}</span>
              </Link>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t('editor.scene.useCurrentViewHint')}</p>
          {layers.length > 0 && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t('editor.scene.layers')}</legend>
              {layers.map((layer) => {
                const checked = scene.layer_visibility?.[layer.id] ?? layer.visible;
                const checkboxId = `${layerIdPrefix}-${layer.id}`;
                return (
                  <div key={layer.id} className="flex items-center gap-2">
                    <Checkbox
                      id={checkboxId}
                      checked={checked}
                      onCheckedChange={(value) =>
                        edit({
                          type: 'setLayerVisible',
                          chapterId,
                          layerId: layer.id,
                          visible: value === true,
                        })
                      }
                    />
                    <Label htmlFor={checkboxId} className="font-normal">
                      {layer.display_name || layer.dataset_name}
                    </Label>
                  </div>
                );
              })}
            </fieldset>
          )}
        </>
      )}
    </div>
  );
});
