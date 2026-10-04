import { render, screen } from '@/test/test-utils';
import { describe, it, expect } from 'vitest';
import { MapTitlePill } from '../MapTitlePill';

describe('MapTitlePill', () => {
  it('stays clear of the right-hand controls at narrow widths', () => {
    render(<MapTitlePill name="A very long shared map name" />);

    const pill = screen.getByRole('heading', { name: 'A very long shared map name' }).closest('div.absolute');
    expect(pill?.className).toContain('max-w-[calc(100%-7.5rem)]');
    expect(pill?.className).not.toContain('max-w-[320px]');
  });
});
