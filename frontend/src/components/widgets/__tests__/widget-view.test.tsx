import { lazy } from 'react';
import { screen } from '@testing-library/react';
import { render } from '@/test/test-utils';
import type { AnyWidgetDefinition } from '../contract';
import type { ParsedWidget } from '../registry';
import { WidgetView } from '../WidgetView';

function parsedWith(loadRenderer: () => Promise<{ default: () => null }>): ParsedWidget {
  const definition = {
    type: 'probe',
    Fallback: () => <p>text fallback</p>,
    Renderer: lazy(loadRenderer),
    loadRenderer,
  } as unknown as AnyWidgetDefinition;
  return {
    ok: true,
    definition,
    instance: { id: 'w', type: 'probe', v: 1, config: {} },
  } as unknown as ParsedWidget;
}

describe('WidgetView', () => {
  it('shows the loading fallback, not the text fallback, while the renderer loads', () => {
    const parsed = parsedWith(() => new Promise(() => {}));
    render(<WidgetView parsed={parsed} loadingFallback={<div>skeleton</div>} />);
    expect(screen.getByText('skeleton')).toBeInTheDocument();
    expect(screen.queryByText('text fallback')).not.toBeInTheDocument();
  });

  it('keeps the text fallback while loading when no loading fallback is given', () => {
    const parsed = parsedWith(() => new Promise(() => {}));
    render(<WidgetView parsed={parsed} />);
    expect(screen.getByText('text fallback')).toBeInTheDocument();
  });

  it('shows the text fallback when the renderer fails to load', async () => {
    const parsed = parsedWith(() => Promise.reject(new Error('chunk failed')));
    render(<WidgetView parsed={parsed} loadingFallback={<div>skeleton</div>} />);
    expect(await screen.findByText('text fallback')).toBeInTheDocument();
    expect(screen.queryByText('skeleton')).not.toBeInTheDocument();
  });
});
