import { render, screen } from '@testing-library/react';
import { supportedLngs } from '@/i18n/config';
import { loadAllResources } from '@/i18n/resources';
import { WidgetView } from '../WidgetView';
import {
  checkWidgetWrite,
  getWidgetDefinition,
  parseStoredWidget,
  widgetDefinitions,
} from '../registry';

// A typical config for each registered type, with visible text in the
// fallback. A new widget type adds its entry here.
const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';

const examples: Record<string, { config: unknown; fallbackText: string | RegExp }> = {
  markdown: { config: { text: '## Heading\n\nSome **bold** text.' }, fallbackText: /Some \*\*bold\*\* text\./ },
};

function lookupKey(bundle: unknown, key: string): unknown {
  return key
    .split('.')
    .reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], bundle);
}

describe.each(widgetDefinitions.map((definition) => [definition.type, definition] as const))(
  'widget type %s',
  (type, definition) => {
    const surface = definition.surfaces[0];
    const example = examples[type];

    it('has an example config in this test', () => {
      expect(example).toBeDefined();
    });

    it('is registered for at least one surface and found by type', () => {
      expect(definition.surfaces.length).toBeGreaterThan(0);
      expect(getWidgetDefinition(type, surface)).toBe(definition);
      expect(Number.isInteger(definition.v) && definition.v >= 1).toBe(true);
    });

    it('validates its default and example configs', () => {
      for (const config of [definition.defaultConfig, example.config]) {
        const parsed = parseStoredWidget({ id, type, v: definition.v, config }, surface);
        expect(parsed).toMatchObject({ ok: true, instance: { id, type, v: definition.v, config } });
        expect(checkWidgetWrite({ id, type, v: definition.v, config }, surface)).toEqual({ ok: true });
      }
    });

    it('rejects configs of the wrong shape', () => {
      for (const config of [undefined, null, 'text', 42, []]) {
        expect(parseStoredWidget({ id, type, v: definition.v, config }, surface)).toMatchObject({
          ok: false,
          reason: 'invalid_config',
        });
      }
    });

    it('rejects an unknown type on write', () => {
      const unknown = { id, type: `${type}-from-the-future`, v: 1, config: example.config };
      expect(checkWidgetWrite(unknown, surface)).toEqual({ ok: false, reason: 'unknown_type' });
      expect(checkWidgetWrite({ ...unknown, v: definition.v + 1, type }, surface)).toEqual({
        ok: false,
        reason: 'unsupported_version',
      });
    });

    it('shows a notice for, and refuses on write, an instance it cannot parse', () => {
      const unreadable = [
        { id, type: `${type}-from-the-future`, v: 1, config: { anything: [1, 2] } },
        { id, type, v: definition.v + 1, config: example.config },
        { id, type, v: definition.v, config: { broken: true } },
      ];
      for (const raw of unreadable) {
        expect(parseStoredWidget(raw, surface).ok).toBe(false);
        expect(checkWidgetWrite(raw, surface).ok).toBe(false);
      }
    });

    it('renders its fallback as text', () => {
      render(<definition.Fallback config={example.config} />);
      expect(screen.getByText(example.fallbackText)).toBeInTheDocument();
    });

    it('loads a renderer that renders its example config', async () => {
      const { default: Renderer } = await definition.loadRenderer();
      const { container } = render(<Renderer config={example.config} />);
      expect(container.textContent).not.toBe('');
    });

    it('has its i18n keys in all five locales', async () => {
      const resources = await loadAllResources();
      for (const lng of supportedLngs) {
        for (const key of [definition.labelKey, ...definition.i18nKeys]) {
          expect(typeof lookupKey(resources[lng].widgets, key), `${lng}: widgets:${key}`).toBe(
            'string',
          );
        }
      }
    });
  },
);

describe('widget registry', () => {
  it('has unique type ids', () => {
    const types = widgetDefinitions.map((definition) => definition.type);
    expect(new Set(types).size).toBe(types.length);
  });

  it('treats a type not allowed on a surface as unknown there', () => {
    const storyOnly = widgetDefinitions.find((d) => !d.surfaces.includes('dashboard'));
    expect(storyOnly).toBeDefined();
    const instance = { id, type: storyOnly!.type, v: storyOnly!.v, config: storyOnly!.defaultConfig };
    expect(checkWidgetWrite(instance, 'dashboard')).toEqual({ ok: false, reason: 'unknown_type' });
  });

  it('marks an instance without a UUID id, string type or integer v as malformed', () => {
    const config = { text: 'x' };
    for (const raw of [
      null,
      'markdown',
      [],
      { type: 'markdown', v: 1, config },
      { id: 'not-a-uuid', type: 'markdown', v: 1, config },
      { id, v: 1, config },
      { id, type: 'markdown', v: '1', config },
    ]) {
      expect(parseStoredWidget(raw, 'story')).toEqual({ ok: false, reason: 'malformed' });
    }
  });

  it('refuses keys beyond id, type, v, title and config, as the server does', () => {
    const instance = { id, type: 'markdown', v: 1, config: { text: 'x' } };
    expect(checkWidgetWrite({ ...instance, layer_id: id }, 'story')).toEqual({
      ok: false,
      reason: 'malformed',
    });
  });

  it('keeps the id and a title of at most 120 characters', () => {
    const instance = { id, type: 'markdown', v: 1, title: 'x'.repeat(120), config: { text: 'x' } };
    expect(parseStoredWidget(instance, 'story')).toMatchObject({ ok: true, instance });
    expect(checkWidgetWrite({ ...instance, title: null }, 'story')).toEqual({ ok: true });
    expect(checkWidgetWrite({ ...instance, title: '🗺'.repeat(120) }, 'story')).toEqual({ ok: true });
    expect(checkWidgetWrite({ ...instance, title: 'x'.repeat(121) }, 'story')).toEqual({
      ok: false,
      reason: 'malformed',
    });
  });

  it('shows a notice for an instance it cannot parse', () => {
    render(<WidgetView parsed={parseStoredWidget({ id, type: 'future', v: 1, config: {} }, 'story')} />);
    expect(screen.getByText(/can't be shown/)).toBeInTheDocument();
  });
});
