import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '@/i18n/i18n';
import { Ruler, Pentagon, Trash2 } from 'lucide-react';
import turfDistance from '@turf/distance';
import turfArea from '@turf/area';
import { point, polygon } from '@turf/helpers';
import { cn } from '@/lib/utils';
import type { WidgetContext } from '../types';

type MeasureMode = 'distance' | 'area';
type Unit = 'metric' | 'imperial';

interface LngLat {
  lng: number;
  lat: number;
}

const MEASURE_SOURCE = '_measure-src';
const MEASURE_LINE_LAYER = '_measure-line';
const MEASURE_POINTS_LAYER = '_measure-points';

/** Compute measurement result and build GeoJSON overlay for a set of points. */
function rebuildMeasurement(pts: LngLat[], currentMode: MeasureMode) {
  let result: number | null = null;
  if (currentMode === 'distance' && pts.length >= 2) {
    let total = 0;
    for (let i = 1; i < pts.length; i++) {
      const from = point([pts[i - 1].lng, pts[i - 1].lat]);
      const to = point([pts[i].lng, pts[i].lat]);
      total += turfDistance(from, to, { units: 'meters' });
    }
    result = total;
  } else if (currentMode === 'area' && pts.length >= 3) {
    const coords = pts.map((p) => [p.lng, p.lat]);
    coords.push(coords[0]);
    const poly = polygon([coords]);
    result = turfArea(poly);
  }

  const features: GeoJSON.Feature[] = [];
  pts.forEach((p) => {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
      properties: {},
    });
  });
  if (pts.length >= 2) {
    const coords = pts.map((p) => [p.lng, p.lat]);
    if (currentMode === 'area' && pts.length >= 3) {
      features.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [...coords, coords[0]] },
        properties: {},
      });
    } else {
      features.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: coords },
        properties: {},
      });
    }
  }

  return { result, features };
}

function formatDistance(meters: number, unit: Unit): string {
  const locale = i18n.language;
  if (unit === 'imperial') {
    const feet = meters * 3.28084;
    if (feet >= 5280) {
      return `${(feet / 5280).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} mi`;
    }
    return `${Math.round(feet).toLocaleString(locale)} ft`;
  }
  if (meters >= 1000) {
    return `${(meters / 1000).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} km`;
  }
  return `${Math.round(meters).toLocaleString(locale)} m`;
}

function formatArea(squareMeters: number, unit: Unit): string {
  const locale = i18n.language;
  if (unit === 'imperial') {
    const sqFeet = squareMeters * 10.7639;
    if (sqFeet >= 27878400) {
      return `${(sqFeet / 27878400).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} mi\u00b2`;
    }
    return `${Math.round(sqFeet).toLocaleString(locale)} ft\u00b2`;
  }
  if (squareMeters >= 1_000_000) {
    return `${(squareMeters / 1_000_000).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} km\u00b2`;
  }
  return `${Math.round(squareMeters).toLocaleString(locale)} m\u00b2`;
}

