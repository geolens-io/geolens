import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { UploadKind } from '@/types/api';

/** Chooses, before the upload, whether the files are geospatial data or 3D Tiles tilesets. */
export function UploadKindChoice({
  value,
  onChange,
  disabled,
  lockedHint,
  tilesetAvailable,
}: {
  value: UploadKind | null;
  onChange: (kind: UploadKind | null) => void;
  disabled: boolean;
  /** Says why the choice is locked; shown only while it is. */
  lockedHint?: string;
  tilesetAvailable: boolean;
}) {
  const { t } = useTranslation('import');
  const id = useId();
  const showLockedHint = disabled && lockedHint;
  const options = [
    { kind: null, key: 'files', label: t('upload.kindFiles'), hint: t('upload.kindFilesHint'), available: true },
    {
      kind: 'tiles3d' as const,
      key: 'tiles3d',
      label: t('upload.kindTileset'),
      hint: tilesetAvailable ? t('upload.kindTilesetHint') : t('upload.kindTilesetUnavailable'),
      available: tilesetAvailable,
    },
  ];

  return (
    <fieldset disabled={disabled} aria-describedby={showLockedHint ? `${id}-locked` : undefined} className="space-y-2">
      <legend className="text-sm font-medium">{t('upload.kindLegend')}</legend>
      {showLockedHint && (
        <p id={`${id}-locked`} className="text-xs text-muted-foreground">
          {lockedHint}
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <div
            key={option.key}
            className={cn(
              'rounded-lg border px-3 py-2.5',
              value === option.kind ? 'border-primary bg-primary/5' : 'border-border',
            )}
          >
            <label className="flex cursor-pointer items-center gap-2.5 text-sm font-medium">
              <input
                type="radio"
                name={`${id}-upload-kind`}
                value={option.key}
                checked={value === option.kind}
                onChange={() => onChange(option.kind)}
                disabled={!option.available}
                aria-describedby={`${id}-${option.key}-hint`}
              />
              {option.label}
            </label>
            <p id={`${id}-${option.key}-hint`} className="ms-6 mt-0.5 text-xs text-muted-foreground">
              {option.hint}
            </p>
          </div>
        ))}
      </div>
    </fieldset>
  );
}
