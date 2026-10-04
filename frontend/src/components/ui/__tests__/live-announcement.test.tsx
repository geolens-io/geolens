import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LiveAnnouncement } from '../live-announcement';

describe('LiveAnnouncement', () => {
  it('mounts empty, then writes the text after the delay', () => {
    vi.useFakeTimers();
    try {
      render(<LiveAnnouncement text="Done" delayMs={500} />);
      const region = screen.getByRole('status');
      expect(region).toBeEmptyDOMElement();
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(region).toHaveTextContent('Done');
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears and refills when the trigger changes with identical text', () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(<LiveAnnouncement text="3 results" trigger="a" />);
      act(() => {
        vi.advanceTimersByTime(0);
      });
      const region = screen.getByRole('status');
      expect(region).toHaveTextContent('3 results');

      rerender(<LiveAnnouncement text="3 results" trigger="b" />);
      expect(region).toBeEmptyDOMElement();
      act(() => {
        vi.advanceTimersByTime(0);
      });
      expect(region).toHaveTextContent('3 results');
    } finally {
      vi.useRealTimers();
    }
  });
});
