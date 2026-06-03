import { getEnvConfig } from '@/lib/env';

describe('getEnvConfig', () => {
  const originalEnv = window.__ENV__;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete window.__ENV__;
    } else {
      window.__ENV__ = originalEnv;
    }
  });

  it('returns default empty strings when window.__ENV__ is undefined', () => {
    delete window.__ENV__;
    const config = getEnvConfig();
    expect(config).toEqual({ API_BASE_URL: '', TILE_BASE_URL: '' });
  });

  it('returns values from window.__ENV__ when set', () => {
    window.__ENV__ = {
      API_BASE_URL: 'https://api.example.com',
      TILE_BASE_URL: 'https://tiles.example.com',
    };
    const config = getEnvConfig();
    expect(config.API_BASE_URL).toBe('https://api.example.com');
    expect(config.TILE_BASE_URL).toBe('https://tiles.example.com');
  });

  it('returns defaults for missing properties', () => {
    window.__ENV__ = { API_BASE_URL: 'https://api.example.com' };
    const config = getEnvConfig();
    expect(config.API_BASE_URL).toBe('https://api.example.com');
    expect(config.TILE_BASE_URL).toBe('');
  });
});
