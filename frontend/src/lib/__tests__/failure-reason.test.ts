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

  it('keeps the stored reason for a code with no fixed sentence', () => {
    const composed = 'Rejected before execution: source_changed.';
    expect(describeFailureReason(composed, 'Something went wrong', 'source_changed')).toBe(composed);
    expect(fixedFailureReason(null)).toBeUndefined();
  });
});
