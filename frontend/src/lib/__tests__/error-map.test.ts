import {
  classifyApiError,
  translateApiErrorDetail,
  translateError,
} from '@/lib/error-map';

describe('API error localization boundary', () => {
  it('maps known backend details to stable keys', () => {
    expect(classifyApiError('Dataset not found', 404)).toEqual({
      key: 'errors.datasetNotFound',
    });
    expect(translateError('Dataset not found', 404)).toBe('Dataset not found');
  });

  it('does not render unknown backend prose', () => {
    const backendDetail = 'Name is required according to an internal rule';
    const rendered = translateApiErrorDetail(backendDetail, 400);

    expect(rendered).toBe('The request could not be completed. Check your input.');
    expect(rendered).not.toContain(backendDetail);
  });

  it('uses a service fallback for unknown server failures', () => {
    expect(translateApiErrorDetail('SQL connection pool exhausted', 503)).toBe(
      'The service is temporarily unavailable. Try again later.',
    );
  });

  it('localizes storage quotas while preserving and formatting every number', () => {
    expect(
      translateApiErrorDetail(
        'Storage quota exceeded: used 1024 of 2048 bytes (adding 4096 bytes)',
        413,
      ),
    ).toBe(
      'Storage quota exceeded: 1,024 of 2,048 bytes used (adding 4,096 bytes).',
    );
  });

  it('localizes dataset quotas while preserving both counts', () => {
    expect(
      translateApiErrorDetail('Dataset quota exceeded: 5 of 5 datasets used', 422),
    ).toBe('Dataset quota exceeded: 5 of 5 datasets used.');
  });

  it('uses a structured backend code without displaying its English message', () => {
    const detail = {
      code: 'duplicate_source',
      message: 'A dataset from this source URL is already registered',
      existing_title: 'Road closures',
    };

    expect(classifyApiError(detail, 409)).toEqual({
      key: 'errors.duplicateSource',
      values: { title: 'Road closures' },
    });
    expect(translateApiErrorDetail(detail, 409)).toBe(
      'A dataset from this source is already registered (Road closures).',
    );
  });

  it('localizes FastAPI missing-field validation with field context', () => {
    const detail = [
      { type: 'missing', loc: ['body', 'display_name'], msg: 'Field required' },
    ];

    expect(translateApiErrorDetail(detail, 422)).toBe('display_name is required.');
  });

  it('localizes validation constraints with their numeric limit', () => {
    const detail = [
      {
        type: 'string_too_short',
        loc: ['body', 'name'],
        msg: 'String should have at least 3 characters',
        ctx: { min_length: 3 },
      },
    ];

    expect(translateApiErrorDetail(detail, 422)).toBe(
      'name must contain at least 3 characters.',
    );
  });

  it('does not stringify malformed validation payloads', () => {
    const detail = [{ code: 17, ctx: { limit: 3 } }];
    const rendered = translateApiErrorDetail(detail, 422);

    expect(rendered).toBe('The submitted values are invalid.');
    expect(rendered).not.toContain('{');
    expect(rendered).not.toContain('[');
  });

  it('retains unknown layer names through localized structured validation', () => {
    expect(
      translateApiErrorDetail(
        {
          message: 'Unknown layer name(s) — not found in the uploaded file',
          unknown_layers: ['roads', 'rivers'],
        },
        422,
      ),
    ).toBe('These layers were not found in the uploaded file: roads, rivers.');
  });
});