export function MeasurementWidget({ ctx }: { ctx: WidgetContext }) {
  const { t } = useTranslation('builder');
  const [mode, setMode] = useState<MeasureMode>('distance');
  const [points, setPoints] = useState<LngLat[]>([]);
  const [result, setResult] = useState<number | null>(null);
  const [unit, setUnit] = useState<Unit>('metric');

  // Keep refs in sync for use inside the event handler closure
  const modeRef = useRef(mode);
  const pointsRef = useRef(points);
  modeRef.current = mode;
  pointsRef.current = points;

  const map = ctx.mapInstance;

  // Setup / teardown map sources, layers, cursor and click handler
  useEffect(() => {
    if (!map) return;

    // Add measurement source and layers
    if (!map.getSource(MEASURE_SOURCE)) {
      map.addSource(MEASURE_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
    }

    if (!map.getLayer(MEASURE_LINE_LAYER)) {
      map.addLayer({
        id: MEASURE_LINE_LAYER,
        type: 'line',
        source: MEASURE_SOURCE,
        filter: ['==', '$type', 'LineString'],
        paint: {
          'line-color': '#3b82f6',
          'line-width': 2,
          'line-dasharray': [2, 1],
        },
      });
    }

    if (!map.getLayer(MEASURE_POINTS_LAYER)) {
      map.addLayer({
        id: MEASURE_POINTS_LAYER,
        type: 'circle',
        source: MEASURE_SOURCE,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 5,
          'circle-color': '#3b82f6',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff',
        },
      });
    }

    // Set crosshair cursor
    map.getCanvas().style.cursor = 'crosshair';

    const handleClick = (e: { lngLat: { lng: number; lat: number } }) => {
      const newPoint: LngLat = { lng: e.lngLat.lng, lat: e.lngLat.lat };
      const updatedPoints = [...pointsRef.current, newPoint];
      pointsRef.current = updatedPoints;
      setPoints(updatedPoints);

      const { result: computed, features } = rebuildMeasurement(updatedPoints, modeRef.current);
      setResult(computed);

      try {
        const src = map.getSource(MEASURE_SOURCE) as maplibregl.GeoJSONSource | undefined;
        src?.setData({ type: 'FeatureCollection', features });
      } catch {
        // Map may be destroyed during click handling
      }
    };

    map.on('click', handleClick);

    return () => {
      map.off('click', handleClick);
      try {
        if (map.getCanvas()) map.getCanvas().style.cursor = '';
        if (map.getLayer(MEASURE_POINTS_LAYER)) map.removeLayer(MEASURE_POINTS_LAYER);
        if (map.getLayer(MEASURE_LINE_LAYER)) map.removeLayer(MEASURE_LINE_LAYER);
        if (map.getSource(MEASURE_SOURCE)) map.removeSource(MEASURE_SOURCE);
      } catch {
        // Map style may already be destroyed during teardown
      }
    };
  }, [map]);

  // Update overlay when mode changes (recompute result from existing points)
  useEffect(() => {
    const pts = pointsRef.current;
    if (pts.length === 0) return;
    const { result: computed, features } = rebuildMeasurement(pts, mode);
    setResult(computed);

    if (!map) return;
    try {
      const src = map.getSource(MEASURE_SOURCE) as maplibregl.GeoJSONSource | undefined;
      src?.setData({ type: 'FeatureCollection', features });
    } catch {
      // Map may be destroyed during mode change
    }
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps -- pointsRef is stable

  function handleClear() {
    setPoints([]);
    pointsRef.current = [];
    setResult(null);
    if (!map) return;
    try {
      const src = map.getSource(MEASURE_SOURCE) as maplibregl.GeoJSONSource | undefined;
      src?.setData({ type: 'FeatureCollection', features: [] });
    } catch {
      // Map may be destroyed during teardown
    }
  }

  return (
    <div className="space-y-2.5 min-w-44">
      {/* Mode toggle */}
      <div className="flex gap-1">
        <button
          onClick={() => setMode('distance')}
          className={cn(
            'flex items-center gap-1 px-2 py-1 rounded text-xs border transition-colors',
            mode === 'distance'
              ? 'bg-primary text-primary-foreground border-primary'
              : 'border-border hover:bg-accent/50'
          )}
          title={t('widgets.measurement.distance')}
        >
          <Ruler className="h-3 w-3" />
          {t('widgets.measurement.distance')}
        </button>
        <button
          onClick={() => setMode('area')}
          className={cn(
            'flex items-center gap-1 px-2 py-1 rounded text-xs border transition-colors',
            mode === 'area'
              ? 'bg-primary text-primary-foreground border-primary'
              : 'border-border hover:bg-accent/50'
          )}
          title={t('widgets.measurement.area')}
        >
          <Pentagon className="h-3 w-3" />
          {t('widgets.measurement.area')}
        </button>
      </div>

      {/* Result */}
      {result !== null ? (
        <div className="text-center">
          <p className="text-lg font-semibold tabular-nums">
            {mode === 'distance' ? formatDistance(result, unit) : formatArea(result, unit)}
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground text-center">
          {t('widgets.measurement.clickToMeasure')}
        </p>
      )}

      {/* Unit toggle + clear */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => setUnit((u) => (u === 'metric' ? 'imperial' : 'metric'))}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors underline-offset-2 hover:underline"
        >
          {unit === 'metric' ? t('widgets.measurement.metric') : t('widgets.measurement.imperial')}
        </button>
        {points.length > 0 && (
          <button
            onClick={handleClear}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            title={t('widgets.measurement.clear')}
          >
            <Trash2 className="h-3 w-3" />
            {t('widgets.measurement.clear')}
          </button>
        )}
      </div>
    </div>
  );
}
