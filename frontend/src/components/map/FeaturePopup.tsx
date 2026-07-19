import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '@/i18n/i18n';
import { Popup } from '@vis.gl/react-maplibre';
import { toast } from 'sonner';
import { ChevronLeft, ChevronRight, Copy, Check, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { truncateGraphemes } from '@/lib/text';
import { splitTextWithUrls, classifyUrl } from '@/lib/popup-rich-text';

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
  // #305: close button ref for soft focus move-in on open.
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  // #305: on open, soft-move focus to the close button so
  // keyboard users land inside the popup; on close/unmount, restore focus to
  // the map canvas (or container) so the map stays keyboard-operable. This is a
  // soft move + restore, NOT a focus trap — map interaction is preserved.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    return () => {
      // Restore focus to the map so the keyboard context returns to the map
      // (canvas carries tabindex=0); fall back to the map container, then to
      // wherever focus was before the popup opened.
      const restoreTarget =
        document.querySelector<HTMLElement>('.maplibregl-canvas') ??
        document.querySelector<HTMLElement>('.maplibregl-map') ??
        previouslyFocused;
      restoreTarget?.focus?.();
    };
  }, []);

  // #305: Escape closes the popup (focus is restored by the
  // unmount effect above). Document-level listener so it fires regardless of
  // which element inside the popup holds focus, without putting a keyboard
  // handler on the non-interactive dialog container.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

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
      // fix(#584): render EVERY configured field. ST_AsMVT omits null-valued
      // properties from the tile, so intersecting with the present keys
      // silently hid configured fields that are null on the clicked feature —
      // formatValue's '--' placeholder was unreachable.
      return visibleFields.map((k) => [k, propMap.get(k)] as [string, unknown]);
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
      {/* #305: labelled dialog container with focus management.
          aria-label uses the feature title when present, else the layer name. */}
      <div
        role="dialog"
        aria-label={
          title ||
          layerName ||
          t('featurePopup.dialogLabel', { defaultValue: 'Feature details' })
        }
        className="text-xs"
      >
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
              ref={closeButtonRef}
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
            <p className="text-xs text-muted-foreground py-1">
              {/* fix(#584): at z<10 the tile server strips attribute columns
                  unless opted in via cols=; in all-fields mode nothing is
                  opted in, so a dataset WITH columns arriving property-less
                  means "zoom in", not "no attributes". */}
              {(columnInfo?.length ?? 0) > 0
                ? t('featurePopup.zoomForAttributes')
                : t('featurePopup.noAttributes')}
            </p>
          ) : (
            <table className="w-full">
              <tbody>
                {visibleEntries.map(([key, value]) => (
                  <tr
                    key={key}
                    role="button"
                    tabIndex={0}
                    className="group cursor-pointer hover:bg-accent/50 rounded-sm transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
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
  const { t } = useTranslation('builder');

  // Standalone URL: classify and render image / video / YouTube / plain anchor.
  // This branch handles the case where the entire property value is a URL.
  // NOTE on iframe sandbox: YouTube embed REQUIRES allow-same-origin so the
  // player can load its own JS. This is intentionally laxer than the share-embed
  // sandbox (allow-scripts only). See threat model T-1138-04.
  if (isUrl(value)) {
    const { kind, srcUrl } = classifyUrl(value);

    if (kind === 'image') {
      return (
        <span className="block space-y-1">
          {/* fix(#438): BLD-01 — dropped `crossOrigin="anonymous"`. It forced a
              CORS request for every popup image, so images from hosts without
              CORS headers rendered broken where a plain <img> loads fine.
              Nothing here reads the pixels back through a canvas, which is the
              only thing the attribute buys. */}
          {/* fix(#438): A11Y-07 — `alt={srcUrl}` made a screen reader read out a
              raw URL. The image is a popup thumbnail with no caption we can
              derive, so an empty alt (decorative) is the correct treatment. */}
          <img
            src={srcUrl}
            alt=""
            loading="lazy"
            decoding="async"
            className="max-h-32 max-w-full rounded-sm object-contain"
          />
          <a
            href={srcUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline break-all text-2xs"
            onClick={(e) => e.stopPropagation()}
          >
            {truncateGraphemes(srcUrl, MAX_VALUE_LENGTH)}
          </a>
        </span>
      );
    }

    if (kind === 'video') {
      return (
        <span className="block">
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <video
            src={srcUrl}
            controls
            preload="metadata"
            className="max-h-32 max-w-full rounded-sm"
          />
        </span>
      );
    }

    if (kind === 'youtube') {
      return (
        <span className="block">
          <iframe
            src={srcUrl}
            title={t('featurePopup.youtubeTitle')}
            sandbox="allow-scripts allow-same-origin allow-presentation"
            referrerPolicy="no-referrer-when-downgrade"
            loading="lazy"
            className="max-h-32 max-w-full rounded-sm w-full aspect-video"
          />
        </span>
      );
    }

    // kind === 'other': plain anchor (backward-compatible with isUrl branch).
    return (
      <a
        href={value}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline break-all"
        onClick={(e) => e.stopPropagation()}
      >
        {!expanded ? truncateGraphemes(value, MAX_VALUE_LENGTH) : value}
      </a>
    );
  }

  // String with embedded URLs: split into text + anchor segments.
  // Media is NOT rendered inline here (POL: avoid blowing up a paragraph with embeds).
  if (typeof value === 'string') {
    const segments = splitTextWithUrls(value);
    const hasUrls = segments.some((s) => s.kind === 'url');
    if (hasUrls) {
      return (
        <span className="break-words">
          {segments.map((seg, i) =>
            seg.kind === 'url' ? (
              <a
                key={i}
                href={seg.value}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline break-all"
                onClick={(e) => e.stopPropagation()}
              >
                {seg.value}
              </a>
            ) : (
              <span key={i}>{seg.value}</span>
            ),
          )}
        </span>
      );
    }
  }

  const formatted = formatValue(value);
  const truncated = truncateGraphemes(formatted, MAX_VALUE_LENGTH, '');
  if (truncated !== formatted && !expanded) {
    return (
      <span className="break-words">
        {truncated}
        <button
          type="button"
          className="text-primary ms-0.5 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t('popup.showFullValue', { defaultValue: 'Show full value' })}
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
          // Keep Enter/Space on this button from bubbling to the surrounding
          // property row, whose keydown handler copies the value + preventDefaults
          // (which would otherwise hijack the button's own activation). #313 a11y.
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();
          }}
        >
          ...
        </button>
      </span>
    );
  }

  return <span className="break-words">{formatted}</span>;
}
