import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { AlertTriangle, Loader2, Save, Share2, MoreHorizontal, Info, Copy, Download, Pencil, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';


const IS_MAC = typeof navigator !== 'undefined' && (
  ('userAgentData' in navigator && (navigator.userAgentData as { platform?: string })?.platform === 'macOS') ||
  /Mac/i.test(navigator.userAgent)
);
const SAVE_SHORTCUT = IS_MAC ? '\u2318S' : 'Ctrl+S';

export interface OverflowActions {
  onExportPNG: () => void;
  onShowInfo: () => void;
  onFork: () => void;
  isForkPending: boolean;
}

interface MapTitleBarProps {
  name: string;
  onNameChange: (value: string) => void;
  description?: string;
  onDescriptionChange?: (value: string) => void;
  onMarkDirty: () => void;
  hasUnsavedChanges: boolean;
  isSaving: boolean;
  saveStatus?: 'saved' | 'unsaved' | 'saving' | 'failed';
  isSaveRetryable?: boolean;
  onSave: () => void;
  onShare?: () => void;
  overflow: OverflowActions;
}

export function MapTitleBar({
  name,
  onNameChange,
  description,
  onDescriptionChange,
  onMarkDirty,
  hasUnsavedChanges,
  isSaving,
  saveStatus = isSaving ? 'saving' : hasUnsavedChanges ? 'unsaved' : 'saved',
  isSaveRetryable = false,
  onSave,
  onShare,
  overflow,
}: MapTitleBarProps) {
  const { t } = useTranslation('builder');
  const saveStatusLabel = saveStatus === 'saving'
    ? t('titleBar.saveStatus.saving', { defaultValue: 'Saving...' })
    : saveStatus === 'failed'
      ? t('titleBar.saveStatus.failed', { defaultValue: 'Save failed' })
      : saveStatus === 'unsaved'
        ? t('titleBar.saveStatus.unsaved', { defaultValue: 'Unsaved changes' })
        : t('titleBar.saveStatus.saved', { defaultValue: 'Saved' });
  const saveButtonLabel = saveStatus === 'failed'
    ? t('titleBar.retrySave', { defaultValue: 'Retry save' })
    : saveStatus === 'unsaved'
      ? t('actions.save', { defaultValue: 'Save' })
      : saveStatus === 'saving'
        ? t('titleBar.saveStatus.saving', { defaultValue: 'Saving...' })
        : t('titleBar.saved', { defaultValue: 'Saved' });
  const saveTooltip = saveStatus === 'failed'
    ? t('tooltips.retrySave', { defaultValue: 'Save failed. Retry saving changes.' })
    : saveStatus === 'unsaved'
      ? t('tooltips.save', { shortcut: SAVE_SHORTCUT, defaultValue: `Save (${SAVE_SHORTCUT})` })
      : saveStatus === 'saving'
        ? t('titleBar.saveStatus.saving', { defaultValue: 'Saving...' })
        : t('tooltips.allSaved', { defaultValue: 'All changes saved' });
  const saveButtonAriaLabel = saveStatus === 'failed'
    ? t('titleBar.retrySave', { defaultValue: 'Retry save' })
    : t('tooltips.save', { shortcut: SAVE_SHORTCUT, defaultValue: `Save (${SAVE_SHORTCUT})` });

  return (
    <div className="h-10 border-b bg-background flex items-center gap-3 px-3 shrink-0">
      {/* Breadcrumb: Maps > editable name */}
      <nav aria-label="breadcrumb" className="flex items-center gap-1.5 min-w-0 flex-1">
        <Link
          to="/maps"
          className="text-sm text-muted-foreground hover:text-foreground transition-colors shrink-0"
        >
          {t('common:nav.maps', { defaultValue: 'Maps' })}
        </Link>
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0 rtl-mirror" />

        {/* Editable map name */}
        <div className="group relative min-w-0 shrink-0 max-w-xs">
          <input
            type="text"
            value={name}
            onChange={(e) => { onNameChange(e.target.value); onMarkDirty(); }}
            onBlur={() => { if (!name.trim()) onNameChange(t('titleBar.untitled', { defaultValue: 'Untitled Map' })); }}
            maxLength={255}
            aria-label={t('mapNameLabel', { defaultValue: 'Map name' })}
            className="text-sm font-medium truncate bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1.5 py-0.5 -ms-1.5 w-full hover:bg-accent/40 transition-colors pe-5"
            title={name}
          />
          <Pencil className="absolute right-1 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/40 opacity-0 group-hover:opacity-100 group-focus-within:opacity-0 transition-opacity pointer-events-none" />
        </div>

        {/* Inline description */}
        {onDescriptionChange && (
          <input
            type="text"
            value={description ?? ''}
            onChange={(e) => { onDescriptionChange(e.target.value); onMarkDirty(); }}
            maxLength={500}
            placeholder={t('descriptionPlaceholder', { defaultValue: 'Add a description\u2026' })}
            aria-label={t('titleBar.description', { defaultValue: 'Description' })}
            className="flex-1 min-w-0 text-xs text-muted-foreground bg-transparent border-none outline-none focus:ring-1 focus:ring-ring rounded px-1.5 py-0.5 truncate placeholder:text-muted-foreground/40 hover:bg-accent/40 transition-colors"
          />
        )}

      </nav>

      {/* Action buttons */}
      <TooltipProvider delayDuration={300}>
        <div className="flex items-center gap-1.5 shrink-0">
          {onShare && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1"
                  onClick={onShare}
                  aria-label={t('share.title', { defaultValue: 'Share' })}
                >
                  <Share2 className="h-3 w-3" />
                  <span className="hidden sm:inline">{t('share.title', { defaultValue: 'Share' })}</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">{t('tooltips.share', { defaultValue: 'Share' })}</TooltipContent>
            </Tooltip>
          )}

          {/* SP-06: a single Save button carries all three states (Save / Saving... /
              Saved / Save failed). The "[OK Saved]" badge that previously lived to
              the left was a duplicate signal — the button's label, dot indicator,
              and tooltip already convey state. */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                data-testid="builder-save-status"
                data-save-status={saveStatus}
                variant={saveStatus === 'failed' ? 'destructive' : hasUnsavedChanges ? 'default' : 'outline'}
                size="sm"
                className="h-7 text-xs gap-1 relative"
                onClick={onSave}
                disabled={isSaving}
                aria-label={saveButtonAriaLabel}
              >
                {isSaving ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : saveStatus === 'failed' ? (
                  <AlertTriangle className="h-3 w-3" />
                ) : hasUnsavedChanges ? (
                  <span className="relative inline-flex">
                    <Save className="h-3 w-3" />
                    <span
                      className="absolute -top-1 -right-1 h-1.5 w-1.5 rounded-full bg-warning ring-1 ring-background"
                      aria-label={t('titleBar.unsavedDot', { defaultValue: 'Unsaved changes' })}
                    />
                  </span>
                ) : (
                  <span className="h-1.5 w-1.5 rounded-full bg-success" />
                )}
                <span className="hidden sm:inline">
                  {isSaveRetryable ? t('titleBar.retry', { defaultValue: 'Retry' }) : saveButtonLabel}
                </span>
                {/* sr-only status text so AT users still hear the save state even
                    when the visible label is hidden on narrow viewports. */}
                <span className="sr-only">{saveStatusLabel}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {saveTooltip}
            </TooltipContent>
          </Tooltip>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon-xs"
                className="h-7 w-7"
                aria-label={t('tooltips.moreActions', { defaultValue: 'More actions' })}
              >
                <MoreHorizontal className="h-3 w-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={overflow.onExportPNG}>
                <Download className="h-3.5 w-3.5 me-2" />
                {t('tooltips.downloadPng', { defaultValue: 'Download PNG' })}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={overflow.onShowInfo}>
                <Info className="h-3.5 w-3.5 me-2" />
                {t('tooltips.mapInfo', { defaultValue: 'Map info' })}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={overflow.onFork} disabled={overflow.isForkPending}>
                <Copy className="h-3.5 w-3.5 me-2" />
                {t('tooltips.duplicateMap', { defaultValue: 'Duplicate map' })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </TooltipProvider>
    </div>
  );
}
