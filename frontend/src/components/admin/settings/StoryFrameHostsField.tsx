import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { normalizeFrameHost } from '@/components/widgets/embed/frame';
import type { StoryFrameHost } from '@/types/api';
import { SettingSourceBadge } from './SettingSourceBadge';
import { findSetting } from './utils';
import type { SettingItem } from '@/api/settings';

/** The server's cap on approved hosts (`MAX_STORY_FRAME_HOSTS` in platform/story_frames.py). */
const MAX_STORY_FRAME_HOSTS = 50;

/** The stored value as a host list; anything else reads as empty. */
export function coerceStoryFrameHosts(value: unknown): StoryFrameHost[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) =>
    typeof entry?.host === 'string' ? [{ host: entry.host, allow_same_origin: entry.allow_same_origin === true }] : [],
  );
}

interface StoryFrameHostsFieldProps {
  settings: SettingItem[];
  hosts: StoryFrameHost[];
  onChange: (hosts: StoryFrameHost[]) => void;
  onReset: (key: string) => void;
  envOnly: boolean;
}

/** The sites story embed and video blocks may frame, each optionally keeping its own origin. */
export function StoryFrameHostsField({ settings, hosts, onChange, onReset, envOnly }: StoryFrameHostsFieldProps) {
  const { t } = useTranslation('admin');
  const id = useId();
  const [draft, setDraft] = useState('');
  const host = normalizeFrameHost(draft);
  const full = hosts.length >= MAX_STORY_FRAME_HOSTS;
  const error =
    draft.trim() === ''
      ? null
      : host === null
        ? t('settings.storyFrames.invalid')
        : hosts.some((entry) => entry.host === host)
          ? t('settings.storyFrames.duplicate')
          : null;

  function add(event: FormEvent) {
    event.preventDefault();
    if (host === null || error !== null || full) return;
    onChange([...hosts, { host, allow_same_origin: false }]);
    setDraft('');
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="text-base font-medium">{t('settings.storyFrames.title')}</h3>
        <SettingSourceBadge
          source={findSetting(settings, 'story_frame_hosts')?.source ?? 'default'}
          settingKey="story_frame_hosts"
          onReset={onReset}
        />
      </div>
      <p className="text-sm text-muted-foreground">{t('settings.storyFrames.description')}</p>
      {hosts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('settings.storyFrames.empty')}</p>
      ) : (
        <ul className="max-w-xl space-y-2">
          {hosts.map((entry, i) => (
            <li key={entry.host} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2">
              <span id={`${id}-host-${i}`} className="font-mono text-sm break-all">
                {entry.host}
              </span>
              <div className="flex items-center gap-2">
                <Switch
                  id={`${id}-same-origin-${i}`}
                  checked={entry.allow_same_origin}
                  disabled={envOnly}
                  aria-labelledby={`${id}-same-origin-label-${i} ${id}-host-${i}`}
                  aria-describedby={`${id}-same-origin-hint`}
                  onCheckedChange={(checked) =>
                    onChange(hosts.map((h) => (h.host === entry.host ? { ...h, allow_same_origin: checked } : h)))
                  }
                />
                <Label id={`${id}-same-origin-label-${i}`} htmlFor={`${id}-same-origin-${i}`} className="text-sm font-normal">
                  {t('settings.storyFrames.sameOrigin')}
                </Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  disabled={envOnly}
                  aria-label={t('settings.storyFrames.remove', { host: entry.host })}
                  onClick={() => onChange(hosts.filter((h) => h.host !== entry.host))}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p id={`${id}-same-origin-hint`} className="text-xs text-muted-foreground">
        {t('settings.storyFrames.sameOriginHint')}
      </p>
      <p className="text-xs text-muted-foreground">{t('settings.storyFrames.reloadHint')}</p>
      <form onSubmit={add} className="flex max-w-xl flex-wrap items-start gap-2">
        <div className="min-w-56 flex-1 space-y-1">
          <Label htmlFor={`${id}-host`}>{t('settings.storyFrames.hostLabel')}</Label>
          <Input
            id={`${id}-host`}
            value={draft}
            autoComplete="off"
            spellCheck={false}
            placeholder="media.example.org"
            disabled={envOnly || full}
            aria-invalid={error !== null}
            aria-describedby={error ? `${id}-host-error` : full ? `${id}-host-full` : undefined}
            onChange={(event) => setDraft(event.target.value)}
          />
          {error && (
            <p id={`${id}-host-error`} className="text-xs text-destructive">
              {error}
            </p>
          )}
          {full && (
            <p id={`${id}-host-full`} className="text-xs text-muted-foreground">
              {t('settings.storyFrames.full', { max: MAX_STORY_FRAME_HOSTS })}
            </p>
          )}
        </div>
        <Button type="submit" variant="outline" className="mt-6" disabled={envOnly || full || host === null || error !== null}>
          {t('settings.storyFrames.add')}
        </Button>
      </form>
    </div>
  );
}
