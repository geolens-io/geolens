import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '@/i18n/i18n';
import { Popup } from '@vis.gl/react-maplibre';
import { toast } from 'sonner';
import { ChevronLeft, ChevronRight, Copy, Check, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface FeatureInfo {
  properties: Record<string, unknown>;
  layerName: string;
  columnInfo?: { name: string; type: string }[] | null;
  /** Already-substituted popup expression output. Rendered as a heading
   *  above the property table when present. */
  title?: string | null;
  /** Ordered allowlist of property keys to display; null/undefined → fall
   *  back to columnInfo legacy default; [] → render zero rows. */
  visibleFields?: string[] | null;
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
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  // Clamp activeIndex if features shrinks while popup is open (e.g. layer toggle race).
  useEffect(() => {
    if (activeIndex >= features.length) setActiveIndex(0);
  }, [features.length, activeIndex]);

  const feature = features[activeIndex] ?? features[0];

  const formatValue = useCallback(
    (value: unknown): string => {
      if (value === null || value === undefined) return '--';
      if (typeof value === 'boolean')
        return value ? t('featurePopup.booleanTrue') : t('featurePopup.booleanFalse');
      if (typeof value === 'number') {
        return Number.isInteger(value)
          ? value.toLocaleString(i18n.language)
          : value.toLocaleString(i18n.language, { maximumFractionDigits: 4 });
      }
      return String(value);
    },
    [t],
  );

  const properties = feature?.properties;
  const columnInfo = feature?.columnInfo;
  const visibleFields = feature?.visibleFields;

  // Filter entries: exclude internal keys and geometry fields.
  // Memoized so paging / copy-toast state doesn't re-derive for 100-attribute features.
  const baseEntries = useMemo(() => {
    if (!properties) return [] as [string, unknown][];
    return Object.entries(properties).filter(([key]) => {
      if (key.startsWith('_')) return false;
      if (EXCLUDED_KEYS.has(key)) return false;
      return true;
    });
  }, [properties]);

  // Visible-fields resolution:
  //   visibleFields is an ordered allowlist when defined → preserve user order
  //   null/undefined → fall back to legacy columnInfo allowlist
  //   [] → render zero rows (intentional "title only" mode)
  const visibleEntries = useMemo<[string, unknown][]>(() => {
    if (visibleFields !== undefined && visibleFields !== null) {
      const propMap = new Map(baseEntries);
      return visibleFields
        .filter((k) => propMap.has(k))
        .map((k) => [k, propMap.get(k)] as [string, unknown]);
    }
    if (columnInfo) {
      const columnNames = new Set(columnInfo.map((c) => c.name));
      return baseEntries.filter(([key]) => columnNames.has(key));
    }
    return baseEntries;
  }, [visibleFields, columnInfo, baseEntries]);

  if (!feature) return null;

  const { layerName, title } = feature;

  const handleCopy = async (key: string, value: unknown) => {
    const text = formatValue(value);
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopiedKey(null), 1500);
    } catch {
      toast.error(t('featurePopup.copyFailed'));
    }
  };

  const handlePrev = () => setActiveIndex((i) => Math.max(0, i - 1));
  const handleNext = () => setActiveIndex((i) => Math.min(features.length - 1, i + 1));

  const isMulti = features.length > 1;

  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      onClose={onClose}
      closeButton={false}
      closeOnClick={false}
      maxWidth="360px"
    >
      <div className="text-xs">
        {/* Header: layer name (left) + pager + close (right) */}
        <div className="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-border">
          <span className="font-semibold font-mono text-xs uppercase tracking-wide text-muted-foreground truncate">
            {layerName || '\u00A0'}
          </span>
          <div className="flex items-center gap-0.5 shrink-0">
            {isMulti && (
              <>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={handlePrev}
                  disabled={activeIndex === 0}
                  aria-label={t('featurePopup.prev')}
                >
                  <ChevronLeft className="rtl-mirror" />
                </Button>
                <span className="text-xs text-muted-foreground tabular-nums px-1">
                  {activeIndex + 1}/{features.length}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={handleNext}
                  disabled={activeIndex === features.length - 1}
                  aria-label={t('featurePopup.next')}
                >
                  <ChevronRight className="rtl-mirror" />
                </Button>
                <span className="w-px h-4 bg-border mx-1" aria-hidden="true" />
              </>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={onClose}
              aria-label={t('featurePopup.close')}
            >
              <X />
            </Button>
          </div>
        </div>

        {/* Title (custom expression output) */}
        {title && (
          <div
            className="font-semibold text-sm text-foreground mb-2 break-words"
            style={{ whiteSpace: 'pre-wrap' }}
          >
            {title}
          </div>
        )}

        {/* Properties */}
        <div className="max-h-48 overflow-y-auto">
          {visibleEntries.length === 0 ? (
            <p className="text-xs text-muted-foreground py-1">{t('featurePopup.noAttributes')}</p>
          ) : (
            <table className="w-full">
              <tbody>
                {visibleEntries.map(([key, value]) => (
                  <tr
                    key={key}
                    role="button"
                    tabIndex={0}
                    className="group cursor-pointer hover:bg-accent/50 rounded transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    onClick={() => handleCopy(key, value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        handleCopy(key, value);
                      }
                    }}
                    title={t('featurePopup.clickToCopy')}
                  >
                    <td className="pe-3 py-1 font-medium font-mono text-xs text-muted-foreground whitespace-nowrap align-top">
                      {humanizeKey(key)}
                    </td>
                    <td className="py-1 text-xs text-foreground">
                      <span className="flex items-start gap-1">
                        <ValueDisplay value={value} formatValue={formatValue} />
                        <span className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5">
                          {copiedKey === key ? (
                            <Check className="h-3 w-3 text-success" />
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
          ? Array.from(value).slice(0, MAX_VALUE_LENGTH).join('') + '...'
          : value}
      </a>
    );
  }

  const formatted = formatValue(value);
  if (formatted.length > MAX_VALUE_LENGTH && !expanded) {
    return (
      <span className="break-words">
        {Array.from(formatted).slice(0, MAX_VALUE_LENGTH).join('')}
        <button
          className="text-primary ms-0.5"
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
