import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { StorySettings } from '@/types/api';
import { readSettings, type SettingsEdit } from './story-draft';

const LAYOUTS: StorySettings['layout'][] = ['side', 'floating'];
const POSITIONS: StorySettings['panel_position'][] = ['left', 'right', 'center'];
const THEMES: StorySettings['theme'][] = ['follow', 'light', 'dark'];

interface StoryReaderSettingsDialogProps {
  settings: StorySettings | null | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (edit: SettingsEdit) => void;
}

/** How readers see the story. Changes join the draft and reach readers on Publish. */
export function StoryReaderSettingsDialog({ settings, open, onOpenChange, onChange }: StoryReaderSettingsDialogProps) {
  const { t } = useTranslation('stories');
  const { t: tWidgets } = useTranslation('widgets');
  const { t: tCommon } = useTranslation('common');
  const navId = useId();
  const current = readSettings(settings);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('readerSettings.heading')}</DialogTitle>
          <DialogDescription>{t('readerSettings.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor={navId}>{t('readerSettings.navigation')}</Label>
              <p className="text-xs text-muted-foreground">{t('readerSettings.navigationHint')}</p>
            </div>
            <Switch id={navId} checked={current.navigation} onCheckedChange={(navigation) => onChange({ navigation })} />
          </div>
          <SettingSelect
            label={t('readerSettings.layout')}
            hint={t('readerSettings.layoutHint')}
            value={current.layout}
            options={LAYOUTS.map((value) => ({ value, label: t(`readerSettings.layouts.${value}`) }))}
            onChange={(layout) => onChange({ layout })}
          />
          <SettingSelect
            label={tWidgets('editor.theme')}
            value={current.theme}
            options={THEMES.map((value) => ({
              value,
              label: value === 'follow' ? tWidgets('editor.themeFollow') : tCommon(`theme.${value}`),
            }))}
            onChange={(theme) => onChange({ theme })}
          />
          {current.layout === 'floating' && (
            <SettingSelect
              label={t('readerSettings.position')}
              value={current.panel_position}
              options={POSITIONS.map((value) => ({ value, label: t(`readerSettings.positions.${value}`) }))}
              onChange={(panel_position) => onChange({ panel_position })}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SettingSelect<T extends string>({
  label,
  hint,
  value,
  options,
  onChange,
}: {
  label: string;
  hint?: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={(next) => onChange(next as T)}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
