import { render, screen } from '@testing-library/react';
import { supportedLngs } from '@/i18n/config';
import { loadAllResources } from '@/i18n/resources';
import { WidgetView } from '../WidgetView';
import type { WidgetDocument } from '../contract';
import {
  checkWidgetWrite,
  getWidgetDefinition,
  parseStoredWidget,
  serializeWidget,
  widgetDefinitions,
} from '../registry';

// A typical config for each registered type, with visible text in the
// fallback. A new widget type adds its entry here.
const examples: Record<string, { config: unknown; fallbackText: string | RegExp }> = {
  markdown: { config: { markdown: '## Heading\n\nSome **bold** text.' }, fallbackText: /Some \*\*bold\*\* text\./ },
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
        const parsed = parseStoredWidget({ type, v: definition.v, config }, surface);
        expect(parsed).toMatchObject({ ok: true, instance: { type, v: definition.v, config } });
        expect(checkWidgetWrite({ type, v: definition.v, config }, surface)).toEqual({ ok: true });
      }
    });

    it('rejects configs of the wrong shape', () => {
      for (const config of [undefined, null, 'text', 42, []]) {
        expect(parseStoredWidget({ type, v: definition.v, config }, surface)).toMatchObject({
          ok: false,
          reason: 'invalid_config',
        });
      }
    });

    it('rejects an unknown type on write', () => {
      const unknown = { type: `${type}-from-the-future`, v: 1, config: example.config };
      expect(checkWidgetWrite(unknown, surface)).toEqual({ ok: false, reason: 'unknown_type' });
      expect(checkWidgetWrite({ ...unknown, v: definition.v + 1, type }, surface)).toEqual({
        ok: false,
        reason: 'unsupported_version',
      });
    });

    it('keeps an unparseable stored instance and lets a save carry it back unchanged', () => {
      const stored = [
        { type: `${type}-from-the-future`, v: 1, config: { anything: [1, 2] } },
        { type, v: definition.v + 1, config: example.config },
        { type, v: definition.v, config: { broken: true } },
      ];
      for (const raw of stored) {
        const parsed = parseStoredWidget(raw, surface);
        expect(parsed.ok).toBe(false);
        expect(serializeWidget(parsed)).toBe(raw);
        // The server's JSONB copy may come back with keys reordered.
        const reordered = Object.fromEntries(Object.entries(raw).reverse());
        expect(checkWidgetWrite(reordered, surface, stored)).toEqual({ ok: true });
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
    const instance = { type: storyOnly!.type, v: storyOnly!.v, config: storyOnly!.defaultConfig };
    expect(checkWidgetWrite(instance, 'dashboard')).toEqual({ ok: false, reason: 'unknown_type' });
  });

  it('marks instances without a string type or integer v as malformed', () => {
    for (const raw of [null, 'markdown', [], { v: 1, config: {} }, { type: 'markdown', v: '1', config: {} }]) {
      expect(parseStoredWidget(raw, 'story')).toMatchObject({ ok: false, reason: 'malformed', raw });
    }
  });

  it('passes surface fields other than type, v and config through', () => {
    const parsed = parseStoredWidget(
      { type: 'markdown', v: 1, config: { markdown: 'x' }, layer: 'layer-1' },
      'story',
    );
    expect(serializeWidget(parsed)).toEqual({
      type: 'markdown',
      v: 1,
      config: { markdown: 'x' },
      layer: 'layer-1',
    });
  });

  it('saves a document with readable and unreadable instances back unchanged', () => {
    const story: WidgetDocument & { blocks: unknown[] } = {
      version: 1,
      blocks: [
        { type: 'markdown', v: 1, config: { markdown: 'Intro' } },
        { type: 'future', v: 3, config: { a: 1 } },
        'not an instance',
      ],
    };
    const blocks = story.blocks.map((raw) => serializeWidget(parseStoredWidget(raw, 'story')));
    expect(blocks).toEqual(story.blocks);
    expect(blocks.every((block) => checkWidgetWrite(block, 'story', story.blocks).ok)).toBe(true);
  });

  it('refuses a changed copy of a stored instance it cannot parse', () => {
    const stored = [{ type: 'future', v: 1, config: { a: 1 } }];
    expect(checkWidgetWrite({ type: 'future', v: 1, config: { a: 2 } }, 'story', stored)).toEqual({
      ok: false,
      reason: 'unknown_type',
    });
  });

  it('shows a notice for an instance it cannot parse', () => {
    render(<WidgetView parsed={parseStoredWidget({ type: 'future', v: 1, config: {} }, 'story')} />);
    expect(screen.getByText(/can't be shown/)).toBeInTheDocument();
  });
});
