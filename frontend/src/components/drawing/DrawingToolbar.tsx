import {
  MapPin,
  Spline,
  Pentagon,
  Square,
  Circle,
  PenTool,
  X,
  MousePointer,
  Check,
  FileEdit,
  Trash2,
  Undo2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useDrawingStore } from '@/stores/drawing-store';
import { getAvailableModes } from '@/hooks/use-terra-draw';
import { Button } from '@/components/ui/button';
import type { LucideIcon } from 'lucide-react';

interface ModeConfig {
  mode: string;
  labelKey: string;
  icon: LucideIcon;
}

const ALL_MODES: ModeConfig[] = [
  { mode: 'point', labelKey: 'drawing.point', icon: MapPin },
  { mode: 'linestring', labelKey: 'drawing.line', icon: Spline },
  { mode: 'polygon', labelKey: 'drawing.polygon', icon: Pentagon },
  { mode: 'rectangle', labelKey: 'drawing.rectangle', icon: Square },
  { mode: 'circle', labelKey: 'drawing.circle', icon: Circle },
  { mode: 'freehand', labelKey: 'drawing.freehand', icon: PenTool },
];

interface DrawingToolbarProps {
  geometryType: string | null;
  onClose: () => void;
  onModeChange?: (mode: string) => void;
  onSaveEdit?: () => void;
  onCancelEdit?: () => void;
  onEditAttributes?: () => void;
  onDeleteFeature?: () => void;
  onUndo?: () => void;
  canUndo?: boolean;
}

export function DrawingToolbar({
  geometryType,
  onClose,
  onModeChange,
  onSaveEdit,
  onCancelEdit,
  onEditAttributes,
  onDeleteFeature,
  onUndo,
  canUndo,
}: DrawingToolbarProps) {
  const { t } = useTranslation('builder');
  const activeMode = useDrawingStore((s) => s.activeMode);
  const setMode = useDrawingStore((s) => s.setMode);
  const selectedFeature = useDrawingStore((s) => s.selectedFeature);

  const availableModes = getAvailableModes(geometryType);
  const visibleModes = ALL_MODES.filter((m) => availableModes.includes(m.mode));
  const handleModeChange = onModeChange ?? setMode;

  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2">
      {/* Main toolbar */}
      <div className="rounded-lg shadow-lg border bg-background p-1 flex items-center gap-1">
        {/* Select button */}
        <Button
          variant={activeMode === 'select' ? 'default' : 'outline'}
          size="sm"
          title={t('drawing.select')}
          aria-label={t('drawing.select')}
          onClick={() => handleModeChange('select')}
        >
          <MousePointer className="h-4 w-4" />
          <span className="hidden sm:inline">{t('drawing.select')}</span>
        </Button>

        <div className="w-px h-6 bg-border mx-1" />

        {/* Drawing mode buttons */}
        {visibleModes.map(({ mode, labelKey, icon: Icon }) => (
          <Button
            key={mode}
            variant={activeMode === mode ? 'default' : 'outline'}
            size="sm"
            title={t(labelKey)}
            aria-label={t(labelKey)}
            onClick={() => handleModeChange(mode)}
          >
            <Icon className="h-4 w-4" />
            <span className="hidden sm:inline">{t(labelKey)}</span>
          </Button>
        ))}

        <div className="w-px h-6 bg-border mx-1" />

        <Button
          variant="outline"
          size="sm"
          title={t('drawing.undo')}
          aria-label={t('drawing.undo')}
          onClick={onUndo}
          disabled={!canUndo}
        >
          <Undo2 className="h-4 w-4" />
        </Button>

        <div className="w-px h-6 bg-border mx-1" />

        <Button variant="ghost" size="icon-sm" title={t('drawing.done')} aria-label={t('drawing.done')} onClick={onClose}>
          <Check className="h-4 w-4" />
        </Button>
      </div>

      {/* Editing action bar — shown when a feature is selected */}
      {selectedFeature && (
        <div className="rounded-lg shadow-lg border bg-background p-1 flex items-center gap-1">
          <Button
            variant="default"
            size="sm"
            title={t('drawing.saveChanges')}
            aria-label={t('drawing.saveChanges')}
            onClick={onSaveEdit}
          >
            <Check className="h-4 w-4" />
            <span className="hidden sm:inline">{t('common:save')}</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            title={t('drawing.cancelEditing')}
            aria-label={t('drawing.cancelEditing')}
            onClick={onCancelEdit}
          >
            <X className="h-4 w-4" />
            <span className="hidden sm:inline">{t('common:cancel')}</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            title={t('drawing.editAttributes')}
            aria-label={t('drawing.editAttributes')}
            onClick={onEditAttributes}
          >
            <FileEdit className="h-4 w-4" />
            <span className="hidden sm:inline">{t('drawing.editAttributes')}</span>
          </Button>

          <Button
            variant="destructive"
            size="sm"
            title={t('drawing.deleteFeature')}
            aria-label={t('drawing.deleteFeature')}
            onClick={onDeleteFeature}
          >
            <Trash2 className="h-4 w-4" />
            <span className="hidden sm:inline">{t('common:delete')}</span>
          </Button>
        </div>
      )}
    </div>
  );
}
