import { render, screen } from '@/test/test-utils';
import { ApiKeyRevealDialog } from '../ApiKeyRevealDialog';
import type { ApiKeyCreateResponse } from '@/types/api';

describe('ApiKeyRevealDialog', () => {
  it('gives the icon-only copy button an accessible name', () => {
    const apiKey = { key: 'gl_example_key' } as ApiKeyCreateResponse;
    render(<ApiKeyRevealDialog apiKey={apiKey} open onOpenChange={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Copy API key' })).toBeInTheDocument();
  });
});
