import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Code } from 'lucide-react';
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

// A mixed-geometry (GEOMETRY sentinel) layer's paint and layout span three
// MapLibre layer types: the adapter fans the same dict out to fill/line/circle
// sublayers via filterPaintForLayerType. Split the block by family prefix so
// each subset validates against its own layer type; un-prefixed keys (e.g.
// layout `visibility`) validate under the fill primary. fill-extrusion-* lands
// in the fill bucket and is rejected there, correctly, since the mixed adapter
// has no extrusion sublayer.
function splitMixedBlock(value: Record<string, unknown>) {
  const buckets: Record<'fill' | 'line' | 'circle', Record<string, unknown>> = {
    fill: {},
    line: {},
    circle: {},
  };
  for (const [key, entry] of Object.entries(value)) {
    if (key.startsWith('line-')) buckets.line[key] = entry;
    else if (key.startsWith('circle-')) buckets.circle[key] = entry;
    else buckets.fill[key] = entry;
  }
  return buckets;
}

// Uses the real MapLibre style-spec validator to catch property names, color
// values, numeric bounds, expression syntax and type mismatches. The user's
// paint/layout is wrapped in a minimal single-layer style of the right type,
// and errors that aren't about paint/layout are filtered out (the source is
// synthesized, so source errors would always fire). Exported for tests.
export function validatePropertyBlock(
  value: Record<string, unknown>,
  layerType: string | undefined,
  block: 'paint' | 'layout',
): string[] | null {
  if (!layerType) return [];
  if (layerType === 'mixed') {
    const buckets = splitMixedBlock(value);
    const allErrors: string[] = [];
    for (const family of ['fill', 'line', 'circle'] as const) {
      if (Object.keys(buckets[family]).length === 0) continue;
      const familyErrors = validatePropertyBlock(buckets[family], family, block);
      if (familyErrors === null) return null;
      allErrors.push(...familyErrors);
    }
    return allErrors;
  }
  // Build a layer of the right shape for the requested type, on a GeoJSON
  // source stub (no source-layer needed) with lineMetrics enabled so
  // line-gradient expressions using ["line-progress"] validate: line-gradient
  // requires a GeoJSON source per the MapLibre spec, which the lineMetrics +
  // adapter engine supports.
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
    // validateStyleMin is typed against StyleSpecification but tolerates any
    // object shape; cast to satisfy the compiler.
    errors = validateStyleMin(testStyle as unknown as Parameters<typeof validateStyleMin>[0]) ?? [];
  } catch {
    // A validator crash must block the apply (null sentinel), not wave the paste
    // through: returning [] would apply unvalidated JSON to MapLibre.
    return null;
  }
  return errors
    .map((e) => e?.message ?? '')
    .filter((m): m is string => Boolean(m))
    .filter((m) => {
      // Drop messages about the stub source/source-layer/sprite/glyphs.
      const lower = m.toLowerCase();
      if (lower.includes('sprite') || lower.includes('glyphs')) return false;
      if (lower.includes('"_validate_src"') || lower.includes('source-layer')) return false;
      // Drop source-tile-url noise (we set a placeholder URL).
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
  const contentId = useId();
  const errorId = useId();

  // Collapsing the block must not discard a draft: seed the text only when there
  // is nothing to preserve. Apply and Cancel are the explicit exits that reset it.
  function handleToggle() {
    if (editing) { setEditing(false); return; }
    if (text === '') setText(JSON.stringify(value, null, 2));
    setError(null);
    setEditing(true);
  }

  function handleCancel() {
    setText('');
    setError(null);
    setEditing(false);
  }

  function handleApply() {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setError(t('style.jsonError'));
        return;
      }
      // Validate against the real MapLibre style spec (property names, color
      // values, numeric bounds, expression syntax, types).
      if (layerType) {
        const validationErrors = validatePropertyBlock(parsed, layerType, block);
        if (validationErrors === null) {
          // Validator crashed — block the apply.
          setError(t('style.validatorUnavailable', {
            defaultValue: 'This JSON could not be validated — simplify the value and try again.',
          }));
          return;
        }
        if (validationErrors.length > 0) {
          setError(validationErrors.join('; '));
          return;
        }
      }
      onApply(parsed);
      setText('');
      setError(null);
      setEditing(false);
    } catch {
      setError(t('style.jsonError'));
    }
  }

  // One disclosure button that stays mounted, so its expanded state is
  // reportable; the error is announced and wired to the textarea.
  return (
    <div className="space-y-1.5">
      <button
        type="button"
        className={cn(
          'cursor-pointer text-xs hover:text-foreground',
          editing ? 'font-medium text-muted-foreground' : 'text-muted-foreground underline',
        )}
        onClick={handleToggle}
        aria-expanded={editing}
        aria-controls={contentId}
      >
        {label}
      </button>
      {/* The aria-controls target stays mounted and `hidden` while collapsed:
          an id reference resolving to nothing is what AT hits at the collapsed
          trigger. */}
      <div id={contentId} hidden={!editing} className="space-y-1.5">
        <Textarea
          className="text-xs font-mono resize-y min-h-[80px]"
          value={text}
          onChange={(e) => { setText(e.target.value); setError(null); }}
          spellCheck={false}
          aria-label={t('style.jsonTextareaAriaLabel', { block: label })}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
        />
        {error && <div id={errorId} role="alert" className="text-xs text-destructive">{error}</div>}
        <div className="flex gap-1.5">
          <Button size="sm" className="h-6 text-xs px-2" onClick={handleApply}>
            {t('style.jsonApply')}
          </Button>
          <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={handleCancel}>
            {t('style.jsonCancel')}
          </Button>
        </div>
      </div>
    </div>
  );
}

interface AdvancedJsonEditorProps {
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
  const blocksId = useId();

  // Symbol mode keeps circle paint on the layer (renderAs.ts) but has real
  // symbol layout, so each block validates against what it holds. Validating the
  // stored circle paint as 'symbol' would reject every key and make the Paint
  // block a dead end.
  const paintLayerType = layerType === 'symbol' ? 'circle' : layerType;

  return (
    <div className="border-t pt-2">
      <button
        type="button"
        className="flex cursor-pointer items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={blocksId}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3 rtl-mirror" />}
        <Code className="h-3 w-3" />
        {t('style.advancedJson')}
      </button>
      <div id={blocksId} hidden={!open} className="mt-2 space-y-3">
          <JsonBlock
            label={t('style.paintJson')}
            value={paint}
            onApply={onPaintChange}
            layerType={paintLayerType}
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
    </div>
  );
}
