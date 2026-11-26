import { render } from '@testing-library/react';
import { useRef, useEffect } from 'react';
import { describe, expect, it } from 'vitest';
import { useDataPanelClearance } from '../useDataPanelClearance';

function Slot({ height }: { height?: number }) {
  const shellRef = useRef<HTMLDivElement>(null);
  const report = useDataPanelClearance(shellRef);
  useEffect(() => {
    if (height !== undefined) report(height);
    return () => { if (height !== undefined) report(0); };
  }, [height, report]);
  return <div ref={shellRef} />;
}

function viewport(container: HTMLElement) {
  return container.querySelector<HTMLElement>('#map-viewport')!;
}

describe('useDataPanelClearance', () => {
  it('publishes the table height on the viewport', () => {
    const { container } = render(<div id="map-viewport"><Slot height={240} /></div>);
    expect(viewport(container).style.getPropertyValue('--viewer-data-panel-height')).toBe('240px');
  });

  it('keeps the active map value when a standby map with no table unmounts', () => {
    const { container, rerender } = render(
      <div id="map-viewport"><Slot height={240} /><Slot key="standby" /></div>,
    );
    rerender(<div id="map-viewport"><Slot height={240} /></div>);
    expect(viewport(container).style.getPropertyValue('--viewer-data-panel-height')).toBe('240px');
  });
});
