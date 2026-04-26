import { describe, it, expect } from 'vitest';
import {
  extractPlaceholders,
  validatePlaceholders,
  substitutePopupTemplate,
} from '@/lib/popup-template';

describe('extractPlaceholders', () => {
  it('returns [] for empty string', () => {
    expect(extractPlaceholders('')).toEqual([]);
  });

  it('returns [] when there are no placeholders', () => {
    expect(extractPlaceholders('plain text with no braces')).toEqual([]);
  });

  it('extracts a single placeholder', () => {
    expect(extractPlaceholders('hello {name}')).toEqual(['name']);
  });

  it('extracts multiple placeholders in document order', () => {
    expect(extractPlaceholders('{a}, {b} and {c}')).toEqual(['a', 'b', 'c']);
  });

  it('de-duplicates repeated placeholders', () => {
    expect(extractPlaceholders('{name} -- {name} ({name})')).toEqual(['name']);
  });

  it('ignores empty braces and identifiers starting with a digit', () => {
    expect(extractPlaceholders('{}{x}{1bad}')).toEqual(['x']);
  });

  it('ignores leading-digit identifiers but matches valid ones in the same string', () => {
    expect(extractPlaceholders('{2bad} {good_one}')).toEqual(['good_one']);
  });

  it('matches underscore-prefixed and mixed-case identifiers', () => {
    expect(extractPlaceholders('{_internal} {CamelCase}')).toEqual(['_internal', 'CamelCase']);
  });
});

describe('validatePlaceholders', () => {
  it('reports ok=true when every placeholder is known', () => {
    expect(validatePlaceholders(['a', 'b'], ['a', 'b', 'c'])).toEqual({
      ok: true,
      unknown: [],
    });
  });

  it('reports unknown placeholders', () => {
    expect(validatePlaceholders(['a', 'x'], ['a', 'b', 'c'])).toEqual({
      ok: false,
      unknown: ['x'],
    });
  });

  it('reports ok=true for an empty placeholder list', () => {
    expect(validatePlaceholders([], ['a', 'b'])).toEqual({
      ok: true,
      unknown: [],
    });
  });

  it('preserves the original order of unknown placeholders', () => {
    expect(validatePlaceholders(['x', 'a', 'y'], ['a'])).toEqual({
      ok: false,
      unknown: ['x', 'y'],
    });
  });
});

describe('substitutePopupTemplate', () => {
  it('substitutes a single placeholder', () => {
    expect(substitutePopupTemplate('Hello {name}', { name: 'Foo' })).toBe('Hello Foo');
  });

  it('substitutes missing keys with the empty string', () => {
    expect(substitutePopupTemplate('{name} -- {missing}', { name: 'Foo' })).toBe('Foo -- ');
  });

  it('coerces numbers to strings', () => {
    expect(substitutePopupTemplate('{count}', { count: 42 })).toBe('42');
  });

  it('treats null and undefined as empty strings', () => {
    expect(substitutePopupTemplate('a={a} b={b}', { a: null, b: undefined })).toBe('a= b=');
  });

  it('substitutes multiple placeholders in one string', () => {
    expect(substitutePopupTemplate('{city}, {state}', { city: 'Brooklyn', state: 'NY' })).toBe(
      'Brooklyn, NY',
    );
  });

  it('returns the template unchanged when there are no placeholders', () => {
    expect(substitutePopupTemplate('plain', { a: 1 })).toBe('plain');
  });

  it('leaves empty braces and digit-leading tokens literal', () => {
    expect(substitutePopupTemplate('{} {1bad}', { '1bad': 'X' })).toBe('{} {1bad}');
  });

  it('coerces booleans via String()', () => {
    expect(substitutePopupTemplate('{flag}', { flag: true })).toBe('true');
  });

  it('does not crash and substitutes empty when properties is null', () => {
    expect(substitutePopupTemplate('{city}, {state}', null)).toBe(', ');
  });

  it('does not crash and substitutes empty when properties is undefined', () => {
    expect(substitutePopupTemplate('{city}', undefined)).toBe('');
  });
});

