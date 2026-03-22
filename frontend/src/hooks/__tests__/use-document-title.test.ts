import { renderHook } from '@testing-library/react';
import { useDocumentTitle } from '../use-document-title';

describe('useDocumentTitle', () => {
  const originalTitle = document.title;

  afterEach(() => {
    document.title = originalTitle;
  });

  it('sets document.title to "Title - GeoLens" for non-empty title', () => {
    renderHook(() => useDocumentTitle('Search'));
    expect(document.title).toBe('Search - GeoLens');
  });

  it('sets document.title to "GeoLens" for empty title', () => {
    renderHook(() => useDocumentTitle(''));
    expect(document.title).toBe('GeoLens');
  });
});
