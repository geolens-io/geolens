import { useMemo } from 'react';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { Upload } from 'lucide-react';
import { cn } from '@/lib/utils';
import { buildAcceptMap, deriveFormatBadges } from '@/lib/file-utils';

interface FileDropzoneProps {
  onFilesAccepted: (files: File[]) => void;
  disabled?: boolean;
  allowedExtensions?: string[];
  maxSizeMb?: number;
}

export function FileDropzone({ onFilesAccepted, disabled, allowedExtensions, maxSizeMb }: FileDropzoneProps) {
  const { t } = useTranslation('import');

  const { accept, badges } = useMemo(() => {
    if (!allowedExtensions || allowedExtensions.length === 0) {
      return { accept: undefined, badges: [] };
    }
    return {
      accept: buildAcceptMap(allowedExtensions),
      badges: deriveFormatBadges(allowedExtensions),
    };
  }, [allowedExtensions]);

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      accept,
      maxFiles: 10,
      multiple: true,
      disabled,
      onDrop: (accepted) => {
        if (accepted.length > 0) {
          onFilesAccepted(accepted);
        }
      },
    });

  return (
    <div
      {...getRootProps()}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-all duration-200 ease-out',
        isDragReject && 'border-destructive bg-destructive/10 scale-[1.01]',
        isDragActive && !isDragReject && 'border-primary bg-primary/10 scale-[1.01] shadow-md',
        !isDragActive &&
          !isDragReject &&
          'border-muted-foreground/25 hover:border-muted-foreground/50',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      <input {...getInputProps()} />
      <Upload className="mb-3 h-10 w-10 text-muted-foreground" />

      {isDragReject ? (
        <p className="text-sm font-medium text-destructive">
          {t('dropzone.unsupportedType')}
        </p>
      ) : isDragActive ? (
        <p className="text-sm font-medium text-primary">
          {t('dropzone.dropHere')}
        </p>
      ) : (
        <p className="text-sm font-medium">
          {t('dropzone.instructions')}
        </p>
      )}

      {badges.length > 0 && (
        <div className="mt-3 flex flex-wrap justify-center gap-1.5">
          {badges.map((ext) => (
            <span
              key={ext}
              className="inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground"
            >
              {ext}
            </span>
          ))}
        </div>
      )}

      <p className="mt-2 text-xs text-muted-foreground">
        {maxSizeMb != null
          ? t('dropzone.sizeLimitDynamic', { size: maxSizeMb, defaultValue: `Max ${maxSizeMb} MB per file` })
          : t('dropzone.sizeLimit')}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {t('dropzone.batchLimit')}
      </p>
    </div>
  );
}
