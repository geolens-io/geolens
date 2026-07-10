import { useRef } from 'react';
import { Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useMapIcons, useUploadMapIcon } from '@/hooks/use-maps';
import { API_BASE } from '@/lib/constants';
import { cn } from '@/lib/utils';

interface IconPickerProps {
  value: string;
  onChange: (spriteId: string) => void;
  label: string;
  // CONF-06 (Phase 277): localized aria-label for the upload button + hidden
  // file input. Required (no default fallback) to ensure non-EN locales never
  // surface the hardcoded English string. Use t('style.symbol.uploadIcon').
  uploadAriaLabel: string;
}

export function IconPicker({ value, onChange, label, uploadAriaLabel }: IconPickerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const iconsQuery = useMapIcons();
  const uploadIcon = useUploadMapIcon();
  const icons = iconsQuery.data?.icons ?? [];

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const icon = await uploadIcon.mutateAsync(file);
    onChange(icon.sprite_id);
    event.target.value = '';
  }

  return (
    <div className="space-y-2">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="symbol-icon-image">
            {label}
          </label>
          <Input
            id="symbol-icon-image"
            className="h-8 text-xs"
            value={value}
            onChange={(event) => onChange(event.target.value || 'marker')}
          />
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".svg,.png,image/svg+xml,image/png"
          className="sr-only"
          onChange={handleFileChange}
          aria-label={uploadAriaLabel}
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-8 w-8"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadIcon.isPending}
          aria-label={uploadAriaLabel}
        >
          <Upload className="h-3.5 w-3.5" />
        </Button>
      </div>
      {icons.length > 0 && (
        <div className="grid grid-cols-5 gap-1">
          {icons.map((icon) => (
            <button
              key={icon.id}
              type="button"
              className={cn(
                'flex cursor-pointer h-8 w-8 items-center justify-center rounded-sm border bg-background text-2xs font-medium',
                value === icon.sprite_id ? 'border-primary ring-1 ring-ring' : 'border-border hover:bg-accent',
              )}
              onClick={() => onChange(icon.sprite_id)}
              title={icon.name}
              aria-label={icon.name}
            >
              {/* icon.url is the API-relative asset path (e.g. /maps/icons/...);
                  an <img> tag bypasses apiFetch, so prefix API_BASE or it resolves
                  against the frontend origin and 404s to the SPA shell (#350-followup). */}
              <img
                src={icon.url.startsWith('http') ? icon.url : `${API_BASE}${icon.url}`}
                alt=""
                className="h-5 w-5 object-contain"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
