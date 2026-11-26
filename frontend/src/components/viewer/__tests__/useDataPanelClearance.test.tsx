import { render } from '@testing-library/react';
import { useEffect, useRef } from 'react';
import { describe, expect, it } from 'vitest';
import { useDataPanelClearance } from '../useDataPanelClearance';

function Slot({ height }: { height?: number }) {
  const shellRef = useRef<HTMLDivElement>(null);
  const report = useDataPanelClearance(shellRef);
  useEffect(() => {
    if (height === undefined) return;
    report(height);
    return () => report(0);
  }, [height, report]);
  return <div ref={shellRef} />;
}

function Frames({ outgoing, active }: { outgoing?: number | null; active?: number }) {
  return (
    // Both frames sit under one #map-viewport, as a story's outgoing and active slots do.
    <div id="map-viewport">
      {outgoing !== null && <div data-testid="outgoing" data-map-frame><Slot height={outgoing} /></div>}
      <div data-testid="active" data-map-frame><Slot height={active} /></div>
    </div>
  );
}

const VAR = '--viewer-data-panel-height';
const read = (el: HTMLElement) => el.style.getPropertyValue(VAR);

describe('useDataPanelClearance', () => {
  it('gives each frame only its own table height', () => {
    const { getByTestId } = render(<Frames outgoing={240} active={280} />);
    expect(read(getByTestId('outgoing'))).toBe('240px');
    expect(read(getByTestId('active'))).toBe('280px');
  });

  it('leaves the active frame alone when a hidden frame with an open table closes or unmounts', () => {
    const { getByTestId, rerender } = render(<Frames outgoing={240} active={240} />);
    rerender(<Frames outgoing={0} active={240} />);
    expect(read(getByTestId('active'))).toBe('240px');
    rerender(<Frames outgoing={null} active={240} />);
    expect(read(getByTestId('active'))).toBe('240px');
  });

  it('does not pass a hidden frame its table to the active frame', () => {
    const { getByTestId } = render(<Frames outgoing={240} />);
    expect(read(getByTestId('active'))).toBe('');
    expect(read(getByTestId('outgoing'))).toBe('240px');
    expect(read(getByTestId('outgoing').parentElement!)).toBe('');
  });

  it('resets a frame when its own table closes', () => {
    const { getByTestId, rerender } = render(<Frames active={240} />);
    rerender(<Frames active={0} />);
    expect(read(getByTestId('active'))).toBe('0px');
  });
});
