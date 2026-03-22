import { useTranslation } from 'react-i18next';
import { MAP_COLORS } from '@/lib/map-colors';

/**
 * Convert a hex color string to an rgba() string with the given opacity.
 */
function hexToRgba(hex: string, opacity: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

/**
 * Land mass outlines derived from Natural Earth 110m simplified data.
 * Coordinates are in SVG space (viewBox 0 0 360 180) where
 * x = longitude + 180, y = 90 - latitude.
 * 13 polygons, ~475 points — major continents plus significant islands.
 */
const LAND_PATHS = [
  // Eurasia
  "M287.0,13.0L307.0,16.4L340.9,20.6L359.2,27.7L340.0,36.8L335.0,30.9L318.2,43.7L308.3,51.4L305.1,51.2L300.8,52.1L298.7,65.5L288.9,74.7L279.9,80.8L280.6,85.2L275.4,74.3L268.2,68.3L257.9,81.7L247.1,65.3L228.2,60.5L231.8,66.0L239.3,68.6L232.2,74.4L222.8,74.7L216.6,64.2L214.8,65.0L223.3,78.0L230.8,79.7L218.8,96.5L215.2,109.6L211.5,119.3L198.9,124.4L192.8,109.7L192.2,96.3L187.1,85.5L172.0,85.6L163.4,77.8L163.7,67.0L174.1,54.2L191.1,53.1L200.1,57.8L214.3,58.8L209.7,53.9L220.9,47.0L213.9,45.6L208.8,48.9L203.4,52.6L196.9,46.8L196.2,48.3L194.7,49.4L180.1,49.9L170.5,51.3L175.4,41.3L188.3,33.2L196.4,35.5L208.0,30.5L197.1,28.7L190.5,25.5L213.9,23.2L225.6,22.4L248.2,20.9L254.2,22.7L264.7,16.2Z",
  // Antarctica
  "M121.4,154.2L117.9,156.2L116.0,158.9L119.0,162.8L112.8,165.8L104.6,167.3L103.4,169.9L120.3,172.4L135.2,171.8L151.5,170.3L144.7,168.1L156.1,166.2L163.5,163.9L170.9,161.3L178.2,161.2L187.1,160.2L194.7,160.0L202.6,160.7L212.0,159.7L218.6,159.8L226.5,157.6L233.6,155.9L240.6,157.7L248.9,157.9L248.4,161.4L253.3,160.4L260.1,158.1L267.5,156.9L274.2,157.1L281.6,156.3L290.2,156.7L297.4,156.9L306.1,156.6L314.8,156.2L319.9,156.9L327.7,158.1L336.8,159.4L346.1,160.8L349.8,163.2L343.6,166.2L343.7,169.1L343.7,172.4L358.3,174.5L3.1,174.3L10.0,173.9L31.5,175.6L27.0,172.8L31.1,171.0L24.0,168.7L28.7,167.4L35.7,165.5L46.3,164.4L58.9,164.5L67.7,164.7L79.4,165.3L78.4,162.8L88.6,163.4L98.5,163.9L107.2,163.4L112.1,160.9L112.3,157.3L118.0,154.6L121.4,154.2Z",
  // Africa
  "M89.5,20.5L98.6,22.9L85.3,31.1L100.1,38.8L104.3,27.7L117.5,31.8L118.3,39.9L115.5,43.8L113.0,45.2L107.7,48.7L104.7,51.0L104.1,53.4L99.5,62.0L95.9,59.9L89.1,60.9L82.5,65.0L88.6,71.1L92.2,71.7L91.5,74.1L95.5,74.1L96.3,78.1L100.1,80.7L105.8,78.7L109.0,80.1L115.7,79.4L122.9,84.0L129.6,90.1L144.8,95.5L139.2,110.9L129.3,121.0L123.3,126.4L116.2,132.0L110.9,140.7L104.4,138.7L106.4,127.2L108.5,107.4L98.9,94.0L101.4,88.2L101.6,81.6L98.3,81.9L95.1,80.2L92.6,77.1L86.1,74.1L75.0,70.7L70.7,63.6L65.2,59.1L69.3,65.7L66.4,63.4L62.1,56.4L55.8,48.9L55.1,40.0L43.4,31.8L28.6,29.3L18.8,34.6L21.8,31.4L13.9,28.5L16.5,25.4L13.8,21.1L30.3,19.5L50.9,20.2L64.7,22.1L81.6,22.2L87.6,20.3Z",
  // Australia
  "M323.6,103.8L325.3,105.4L326.1,108.3L328.7,110.6L330.7,112.4L333.1,116.1L333.3,119.5L331.7,123.0L330.1,126.4L327.4,128.2L325.0,127.9L321.6,128.3L319.1,125.7L316.8,125.3L317.0,123.8L314.6,123.2L311.3,121.5L305.1,122.7L302.2,124.0L299.0,124.5L295.6,124.4L295.7,122.9L295.0,119.5L293.5,116.5L294.2,116.3L293.5,113.8L294.2,112.5L297.2,110.6L299.3,110.0L302.2,108.2L303.9,107.1L304.9,105.1L306.1,104.1L309.0,104.9L310.2,103.1L312.6,101.6L314.4,102.0L316.5,101.9L316.1,103.7L317.1,105.9L319.3,107.4L321.4,105.8L321.7,102.9L322.1,101.0L323.2,102.3Z",
  // North America (upper)
  "M152.9,6.5L153.5,7.7L152.1,7.9L157.9,8.3L164.2,8.1L163.7,9.4L162.3,9.9L160.3,12.4L158.3,13.4L159.3,14.8L159.6,16.2L156.4,16.7L155.7,17.4L157.9,18.5L155.7,19.1L153.6,19.8L155.0,20.7L148.2,21.9L143.6,24.0L140.2,24.5L138.8,26.5L137.1,28.9L133.7,29.1L130.1,27.6L127.7,24.8L126.0,22.8L128.9,20.9L127.4,20.6L125.2,19.7L128.6,19.4L125,18.6L124.7,17.0L121.4,14.9L116.6,13.8L110.3,13.6L113.2,12.6L106.8,11.6L114.7,10.2L116.3,8.8L119.7,8.0L127.0,8.1L133.4,8.0L133.2,7.4L141.4,6.5Z",
  // South America
  "M93.4,16.8L97.7,16.2L101.2,17.6L105.8,18.2L108.8,19.1L113.0,20.8L115.1,22.2L117.8,23.8L113.3,23.6L112.9,24.9L115.3,26.6L111.2,26.3L113.8,28.1L107.8,26.6L105.2,25.3L101.4,25.4L106.0,24.5L107.3,22.7L105.2,21.4L102.7,20.2L100.5,20.1L92.9,19.7L91.5,18.8L90.6,16.9L93.4,16.8Z",
  // Greenland
  "M111.5,6.9L118.2,7.4L113.2,8.3L112.2,9.1L106.8,10.4L104.5,10.8L103.7,11.8L100.2,12.8L102.1,13.2L93.9,13.7L90.4,13.0L92.3,12.0L92.0,11.6L94.9,10.7L95.8,9.8L95.9,9.4L89.8,8.7L89.9,7.9L94.5,7.3L97.6,7.1L103.8,6.8L109.3,6.8Z",
  // Indonesia (Borneo area)
  "M314.1,91.2L316.3,92.3L319.2,92.1L322.7,93.3L325.8,94.9L327.9,96.6L328.1,98.0L329.3,99.5L330.8,100.3L329.8,100.4L327.1,99.5L324.7,97.6L323.4,99.0L321.0,99.1L318.9,98.4L318.7,97.3L316.0,94.5L313.4,94.0L312.8,93.3L313.8,92.5L311.8,91.6L311.9,90.7L314.1,91.2Z",
  // Indonesia (Sumatra area)
  "M297.9,88.2L297.8,89.2L297.5,90.8L296.5,92.5L296.0,93.7L294.5,93.5L293.3,93.1L291.7,93.0L290.2,92.9L289.6,91.3L289.0,89.6L289.7,88.0L291.2,88.1L291.8,87.1L293.7,86.1L294.6,85.1L296.2,83.9L297.1,83.1L297.7,84.0L299.2,84.6L298.4,85.0L297.9,85.9L298.0,87.7Z",
  // Central America / Caribbean
  "M65.8,16.9L67.6,17.0L70.1,17.0L71.8,18.3L71.6,16.9L73.5,16.9L75.2,18.3L77.2,19.5L78.9,20.4L77.9,20.9L75.8,21.1L72.9,20.9L68.0,21.4L66.1,21.0L63.9,20.8L63.3,19.9L66.3,19.8L65.7,19.4L62.1,19.5L63.9,18.7L60.6,18.4L62.1,17.3L65.8,16.9Z",
  // Madagascar
  "M230.1,103.6L230.5,105.2L230.2,106.0L229.7,105.7L229.8,106.9L229.4,108.0L228.5,110.5L227.5,113.8L226.3,115.2L224.8,115.3L223.8,114.5L223.3,112.8L223.4,111.3L223.9,110.8L224.5,109.4L224.0,108.3L224.3,106.9L224.9,106.2L225.9,105.8L226.9,105.2L228.0,104.1L228.3,103.8L228.9,102.5L229.5,102.5L230.1,103.6Z",
  // New Zealand (South Island area)
  "M285.8,95.9L284.7,95.9L283.9,95.0L282.6,94.2L282.2,93.6L281.4,92.8L280.9,92.1L280.1,90.7L279.3,89.8L279.0,89.0L278.6,88.2L277.7,87.5L277.2,86.7L276.4,86.1L275.4,85.0L275.3,84.5L275.9,84.6L277.5,84.8L278.4,85.7L279.1,86.4L279.7,86.8L280.6,87.9L281.7,87.9L282.5,88.6L283.1,89.4L283.8,89.9L283.4,90.7L284.0,91.1L284.4,91.1L284.5,91.8L284.9,92.3L285.6,92.4L286.1,93.1L285.9,94.3L285.8,95.9Z",
  // Japan
  "M177.0,31.4L176.9,32.3L177.8,33.1L177.9,34.1L179.6,35.5L180.5,37.1L181.6,37.9L181.4,38.7L179.2,39.2L177.0,39.3L175.5,39.7L174.2,39.8L176.6,38.6L174.7,38.0L175.2,37.2L176.9,36.6L176.4,35.4L174.9,34.9L175.0,34.2L174.4,33.7L174.2,32.2L175.8,31.4Z",
];

interface BBoxPreviewProps {
  bbox: [number, number, number, number] | null;
}

export function BBoxPreview({ bbox }: BBoxPreviewProps) {
  const { t } = useTranslation('search');

  if (!bbox) {
    return (
      <div className="flex items-center justify-center h-[120px] w-full bg-muted/30 rounded-md text-xs text-muted-foreground">
        {t('bbox.noExtent')}
      </div>
    );
  }

  const [minx, miny, maxx, maxy] = bbox;

  // Convert WGS84 coordinates to SVG space (viewBox 0 0 360 180)
  const x = minx + 180;
  const y = 90 - maxy; // SVG y is inverted
  const width = maxx - minx;
  const height = maxy - miny;

  // Detect dateline-crossing or compute coverage ratio
  const crossesDateline = minx > maxx;
  const bboxArea = Math.abs(width) * Math.abs(height);
  const worldArea = 360 * 180;
  const coverage = bboxArea / worldArea;

  // Adaptive viewBox: zoom in for datasets covering < 10% of the world
  let viewBox = '0 0 360 180';
  if (!crossesDateline && coverage < 0.1) {
    const padX = Math.max(width, 20) * 0.5;
    const padY = Math.max(height, 20) * 0.5;
    const vbX = Math.max(0, x - padX);
    const vbY = Math.max(0, y - padY);
    const vbW = Math.max(20, Math.min(360 - vbX, width + padX * 2));
    const vbH = Math.max(20, Math.min(180 - vbY, height + padY * 2));
    viewBox = `${vbX} ${vbY} ${vbW} ${vbH}`;
  }

  const strokeWidth = !crossesDateline && coverage < 0.1 ? 1 : 2;

  return (
    <svg
      viewBox={viewBox}
      className="h-[120px] w-full rounded-md bg-muted"
      preserveAspectRatio="xMidYMid meet"
    >
      {/* World outline */}
      <rect
        x="0"
        y="0"
        width="360"
        height="180"
        fill="none"
        stroke="currentColor"
        strokeWidth="0.5"
        className="text-border"
      />
      {/* Grid lines - prime meridian and equator */}
      <line x1="180" y1="0" x2="180" y2="180" stroke="currentColor" strokeWidth="0.2" className="text-border" />
      <line x1="0" y1="90" x2="360" y2="90" stroke="currentColor" strokeWidth="0.2" className="text-border" />
      {/* Latitude lines at 30N and 30S */}
      <line x1="0" y1="60" x2="360" y2="60" stroke="currentColor" strokeWidth="0.15" className="text-border" />
      <line x1="0" y1="120" x2="360" y2="120" stroke="currentColor" strokeWidth="0.15" className="text-border" />
      {/* Land mass outlines */}
      {LAND_PATHS.map((d, i) => (
        <path
          key={i}
          d={d}
          fill="currentColor"
          className="text-muted-foreground/15"
          stroke="none"
        />
      ))}
      {/* BBox rectangle */}
      <rect
        x={x}
        y={y}
        width={Math.max(width, 2)}
        height={Math.max(height, 2)}
        fill={hexToRgba(MAP_COLORS.default.fill, 0.25)}
        stroke={MAP_COLORS.default.fill}
        strokeWidth={strokeWidth}
        rx="0.5"
      />
    </svg>
  );
}
