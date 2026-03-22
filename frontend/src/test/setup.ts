import '@testing-library/jest-dom/vitest'

// Initialize i18n for tests so useTranslation() resolves English strings
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { getTestI18nOptions } from '@/i18n/options';

if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init(getTestI18nOptions());
}

// Provide a reliable localStorage implementation for tests.
// Node 25 ships a built-in localStorage that conflicts with jsdom's when
// --localstorage-file is not configured, causing storage.setItem errors in
// zustand persist middleware.
if (typeof globalThis.localStorage === 'undefined' || typeof globalThis.localStorage.setItem !== 'function') {
  const store: Record<string, string> = {}
  globalThis.localStorage = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value) },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { for (const key of Object.keys(store)) delete store[key] },
    get length() { return Object.keys(store).length },
    key: (index: number) => Object.keys(store)[index] ?? null,
  } as Storage
}

// Mock maplibre-gl (requires WebGL2 which jsdom does not provide)
vi.mock('maplibre-gl', () => {
  const MockMap = vi.fn().mockImplementation(() => ({
    addControl: vi.fn(),
    removeControl: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    remove: vi.fn(),
    getCanvas: vi.fn(() => ({ style: {} })),
    getContainer: vi.fn(() => document.createElement('div')),
    resize: vi.fn(),
    fitBounds: vi.fn(),
    setCenter: vi.fn(),
    setZoom: vi.fn(),
    getCenter: vi.fn(() => ({ lng: 0, lat: 0 })),
    getZoom: vi.fn(() => 0),
    getBounds: vi.fn(() => ({
      getNorth: vi.fn(() => 90),
      getSouth: vi.fn(() => -90),
      getEast: vi.fn(() => 180),
      getWest: vi.fn(() => -180),
    })),
    addSource: vi.fn(),
    removeSource: vi.fn(),
    addLayer: vi.fn(),
    removeLayer: vi.fn(),
    getSource: vi.fn(),
    getLayer: vi.fn(),
    loaded: vi.fn(() => true),
  }))

  const MockNavigationControl = vi.fn()
  const MockMarker = vi.fn().mockImplementation(() => ({
    setLngLat: vi.fn().mockReturnThis(),
    addTo: vi.fn().mockReturnThis(),
    remove: vi.fn(),
    getElement: vi.fn(() => document.createElement('div')),
  }))
  const MockPopup = vi.fn().mockImplementation(() => ({
    setLngLat: vi.fn().mockReturnThis(),
    setHTML: vi.fn().mockReturnThis(),
    addTo: vi.fn().mockReturnThis(),
    remove: vi.fn(),
  }))

  return {
    default: { Map: MockMap, NavigationControl: MockNavigationControl, Marker: MockMarker, Popup: MockPopup },
    Map: MockMap,
    NavigationControl: MockNavigationControl,
    Marker: MockMarker,
    Popup: MockPopup,
  }
})

// Mock @vis.gl/react-maplibre (React components wrapping maplibre-gl)
vi.mock('@vis.gl/react-maplibre', () => ({
  Map: ({ children }: { children?: React.ReactNode }) => children ?? null,
  Source: ({ children }: { children?: React.ReactNode }) => children ?? null,
  Layer: () => null,
  NavigationControl: () => null,
}))

// Mock maplibre-gl CSS import (jsdom cannot process CSS)
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}))

// Clean up persisted Zustand state between tests
afterEach(() => {
  localStorage.clear()
})
