import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Code } from 'lucide-react';
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
import { Button } from '@/components/ui/button';

// Use the real MapLibre style-spec validator to catch property names,
// color values, numeric bounds, expression syntax, and type mismatches —
// not just property names. Wrap the user's paint/layout in a minimal
// single-layer style of the correct layer type and filter errors that
// aren't about paint/layout (we synthesize the source, so source errors
// would always fire here and are irrelevant to what the user is editing).
function validatePropertyBlock(
  value: Record<string, unknown>,
  layerType: string | undefined,
  block: 'paint' | 'layout',
): string[] {
  if (!layerType) return [];
  // Construct a layer object with the right shape for the requested type.
  // Use a GeoJSON source stub (no source-layer needed) with lineMetrics
  // enabled so line-gradient expressions using ["line-progress"] validate
  // — line-gradient REQUIRES a GeoJSON source per MapLibre spec, and the
  // project supports it via the Phase 255 lineMetrics + adapter engine.
  const layer: Record<string, unknown> = {
    id: '_validate_target',
    type: layerType,
    source: '_validate_src',
    [block]: value,
  };
  const testStyle = {
    version: 8,
    sources: {
      _validate_src: {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
        lineMetrics: true,
      },
    },
    layers: [layer],
  };
  let errors: { message?: string }[] = [];
  try {
    // validateStyleMin is typed against StyleSpecification but tolerates
    // any object shape; cast to satisfy the compiler.
    errors = validateStyleMin(testStyle as unknown as Parameters<typeof validateStyleMin>[0]) ?? [];
  } catch {
    // If the validator itself throws, fall back to no errors rather than
    // blocking the user — better to let MapLibre runtime catch real bugs
    // than to falsely reject a paste that the validator can't parse.
    return [];
  }
  return errors
    .map((e) => e?.message ?? '')
    .filter((m): m is string => Boolean(m))
    .filter((m) => {
      // Drop messages about the stub source/source-layer/sprite/glyphs —
      // those aren't about what the user typed.
      const lower = m.toLowerCase();
      if (lower.includes('sprite') || lower.includes('glyphs')) return false;
      if (lower.includes('"_validate_src"') || lower.includes('source-layer')) return false;
      // Drop source-tile-url validation noise (we set a placeholder URL).
      if (lower.includes('tiles')) return false;
      return true;
    });
}

interface JsonBlockProps {
  label: string;
  value: Record<string, unknown>;
  onApply: (v: Record<string, unknown>) => void;
  layerType?: string;
  /** Which property block this editor edits — drives the validator shape. */
  block: 'paint' | 'layout';
}

function JsonBlock({ label, value, onApply, layerType, block }: JsonBlockProps) {
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
      // Validate against the real MapLibre style spec — catches property
      // names, color values, numeric bounds, expression syntax, types.
      if (layerType) {
        const validationErrors = validatePropertyBlock(parsed, layerType, block);
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
            block="paint"
          />
          <JsonBlock
            label={t('style.layoutJson')}
            value={layout}
            onApply={onLayoutChange}
            layerType={layerType}
            block="layout"
          />
        </div>
      )}
    </div>
  );
}
