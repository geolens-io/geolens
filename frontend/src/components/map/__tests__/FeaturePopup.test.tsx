import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@/test/test-utils';
import type { ReactNode } from 'react';
import { FeaturePopup, type FeatureInfo } from '../FeaturePopup';

// ---------------------------------------------------------------------------
// EASY-11 rich-text / media rendering tests
// ---------------------------------------------------------------------------

// MapLibre's Popup component requires a real map context. For unit tests we
// just need the children to render — replace it with a passthrough wrapper.
vi.mock('@vis.gl/react-maplibre', () => ({
  Popup: ({ children }: { children: ReactNode }) => <div data-testid="popup">{children}</div>,
}));

function makeFeature(overrides: Partial<FeatureInfo> = {}): FeatureInfo {
  return {
    properties: { city: 'NYC', state: 'NY' },
    layerName: 'Test Layer',
    columnInfo: null,
    title: null,
    visibleFields: null,
    ...overrides,
  };
}

describe('FeaturePopup — EASY-11 rich-text rendering', () => {
  it('EASY-11 — text with embedded URL renders as text + anchor segments', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { description: 'See https://example.com for details' },
        visibleFields: ['description'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const anchor = screen.getByRole('link', { name: /https:\/\/example\.com/ });
    expect(anchor).toHaveAttribute('href', 'https://example.com');
    expect(anchor).toHaveAttribute('target', '_blank');
    expect(anchor).toHaveAttribute('rel', 'noopener noreferrer');
    // The surrounding cell should also contain the text "See "
    expect(screen.getByText(/See/)).toBeInTheDocument();
  });

  it('EASY-11 — image URL value renders a decorative <img> with src and lazy loading', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { photo: 'https://example.com/x.jpg' },
        visibleFields: ['photo'],
      }),
    ];
    const { container } = render(
      <FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />,
    );
    // fix(#438): A11Y-07 — the popup image is decorative (alt=""), so it is not
    // in the a11y tree and getByRole('img') no longer finds it. Query the DOM.
    const img = container.querySelector('img')!;
    expect(img).toHaveAttribute('src', 'https://example.com/x.jpg');
    expect(img).toHaveAttribute('alt', '');
    expect(img).toHaveAttribute('loading', 'lazy');
    // Fallback anchor also present
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://example.com/x.jpg');
  });

  it('EASY-11 — video URL value renders a <video controls preload=metadata>', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { clip: 'https://example.com/x.mp4' },
        visibleFields: ['clip'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const video = document.querySelector('video');
    expect(video).not.toBeNull();
    expect(video!.hasAttribute('controls')).toBe(true);
    expect(video).toHaveAttribute('preload', 'metadata');
  });

  it('EASY-11 — YouTube URL value renders an <iframe> with sandbox and title', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { video: 'https://youtu.be/dQw4w9WgXcQ' },
        visibleFields: ['video'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const iframe = document.querySelector('iframe');
    expect(iframe).not.toBeNull();
    expect(iframe!.getAttribute('src')).toContain('youtube.com/embed/dQw4w9WgXcQ');
    expect(iframe!.getAttribute('sandbox')).toContain('allow-scripts');
    expect(iframe!.getAttribute('title')).toBeTruthy();
  });

  it('EASY-11 — plain URL value (no extension) renders as anchor (backward-compat regression pin)', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { link: 'https://example.com' },
        visibleFields: ['link'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const anchor = screen.getByRole('link');
    expect(anchor).toHaveAttribute('href', 'https://example.com');
    // Should NOT be plain text without a link
    expect(anchor.tagName).toBe('A');
  });

  it('EASY-11 — javascript: in a property value is escaped as text, no anchor created', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { dangerous: 'javascript:alert(1)' },
        visibleFields: ['dangerous'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    // No anchor element should be rendered for XSS payloads
    expect(screen.queryByRole('link')).toBeNull();
    // The text content appears as plain text
    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument();
  });
});

