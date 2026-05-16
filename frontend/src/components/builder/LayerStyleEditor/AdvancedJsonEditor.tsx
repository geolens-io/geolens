import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Code } from 'lucide-react';
import { Button } from '@/components/ui/button';

// Valid MapLibre paint properties per layer type for client-side validation.
// line-gradient gets first-class authoring through LineGradientControls (Phase 256)
// on top of the lineMetrics + adapter expression-preservation engine (Phase 255).
// AdvancedJsonEditor remains available for power-user / paste-in workflows.
const VALID_PAINT_KEYS: Record<string, Set<string>> = {
  fill: new Set(['fill-color', 'fill-opacity', 'fill-outline-color', 'fill-antialias', 'fill-translate', 'fill-translate-anchor', 'fill-pattern']),
  line: new Set(['line-color', 'line-opacity', 'line-width', 'line-gap-width', 'line-blur', 'line-dasharray', 'line-translate', 'line-translate-anchor', 'line-offset', 'line-gradient', 'line-pattern']),
  circle: new Set(['circle-color', 'circle-opacity', 'circle-radius', 'circle-blur', 'circle-stroke-color', 'circle-stroke-opacity', 'circle-stroke-width', 'circle-translate', 'circle-translate-anchor', 'circle-pitch-scale', 'circle-pitch-alignment']),
  heatmap: new Set(['heatmap-radius', 'heatmap-weight', 'heatmap-intensity', 'heatmap-color', 'heatmap-opacity']),
};

function validatePaintJson(paint: Record<string, unknown>, layerType?: string): string[] {
  if (!layerType) return [];
  const validKeys = VALID_PAINT_KEYS[layerType];
  if (!validKeys) return [];
  const errors: string[] = [];
  for (const key of Object.keys(paint)) {
    if (!validKeys.has(key)) {
      errors.push(`"${key}" is not a valid ${layerType} paint property`);
    }
  }
  return errors;
}

interface JsonBlockProps {
  label: string;
  value: Record<string, unknown>;
  onApply: (v: Record<string, unknown>) => void;
  layerType?: string;
}

function JsonBlock({ label, value, onApply, layerType }: JsonBlockProps) {
  const { t } = useTranslation('builder');
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);

  function handleOpen() {
    setText(JSON.stringify(value, null, 2));
    setError(null);
    setEditing(true);
  }

  function handleApply() {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setError(t('style.jsonError'));
        return;
      }
      // Validate paint properties against MapLibre spec if layerType is available
      if (layerType) {
        const validationErrors = validatePaintJson(parsed, layerType);
        if (validationErrors.length > 0) {
          setError(validationErrors.join('; '));
          return;
        }
      }
      onApply(parsed);
      setError(null);
      setEditing(false);
    } catch {
      setError(t('style.jsonError'));
    }
  }

  if (!editing) {
    return (
      <div>
        <button
          className="cursor-pointer text-xs text-muted-foreground hover:text-foreground underline"
          onClick={handleOpen}
        >
          {label}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <textarea
        className="w-full rounded border border-input bg-background p-2 text-xs font-mono resize-y min-h-[80px] outline-none focus:ring-1 focus:ring-ring"
        value={text}
        onChange={(e) => { setText(e.target.value); setError(null); }}
        spellCheck={false}
      />
      {error && <div className="text-xs text-destructive">{error}</div>}
      <div className="flex gap-1.5">
        <Button size="sm" className="h-6 text-xs px-2" onClick={handleApply}>
          {t('style.jsonApply')}
        </Button>
        <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={() => setEditing(false)}>
          {t('style.jsonCancel')}
        </Button>
      </div>
    </div>
  );
}

export interface AdvancedJsonEditorProps {
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  onPaintChange: (paint: Record<string, unknown>) => void;
  onLayoutChange: (layout: Record<string, unknown>) => void;
  defaultOpen?: boolean;
  layerType?: string;
}

export function AdvancedJsonEditor({ paint, layout, onPaintChange, onLayoutChange, defaultOpen = false, layerType }: AdvancedJsonEditorProps) {
  const { t } = useTranslation('builder');
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-t pt-2">
      <button
        className="flex cursor-pointer items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3 rtl-mirror" />}
        <Code className="h-3 w-3" />
        {t('style.advancedJson')}
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          <JsonBlock
            label={t('style.paintJson')}
            value={paint}
            onApply={onPaintChange}
            layerType={layerType}
          />
          <JsonBlock
            label={t('style.layoutJson')}
            value={layout}
            onApply={onLayoutChange}
          />
        </div>
      )}
    </div>
  );
}
