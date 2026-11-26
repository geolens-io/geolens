import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { SkipToContent } from '@/components/layout/SkipToContent';

describe('SkipToContent', () => {
  it('keeps the router history state when it adds the hash', async () => {
    window.history.replaceState({ idx: 2, key: 'k', usr: null }, '', '/');
    render(
      <>
        <SkipToContent />
        <main id="main-content" tabIndex={-1} />
      </>,
    );

    await userEvent.click(screen.getByRole('link'));

    expect(window.location.hash).toBe('#main-content');
    expect(window.history.state).toEqual({ idx: 2, key: 'k', usr: null });
  });
});
