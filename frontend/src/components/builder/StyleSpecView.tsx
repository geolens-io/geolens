import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';

interface StyleSpecViewProps {
  layer: MapLayerResponse;
}

/**
 * Read-only Mapbox style spec JSON view for a layer's paint/layout/filter properties.
 * Shown in the inspector's Style tab when advanced mode is on.
 */
export function StyleSpecView({ layer }: StyleSpecViewProps) {
  const { t } = useTranslation('builder');
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const spec = useMemo(() => {
    const obj: Record<string, unknown> = {};

    if (layer.paint && Object.keys(layer.paint).length > 0) {
      obj.paint = layer.paint;
    }
    if (layer.layout && Object.keys(layer.layout).length > 0) {
      obj.layout = layer.layout;
    }
    if (layer.filter) {
      obj.filter = layer.filter;
    }
    if (layer.opacity != null && layer.opacity !== 1) {
      obj.opacity = layer.opacity;
    }

    return JSON.stringify(obj, null, 2);
  }, [layer.paint, layer.layout, layer.filter, layer.opacity]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(spec);
      setCopyState('copied');
      setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      setCopyState('failed');
      setTimeout(() => setCopyState('idle'), 2000);
    }
  };

  return (
    <div className="mt-3 border-t pt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          {t('inspector.specTitle', { defaultValue: 'Style Spec' })}
        </span>
        <button
          onClick={handleCopy}
          className={cn(
            'inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded transition-colors',
            copyState === 'copied'
              ? 'text-success bg-success/10'
              : copyState === 'failed'
                ? 'text-destructive bg-destructive/10'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent',
          )}
          aria-label={t('inspector.copySpec', { defaultValue: 'Copy spec' })}
        >
          {copyState === 'copied' ? <Check className="h-2.5 w-2.5" /> : copyState === 'failed' ? <AlertCircle className="h-2.5 w-2.5" /> : <Copy className="h-2.5 w-2.5" />}
          {copyState === 'copied' ? t('common:actions.copied', { defaultValue: 'Copied' }) : copyState === 'failed' ? t('common:errors.failed', { defaultValue: 'Failed' }) : t('common:actions.copy', { defaultValue: 'Copy' })}
        </button>
      </div>
      <pre className="bg-surface-0 border rounded-md p-3 text-[11px] leading-relaxed font-mono overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap break-all text-foreground">
        {spec}
      </pre>
    </div>
  );
}
