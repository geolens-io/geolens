import { afterEach, describe, it, expect } from 'vitest';
import {
  INTERNAL_FAILURE_REASON,
  describeFailureReason,
  fixedFailureReason,
} from '@/lib/failure-reason';
import { changeTestLanguage } from '@/test/i18n';

describe('describeFailureReason', () => {
  afterEach(async () => {
    await changeTestLanguage('en');
  });

  it('replaces the coded reason with the localized line', () => {
    expect(describeFailureReason(INTERNAL_FAILURE_REASON, 'Something went wrong')).toBe(
      'Something went wrong',
    );
  });

  it('leaves a message the server composed alone', () => {
    const composed = "Layer 'parcels' has no geometry column";
    expect(describeFailureReason(composed, 'Something went wrong')).toBe(composed);
  });

  it('pins the code the backend stores', () => {
    // Mirrors INTERNAL_FAILURE_REASON in backend/app/core/failure_reason.py.
    expect(INTERNAL_FAILURE_REASON).toBe('internal_error');
  });

  it.each([
    ['arcgis_wfs_count_unavailable', "Couldn't count the features this ArcGIS WFS holds"],
    ['arcgis_wfs_short', 'fewer features than the layer holds'],
    ['arcgis_wfs_repeated', 'the same features more than once'],
    ['service_auth_refused', "the token is valid and hasn't expired"],
    ['service_error', 'answered with an error'],
    ['service_empty_page', 'Retry in a few minutes'],
  ])('shows the import refusal %s as its own guidance', (code, text) => {
    expect(describeFailureReason('English text the worker stored', 'Something went wrong', code)).toContain(
      text,
    );
  });

  it("shows a fixed reason in the reader's language", async () => {
    await changeTestLanguage('de');

    expect(describeFailureReason('Cancelled by user', 'Something went wrong', 'user_cancelled')).toBe(
      'Vom Benutzer abgebrochen',
    );
  });

  it("shows a point cloud refusal the worker stored in the reader's language", async () => {
    await changeTestLanguage('fr');

    expect(
      describeFailureReason(
        "The point cloud's points don't decode as its header describes.",
        'Something went wrong',
        'pointcloud_decode_failed',
      ),
    ).toBe("Les points du nuage de points ne se décodent pas comme l'indique son en-tête.");
  });

  it("names the columns a replacement lacks in the reader's language", async () => {
    await changeTestLanguage('es');
    const stored =
      "The replacement lacks the columns this dataset's geometry is built from (lat, Lon Deg), so nothing was changed. Add them to the file, or import the file as a new dataset instead.";

    expect(describeFailureReason(stored, 'Something went wrong', 'geometry_columns_missing')).toBe(
      'Este reemplazo no tiene las columnas con las que se construye la geometría de este conjunto de datos (lat, Lon Deg), así que no se cambió nada. Añádelas al archivo o impórtalo como un conjunto de datos nuevo.',
    );
  });

  it.each([
    ['geometry_xy_not_numeric', '3 row(s) contain X/Y values that are not numbers', '3 fila(s) tienen valores X o Y'],
    ['geometry_xy_outside_wgs84', '2 row(s) contain X/Y coordinates outside EPSG:4326 ranges', '2 fila(s) tienen coordenadas X/Y fuera'],
    ['geometry_xy_not_finite', '4 row(s) contain X/Y coordinates outside finite values', '4 fila(s) tienen coordenadas X/Y que no son números finitos'],
    [
      'geometry_wkt_invalid_wgs84',
      '5 row(s) contain invalid WKT geometry or coordinates outside EPSG:4326 ranges',
      '5 fila(s) tienen geometría WKT no válida',
    ],
    [
      'geometry_wkt_invalid',
      '6 row(s) contain invalid WKT geometry or coordinates outside finite values',
      '6 fila(s) tienen geometría WKT no válida o coordenadas que no son números finitos',
    ],
    ['geometry_wkt_malformed', 'WKT column contains malformed geometry text', 'La columna WKT contiene texto'],
  ])("shows the geometry build failure %s in the reader's language", async (code, stored, text) => {
    await changeTestLanguage('es');

    expect(describeFailureReason(stored, 'Something went wrong', code)).toContain(text);
  });

  it('names a header the server joined onto one line', () => {
    const stored =
      "The replacement lacks the columns this dataset's geometry is built from (Lat: Deg, lon), so nothing was changed. Add them to the file, or import the file as a new dataset instead.";

    expect(describeFailureReason(stored, 'Something went wrong', 'geometry_columns_missing')).toContain(
      '(Lat: Deg, lon)',
    );
  });

  it('keeps a stored geometry-columns reason it cannot read the columns from', () => {
    const stored = 'internal_error';
    expect(describeFailureReason(stored, 'Something went wrong', 'geometry_columns_missing')).toBe(
      'Something went wrong',
    );
  });

  it('keeps the stored reason for a code with no fixed sentence', () => {
    const composed = 'Rejected before execution: source_changed.';
    expect(describeFailureReason(composed, 'Something went wrong', 'source_changed')).toBe(composed);
    expect(fixedFailureReason(null)).toBeUndefined();
  });
});