describe('FeaturePopup', () => {
  it('renders the title above the property table when set', () => {
    const features: FeatureInfo[] = [makeFeature({ title: 'New York' })];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('New York')).toBeInTheDocument();
    expect(screen.getByText('NYC')).toBeInTheDocument();
  });

  it('renders only the title when visibleFields is [] (zero rows)', () => {
    const features: FeatureInfo[] = [
      makeFeature({ title: 'Just a title', visibleFields: [] }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('Just a title')).toBeInTheDocument();
    // Property values should NOT be rendered
    expect(screen.queryByText('NYC')).not.toBeInTheDocument();
  });

  it('fix(#584): renders configured fields absent from tile properties as "--" instead of dropping them', () => {
    // ST_AsMVT omits null-valued properties from the tile, so a configured
    // field can be missing from `properties` on the clicked feature.
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { present: 'value' },
        visibleFields: ['present', 'missing_null_field'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const cells = screen.getAllByRole('cell');
    expect(cells[0]).toHaveTextContent('Present');
    expect(cells[1]).toHaveTextContent('value');
    expect(cells[2]).toHaveTextContent('Missing Null Field');
    expect(cells[3]).toHaveTextContent('--');
  });

  it('fix(#584): hides configured fields absent from BOTH tile properties and the schema (stale config)', () => {
    // codex #586 P3: a reupload/rename can strand old names in visible_fields;
    // those stay hidden, while schema-present-but-null fields render '--'.
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { present: 'value' },
        columnInfo: [
          { name: 'present', type: 'text' },
          { name: 'null_but_in_schema', type: 'text' },
        ],
        visibleFields: ['present', 'null_but_in_schema', 'stale_removed_column'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const cells = screen.getAllByRole('cell');
    expect(cells).toHaveLength(4); // two rows only — stale field hidden
    expect(cells[0]).toHaveTextContent('Present');
    expect(cells[2]).toHaveTextContent('Null But In Schema');
    expect(cells[3]).toHaveTextContent('--');
    expect(screen.queryByText('Stale Removed Column')).not.toBeInTheDocument();
  });

  it('fix(#584): empty properties on a dataset WITH columns show the zoom hint, not "No attributes"', () => {
    // z<10 tiles strip attribute columns unless opted in via cols= — the
    // all-fields default opts nothing in, so properties arrive empty.
    const features: FeatureInfo[] = [
      makeFeature({
        properties: {},
        columnInfo: [{ name: 'borough', type: 'text' }],
        visibleFields: null,
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('Zoom in to view attributes')).toBeInTheDocument();
  });

  it('empty properties on a column-less dataset still show "No attributes"', () => {
    const features: FeatureInfo[] = [
      makeFeature({ properties: {}, columnInfo: null, visibleFields: null }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('No attributes')).toBeInTheDocument();
  });

  it('title-only mode (visibleFields []) never shows the zoom hint, even with columnInfo present', () => {
    // codex #586 P2: [] is the intentional "title only" contract — the zoom
    // hint is for the all-fields (null) case only.
    const features: FeatureInfo[] = [
      makeFeature({
        title: 'Just a title',
        properties: {},
        columnInfo: [{ name: 'borough', type: 'text' }],
        visibleFields: [],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    expect(screen.getByText('Just a title')).toBeInTheDocument();
    expect(screen.queryByText('Zoom in to view attributes')).not.toBeInTheDocument();
  });

  it('honors visible_fields ordering', () => {
    const features: FeatureInfo[] = [
      makeFeature({
        properties: { a: '1', b: '2', c: '3' },
        visibleFields: ['c', 'a'],
      }),
    ];
    render(<FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />);
    const cells = screen.getAllByRole('cell');
    // Row 0: c key + value, Row 1: a key + value
    expect(cells[0]).toHaveTextContent('C');
    expect(cells[1]).toHaveTextContent('3');
    expect(cells[2]).toHaveTextContent('A');
    expect(cells[3]).toHaveTextContent('1');
  });

  it('clamps activeIndex when features.length shrinks below the active page', () => {
    const features: FeatureInfo[] = [
      makeFeature({ properties: { name: 'A' } }),
      makeFeature({ properties: { name: 'B' } }),
      makeFeature({ properties: { name: 'C' } }),
    ];
    const { rerender } = render(
      <FeaturePopup longitude={0} latitude={0} features={features} onClose={vi.fn()} />,
    );
    // Initial: page 1/3, showing A
    expect(screen.getByText('A')).toBeInTheDocument();

    // Shrink to a single feature — activeIndex would be out of bounds (0 is fine
    // here, but the effect should reset it whenever features.length < activeIndex).
    rerender(
      <FeaturePopup
        longitude={0}
        latitude={0}
        features={[makeFeature({ properties: { name: 'X' } })]}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('X')).toBeInTheDocument();
    // Pager hidden when only one feature
    expect(screen.queryByLabelText(/next feature/i)).not.toBeInTheDocument();
  });
});
