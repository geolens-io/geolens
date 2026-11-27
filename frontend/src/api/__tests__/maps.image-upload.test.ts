import { uploadOgImage, uploadThumbnail } from '../maps';
import { apiFetch } from '../client';

vi.mock('../client', async () => {
  const actual = await vi.importActual<typeof import('../client')>('../client');
  return { ...actual, apiFetch: vi.fn() };
});

const mockApiFetch = vi.mocked(apiFetch);

describe('map image upload expected_updated_at', () => {
  beforeEach(() => {
    mockApiFetch.mockReset();
    mockApiFetch.mockResolvedValue(undefined);
  });

  it('uploadThumbnail sends expected_updated_at in the PUT body when provided and omits it otherwise', async () => {
    await uploadThumbnail('map-1', 'data:image/jpeg;base64,abc', '2026-11-25T08:00:00Z');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/maps/map-1/thumbnail/', {
      method: 'PUT',
      body: JSON.stringify({
        data_uri: 'data:image/jpeg;base64,abc',
        expected_updated_at: '2026-11-25T08:00:00Z',
      }),
    });

    await uploadThumbnail('map-1', 'data:image/jpeg;base64,abc');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/maps/map-1/thumbnail/', {
      method: 'PUT',
      body: JSON.stringify({
        data_uri: 'data:image/jpeg;base64,abc',
      }),
    });
  });

  it('uploadOgImage sends expected_updated_at in the PUT body when provided and omits it otherwise', async () => {
    await uploadOgImage('map-1', 'data:image/jpeg;base64,xyz', '2026-11-25T08:00:00Z');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/maps/map-1/og-image/', {
      method: 'PUT',
      body: JSON.stringify({
        data_uri: 'data:image/jpeg;base64,xyz',
        expected_updated_at: '2026-11-25T08:00:00Z',
      }),
    });

    await uploadOgImage('map-1', 'data:image/jpeg;base64,xyz');
    expect(mockApiFetch).toHaveBeenLastCalledWith('/maps/map-1/og-image/', {
      method: 'PUT',
      body: JSON.stringify({
        data_uri: 'data:image/jpeg;base64,xyz',
      }),
    });
  });
});
