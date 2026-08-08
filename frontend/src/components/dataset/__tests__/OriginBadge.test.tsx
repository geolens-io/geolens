import { render, screen } from '@/test/test-utils';
import type { DatasetOrigin } from '@/types/api';
import { OriginBadge } from '../OriginBadge';

describe('OriginBadge source-mode copy', () => {
  it.each([
    ['upload', 'Uploaded', 'local copy in GeoLens'],
    ['postgis', 'PostGIS', "GeoLens's PostGIS database"],
    ['service', 'Service', 'One-shot copy imported from a remote service'],
    ['stac', 'STAC', 'Live reference to an asset'],
    ['created', 'Created', 'Created in GeoLens as an editable layer'],
  ] satisfies Array<[DatasetOrigin, string, string]>)(
    'describes %s without implying an unsupported source mode',
    (origin, label, description) => {
      render(<OriginBadge origin={origin} />);

      const badge = screen.getByTestId('origin-badge');
      expect(badge).toHaveAttribute('data-origin', origin);
      expect(badge).toHaveTextContent(label);
      expect(badge).toHaveAttribute('title', expect.stringContaining(description));
    },
  );
});
