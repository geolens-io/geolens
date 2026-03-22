import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Popup } from '@vis.gl/react-maplibre';
import { toast } from 'sonner';
import { ChevronLeft, ChevronRight, Copy, Check } from 'lucide-react';

export interface FeatureInfo {
  properties: Record<string, unknown>;
  layerName: string;
  columnInfo?: { name: string; type: string }[] | null;
}

export interface FeaturePopupProps {
  longitude: number;
  latitude: number;
  features: FeatureInfo[];
  onClose: () => void;
}

const EXCLUDED_KEYS = new Set(['geom', 'geometry']);
const MAX_VALUE_LENGTH = 100;

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  return value.startsWith('http://') || value.startsWith('https://');
}

export function FeaturePopup({
  longitude,
  latitude,
  features,
  onClose,
}: FeaturePopupProps) {
  const { t } = useTranslation('builder');
  const [activeIndex, setActiveIndex] = useState(0);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const feature = features[activeIndex] ?? features[0];
  if (!feature) return null;

  const { properties, layerName, columnInfo } = feature;

  function formatValue(value: unknown): string {
    if (value === null || value === undefined) return '--';
    if (typeof value === 'boolean') return value ? t('featurePopup.booleanTrue') : t('featurePopup.booleanFalse');
    if (typeof value === 'number') {
      return Number.isInteger(value)
        ? value.toLocaleString()
        : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
    }
    return String(value);
  }

  // Filter entries: exclude internal keys and geometry fields
  const entries = Object.entries(properties).filter(([key]) => {
    if (key.startsWith('_')) return false;
    if (EXCLUDED_KEYS.has(key)) return false;
    return true;
  });

  // When columnInfo is available, further filter to only show keys present in it
  const columnNames = columnInfo
    ? new Set(columnInfo.map((c) => c.name))
    : null;

  const visibleEntries = columnNames
    ? entries.filter(([key]) => columnNames.has(key))
    : entries;

  const handleCopy = async (key: string, value: unknown) => {
    const text = formatValue(value);
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1500);
    } catch {
      toast.error(t('featurePopup.copyFailed'));
    }
  };

  const handlePrev = () => setActiveIndex((i) => Math.max(0, i - 1));
  const handleNext = () => setActiveIndex((i) => Math.min(features.length - 1, i + 1));

  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      onClose={onClose}
      closeOnClick={false}
      maxWidth="320px"
    >
      <div className="text-xs">
        {/* Header: layer name + feature counter */}
        <div className="flex items-center justify-between gap-2 mb-1 pb-1 border-b">
          {layerName && (
            <span className="font-semibold text-muted-foreground truncate">
              {layerName}
            </span>
          )}
          {features.length > 1 && (
            <div className="flex items-center gap-0.5 shrink-0">
              <button
                onClick={handlePrev}
                disabled={activeIndex === 0}
                className="p-0.5 rounded hover:bg-muted disabled:opacity-30"
              >
                <ChevronLeft className="h-3 w-3" />
              </button>
              <span className="text-muted-foreground tabular-nums text-[10px]">
                {activeIndex + 1}/{features.length}
              </span>
              <button
                onClick={handleNext}
                disabled={activeIndex === features.length - 1}
                className="p-0.5 rounded hover:bg-muted disabled:opacity-30"
              >
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>

        {/* Attribute table */}
        <div className="max-h-48 overflow-y-auto">
          {visibleEntries.length === 0 ? (
            <p className="text-muted-foreground py-1">{t('featurePopup.noAttributes')}</p>
          ) : (
            <table className="w-full">
              <tbody>
                {visibleEntries.map(([key, value]) => (
                  <tr
                    key={key}
                    className="group cursor-pointer hover:bg-muted/50 rounded"
                    onClick={() => handleCopy(key, value)}
                    title={t('featurePopup.clickToCopy')}
                  >
                    <td className="pr-2 py-0.5 font-medium text-muted-foreground whitespace-nowrap align-top">
                      {humanizeKey(key)}
                    </td>
                    <td className="py-0.5 text-foreground">
                      <span className="flex items-start gap-1">
                        <ValueDisplay value={value} formatValue={formatValue} />
                        <span className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5">
                          {copiedKey === key ? (
                            <Check className="h-3 w-3 text-green-500" />
                          ) : (
                            <Copy className="h-3 w-3 text-muted-foreground" />
                          )}
                        </span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Popup>
  );
}

function ValueDisplay({
  value,
  formatValue,
}: {
  value: unknown;
  formatValue: (v: unknown) => string;
}) {
  const [expanded, setExpanded] = useState(false);

  if (isUrl(value)) {
    return (
      <a
        href={value}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline break-all"
        onClick={(e) => e.stopPropagation()}
      >
        {value.length > MAX_VALUE_LENGTH && !expanded
          ? value.slice(0, MAX_VALUE_LENGTH) + '...'
          : value}
      </a>
    );
  }

  const formatted = formatValue(value);
  if (formatted.length > MAX_VALUE_LENGTH && !expanded) {
    return (
      <span className="break-words">
        {formatted.slice(0, MAX_VALUE_LENGTH)}
        <button
          className="text-primary ml-0.5"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
        >
          ...
        </button>
      </span>
    );
  }

  return <span className="break-words">{formatted}</span>;
}
