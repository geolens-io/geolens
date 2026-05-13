import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { DatasetSearchPanel } from '@/components/builder/DatasetSearchPanel';
import { ShareDialog } from '@/components/builder/SharePanel';
import { VisibilityIcon } from '@/components/maps/VisibilityIcon';
import { formatRelativeDate } from '@/lib/format';
import { getVisibilityLabel } from '@/i18n/labels';
import type { MapBasemapConfig, MapLayerResponse, MapResponse } from '@/types/api';

interface BuilderDialogsProps {
  mapId?: string;
  mapData: MapResponse;
  // Add Data
  showAddData: boolean;
  onShowAddDataChange: (open: boolean) => void;
  onAddDataset: (datasetId: string) => void;
  onDuplicateRendering: (layerId: string) => void;
  layers: MapLayerResponse[];
  isAdding: boolean;
  basemapStyle: string;
  showBasemapLabels: boolean;
  basemapConfig: MapBasemapConfig | null;
  onBasemapChange: (key: string) => void;
  onBasemapLabelsChange: (show: boolean) => void;
  onBasemapConfigChange: (value: MapBasemapConfig) => void;
  addDataInitialQuery?: string;
  // Share
  showShare: boolean;
  onShowShareChange: (open: boolean) => void;
  hasUnsavedChanges: boolean;
  saveStatus: 'saved' | 'unsaved' | 'saving' | 'failed';
  // Info
  showInfo: boolean;
  onShowInfoChange: (open: boolean) => void;
  // Unsaved changes
  blockerState: 'blocked' | 'unblocked' | 'proceeding';
  onBlockerReset?: () => void;
  onBlockerProceed?: () => void;
}

export function BuilderDialogs({
  mapId,
  mapData,
  showAddData,
  onShowAddDataChange,
  onAddDataset,
  onDuplicateRendering,
  layers,
  isAdding,
  basemapStyle,
  showBasemapLabels,
  basemapConfig,
  onBasemapChange,
  onBasemapLabelsChange,
  onBasemapConfigChange,
  addDataInitialQuery,
  showShare,
  onShowShareChange,
  hasUnsavedChanges,
  saveStatus,
  showInfo,
  onShowInfoChange,
  blockerState,
  onBlockerReset,
  onBlockerProceed,
}: BuilderDialogsProps) {
  const { t } = useTranslation('builder');

  return (
    <>
      {/* Add Data dialog */}
      <Dialog open={showAddData} onOpenChange={onShowAddDataChange}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('search.title')}</DialogTitle>
            <DialogDescription>{t('search.dialogDescription')}</DialogDescription>
          </DialogHeader>
          <DatasetSearchPanel
            onAddDataset={onAddDataset}
            onDuplicateRendering={onDuplicateRendering}
            layers={layers}
            isAdding={isAdding}
            basemapStyle={basemapStyle}
            showBasemapLabels={showBasemapLabels}
            basemapConfig={basemapConfig}
            onBasemapChange={onBasemapChange}
            onBasemapLabelsChange={onBasemapLabelsChange}
            onBasemapConfigChange={onBasemapConfigChange}
            initialQuery={addDataInitialQuery}
          />
        </DialogContent>
      </Dialog>

      {/* Share dialog */}
      {mapId && (
        <ShareDialog
          mapId={mapId}
          visibility={mapData.visibility ?? 'private'}
          open={showShare}
          onOpenChange={onShowShareChange}
          hasUnsavedChanges={hasUnsavedChanges}
          saveStatus={saveStatus}
        />
      )}

      {/* Map Info dialog */}
      <Dialog open={showInfo} onOpenChange={onShowInfoChange}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('info.title')}</DialogTitle>
            <DialogDescription>{t('info.dialogDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.author')}</span>
              <span className="font-medium">{mapData.created_by_username ?? t('info.unknown')}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.created')}</span>
              <span>{formatRelativeDate(mapData.created_at ?? null)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.updated')}</span>
              <span>{formatRelativeDate(mapData.updated_at ?? null)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground">{t('info.visibility')}</span>
              <Badge variant="outline" className="flex items-center gap-1 text-xs">
                <VisibilityIcon visibility={mapData.visibility ?? 'private'} />
                {getVisibilityLabel(t, mapData.visibility ?? 'private')}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t('info.layers')}</span>
              <span>{mapData.layer_count ?? 0}</span>
            </div>
            {mapData.forked_from_id && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t('info.forkedFrom')}</span>
                {mapData.forked_from_name ? (
                  <Link
                    to={`/maps/${mapData.forked_from_id}`}
                    className="text-primary underline hover:text-primary/80"
                    onClick={() => onShowInfoChange(false)}
                  >
                    {mapData.forked_from_name}
                  </Link>
                ) : (
                  <span className="text-muted-foreground/60">{t('info.deletedMap')}</span>
                )}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Unsaved changes leave warning */}
      <Dialog open={blockerState === 'blocked'} onOpenChange={() => onBlockerReset?.()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('leaveWarning.title')}</DialogTitle>
            <DialogDescription>{t('leaveWarning.description')}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onBlockerReset?.()}>
              {t('leaveWarning.stay')}
            </Button>
            <Button variant="destructive" onClick={() => onBlockerProceed?.()}>
              {t('leaveWarning.leave')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
