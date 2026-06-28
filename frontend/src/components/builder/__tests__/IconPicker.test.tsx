import { render } from '@/test/test-utils';
import { IconPicker } from '../IconPicker';
import { API_BASE } from '@/lib/constants';

// Bug-bash: the icon swatch <img> used icon.url verbatim (e.g.
// "/maps/icons/builtin:marker/asset"). An <img> tag bypasses apiFetch, so
// without the API_BASE prefix the request hit the frontend origin and 404'd to
// the SPA shell (text/html) → broken image. The fix prefixes API_BASE for
// API-relative urls while leaving absolute urls untouched.
vi.mock('@/hooks/use-maps', () => ({
  useMapIcons: () => ({
    data: {
      icons: [
        {
          id: 'b-marker', name: 'Marker', slug: 'marker', media_type: 'image/svg+xml',
          url: '/maps/icons/builtin:marker/asset', sprite_id: 'marker', builtin: true,
        },
        {
          id: 'cdn-1', name: 'CDN', slug: 'cdn', media_type: 'image/png',
          url: 'https://cdn.example.com/icon.png', sprite_id: 'cdn', builtin: false,
        },
      ],
    },
  }),
  useUploadMapIcon: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

describe('IconPicker', () => {
  it('prefixes API_BASE on a relative icon url, leaves an absolute url untouched', () => {
    const { container } = render(
      <IconPicker value="marker" onChange={vi.fn()} label="Icon" uploadAriaLabel="Upload icon" />,
    );
    const srcs = Array.from(container.querySelectorAll('img')).map((img) => img.getAttribute('src'));
    expect(srcs).toContain(`${API_BASE}/maps/icons/builtin:marker/asset`);
    expect(srcs).toContain('https://cdn.example.com/icon.png');
  });
});
